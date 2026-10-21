"""Small, contract-tested hooks into the running bridge: iClaude's tools and conversation context."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

log = logging.getLogger("iclaude.hooks")

CHATS_FILE = Path.home() / ".iclaude" / "chats.json"
TOOL_SERVER = "iclaude"

_lock = threading.Lock()
_bridge: dict[str, Any] = {"loop": None, "manager": None, "env": dict}


def current_session() -> Any:
    try:
        from inkbox_claude.tools import CURRENT_SESSION
    except ImportError:
        return None
    return CURRENT_SESSION.get()


def session_contact(session: Any) -> str:
    """The phone number or email of the person a bridge session is talking to."""
    meta = getattr(session, "reply_meta", None) or {}
    return str(meta.get("sender") or meta.get("to") or "").strip()


def load_chats(path: Path | None = None) -> dict[str, str]:
    path = path or CHATS_FILE
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def remember_chat(contact: str, chat_id: str, path: Path | None = None) -> None:
    path = path or CHATS_FILE
    with _lock:
        chats = load_chats(path)
        if chats.get(contact) == chat_id:
            return
        chats[contact] = chat_id
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(chats, indent=2))
        tmp.replace(path)


def add_context(contact: str, text: str, key: str) -> bool:
    """Quietly add text to a contact's conversation; Claude sees it with their next message."""
    loop, manager = _bridge["loop"], _bridge["manager"]
    chat_id = load_chats().get(contact)
    if loop is None or manager is None or not chat_id or loop.is_closed():
        return False

    def buffer() -> None:
        try:
            manager.get(chat_id).buffer_context(text, key)
        except Exception:
            log.warning("Could not add a notification to the conversation", exc_info=True)

    loop.call_soon_threadsafe(buffer)
    return True


def stream_updates(client, session) -> None:
    """Send the text Claude writes before a tool call as it happens, throttled."""
    from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock

    from . import chat_flow

    original_receive = client.receive_response

    async def receive_response():
        turn = session._current_turn
        mode, meta = session._reply_route()
        live = (turn is not None and turn.future is None and turn.checkpoint is None
                and chat_flow.applies(mode, meta) and chat_flow.style(_bridge["env"]()) == "natural")
        updates, pending = chat_flow.Updates(), []
        if live:
            session._iclaude_updates = (turn, updates.sent)
        async for message in original_receive():
            if live and isinstance(message, AssistantMessage) and not getattr(message, "parent_tool_use_id", None):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        pending.append(block.text)
                    elif isinstance(block, ToolUseBlock) and pending:
                        text = updates.take("\n\n".join(pending))
                        pending.clear()
                        if text and session._current_turn is turn and not session._interrupting and not turn.cancelled:
                            try:
                                await session._reply(text)
                            except Exception:
                                log.warning("Could not send a progress update", exc_info=True)
            yield message

    client.receive_response = receive_response



def install(tool_factory=None, env_factory=None) -> None:
    """Record where conversations live; give bridge sessions iClaude's tools and auto-approvals."""
    from claude_agent_sdk import ClaudeSDKClient, PermissionResultAllow
    from inkbox_claude.sessions import ContactSession, SessionManager

    from . import approvals, chat_flow

    if env_factory:
        _bridge["env"] = env_factory

    if getattr(SessionManager.__init__, "_iclaude", False):
        return

    original_manager = SessionManager.__init__

    def manager_init(self, *args, **kwargs):
        original_manager(self, *args, **kwargs)
        _bridge["manager"] = self
        try:
            _bridge["loop"] = asyncio.get_running_loop()
        except RuntimeError:
            pass

    original_inbound = ContactSession.handle_inbound

    async def handle_inbound(self, text, mode, meta):
        _bridge["loop"] = asyncio.get_running_loop()
        sender = str((meta or {}).get("sender") or "").strip()
        if sender and (meta or {}).get("conversation_kind", "direct") == "direct" and mode in ("imessage", "sms"):
            try:
                remember_chat(sender, self.chat_id)
            except OSError:
                log.warning("Could not record the conversation for %s", mode)
        return await original_inbound(self, text, mode, meta)

    original_can_use = ContactSession._can_use_tool

    async def can_use_tool(self, tool_name, input_data, context):
        if not (self.reply_meta or {}).get("companion") and approvals.auto_approves(tool_name, _bridge["env"]()):
            if self._current_turn is not None:
                self._current_turn.execution_observed = True
            log.info("Auto-approved %s (%s)", tool_name, approvals.categorise(tool_name))
            return PermissionResultAllow()
        return await original_can_use(self, tool_name, input_data, context)

    original_deliver = ContactSession._deliver_reply

    async def deliver_reply(self, turn, reply):
        mode, meta = turn.mode or self.mode, deepcopy(turn.reply_meta or self.reply_meta)
        if chat_flow.style(_bridge["env"]()) != "natural" or not chat_flow.applies(mode, meta):
            return await original_deliver(self, turn, reply)
        owner, sent = getattr(self, "_iclaude_updates", (None, []))
        parts = chat_flow.bubbles(reply, sent if owner is turn else [])
        if not parts:
            return await self.receipt(mode, meta, "done")
        for i, part in enumerate(parts[:-1]):
            if turn.cancelled or self._shutting_down:
                return None
            try:
                await self.send_fn(self.chat_id, part, mode, deepcopy(meta))
            except Exception:
                log.warning("Could not send part of a reply; sending the rest as one message", exc_info=True)
                return await original_deliver(self, turn, "\n\n".join(parts[i:]))
            await asyncio.sleep(chat_flow.BUBBLE_PAUSE_SECONDS)
        return await original_deliver(self, turn, parts[-1])

    original_init = ClaudeSDKClient.__init__

    def init(self, options=None, *args, **kwargs):
        servers = getattr(options, "mcp_servers", None)
        if isinstance(servers, dict) and "inkbox" in servers and current_session() is not None:
            if tool_factory:
                server, names = tool_factory()
                options = dataclasses.replace(
                    options,
                    mcp_servers={**servers, TOOL_SERVER: server},
                    allowed_tools=list(options.allowed_tools) + [f"mcp__{TOOL_SERVER}__{n}" for n in names],
                )
            if options.permission_mode is None and approvals.auto_mode(Path.home()):
                options = dataclasses.replace(options, permission_mode="auto")
            env = _bridge["env"]()
            notes = [approvals.prompt_text(env), chat_flow.PROMPT if chat_flow.style(env) == "natural" else ""]
            note = "\n\n".join(n for n in notes if n)
            prompt = options.system_prompt
            if note and isinstance(prompt, dict) and prompt.get("type") == "preset":
                append = f"{prompt['append']}\n\n{note}" if prompt.get("append") else note
                options = dataclasses.replace(options, system_prompt={**prompt, "append": append})
            original_init(self, options, *args, **kwargs)
            stream_updates(self, current_session())
            return
        original_init(self, options, *args, **kwargs)

    manager_init._iclaude = True
    SessionManager.__init__ = manager_init
    ContactSession.handle_inbound = handle_inbound
    ContactSession._can_use_tool = can_use_tool
    ContactSession._deliver_reply = deliver_reply
    ClaudeSDKClient.__init__ = init

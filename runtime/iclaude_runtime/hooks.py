"""Small, contract-tested hooks into the running bridge: iClaude's tools and conversation context."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("iclaude.hooks")

CHATS_FILE = Path.home() / ".iclaude" / "chats.json"
TOOL_SERVER = "iclaude"

_lock = threading.Lock()
_bridge: dict[str, Any] = {"loop": None, "manager": None}


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


def install(tool_factory=None) -> None:
    """Record where conversations live and give bridge sessions iClaude's tools."""
    from claude_agent_sdk import ClaudeSDKClient
    from inkbox_claude.sessions import ContactSession, SessionManager

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

    original_init = ClaudeSDKClient.__init__

    def init(self, options=None, *args, **kwargs):
        servers = getattr(options, "mcp_servers", None)
        if tool_factory and isinstance(servers, dict) and "inkbox" in servers and current_session() is not None:
            server, names = tool_factory()
            options = dataclasses.replace(
                options,
                mcp_servers={**servers, TOOL_SERVER: server},
                allowed_tools=list(options.allowed_tools) + [f"mcp__{TOOL_SERVER}__{n}" for n in names],
            )
        original_init(self, options, *args, **kwargs)

    manager_init._iclaude = True
    SessionManager.__init__ = manager_init
    ContactSession.handle_inbound = handle_inbound
    ClaudeSDKClient.__init__ = init

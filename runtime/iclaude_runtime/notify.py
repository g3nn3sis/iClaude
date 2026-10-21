"""iClaude's own notifications: an iMessage to an authorised phone, mirrored into that conversation."""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Mapping

from . import hooks
from .checks import PHONE_RE, parse_contacts

log = logging.getLogger("iclaude.notify")


def owner(env: Mapping[str, str]) -> tuple[str, str]:
    """Return (phone, problem) for the person iClaude notifies unprompted."""
    allowed, _ = parse_contacts(env.get("INKBOX_ALLOWED_USERS", ""))
    phones = [c for c in allowed if PHONE_RE.match(c)]
    phone = (env.get("ICLAUDE_ALERT_TO") or "").strip() or (phones[0] if phones else "")
    if not phone:
        return "", "No phone number to notify. Authorise your iMessage number or set ICLAUDE_ALERT_TO."
    if phone not in allowed:
        return phone, f"{phone} is not an authorised contact."
    if not PHONE_RE.match(phone):
        return phone, f"{phone} is not a +E.164 phone number."
    return phone, ""


def authorised_phone(env: Mapping[str, str], contact: str) -> bool:
    allowed, _ = parse_contacts(env.get("INKBOX_ALLOWED_USERS", ""))
    return bool(PHONE_RE.match(contact)) and contact in allowed


def stable_key(prefix: str, *parts: str) -> str:
    return f"iclaude-{prefix}-" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


class Notifier:
    def __init__(self, env: Mapping[str, str]):
        self.env = env
        self._identity = None
        self._lock = threading.Lock()

    def identity(self):
        with self._lock:
            if self._identity is None:
                from inkbox import Inkbox
                from inkbox_claude.config import inkbox_client_kwargs

                client = Inkbox(**inkbox_client_kwargs(self.env.get("INKBOX_API_KEY", ""), self.env.get("INKBOX_BASE_URL")))
                self._identity = client.get_identity(self.env.get("INKBOX_IDENTITY", ""))
            return self._identity

    def send(self, to: str, text: str, key: str, context: str | None = None) -> None:
        """Send to an authorised phone only, then let Claude see it in that conversation."""
        if not authorised_phone(self.env, to):
            raise PermissionError("Notifications only go to authorised phone numbers")
        try:
            self.identity().send_imessage(to=to, text=text, idempotency_key=key)
        except Exception:
            self._identity = None
            raise
        note = "Earlier, iClaude sent this contact the notification below (context only, not their message):\n" + (context or text)
        hooks.add_context(to, note, key)

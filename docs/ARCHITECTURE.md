# iClaude architecture and plan

iClaude is a thin deployment layer. The [Inkbox Claude Code bridge](https://github.com/inkbox-ai/claude-code-plugin)
does all messaging, tunnelling, webhook verification, contact-keyed sessions and
permission escalation. iClaude packages it into a supervised container, adds the
security checks a public-facing deployment needs, and wraps setup in a few commands.

## What the upstream bridge already provides (reused, not rebuilt)

Inspected at commit `a02722d` (v0.2.14, 2026-10-08).

| Need | Upstream feature |
|---|---|
| iMessage, SMS, email, voice | `inkbox-claude run` gateway |
| Inbound connectivity without open ports | Inkbox tunnel opened on start |
| Webhook signature verification | `INKBOX_SIGNING_KEY`, `INKBOX_REQUIRE_SIGNATURE=true` by default |
| Inkbox signup, identity, iMessage connect, signing key | `inkbox-claude setup` wizard |
| Contact-keyed Claude sessions across restarts | `~/.inkbox-claude/sessions.json` + Claude transcripts in `~/.claude/projects` |
| Approval texts for dangerous tools | `can_use_tool` escalation; read-only tools auto-allowed |
| Per-contact memory | Inkbox contact memories injected per contact (`INKBOX_CONTACT_MEMORIES_ENABLED`) |
| CLAUDE.md / settings | `setting_sources=["user", "project"]` |
| Health | `/health` (liveness) and `/ready` (includes Claude auth) on port 8767 |
| Diagnostics | `inkbox-claude doctor` |

## What iClaude adds

1. **Image** (`Dockerfile`): Debian bookworm, Python venv with the pinned bridge,
   `gh` (checksum-verified), Git, Node 22, non-root `iclaude` user (uid 1000).
2. **One Claude binary.** The Agent SDK runs its own bundled Claude Code, so the image
   links that binary as `claude` instead of installing a second copy from npm. Login,
   `auth status` and the bridge always use the same version.
3. **Supervision** (`compose.yaml`): `restart: unless-stopped`, `init: true`, read-only
   root filesystem, all capabilities dropped, `no-new-privileges`, log rotation,
   no published ports (the Inkbox tunnel is outbound).
4. **Persistence**: one named volume for `/home/iclaude` (Claude credentials and
   `.claude.json`, bridge `.env`, sessions, media, `gh` auth, git config) and one for
   `/workspace` (Claude's project directory).
5. **Preflight gate** (`runtime/iclaude_runtime`): the container only execs the bridge
   when every check passes, and otherwise waits and rechecks every 30 s, so
   a half-configured deployment never crash-loops or runs insecurely:
   - Claude is logged in (`claude auth status`)
   - Inkbox identity and signing key exist, signatures not disabled
   - an explicit contact allowlist is set and `INKBOX_ALLOW_ALL_USERS` is not true
   - no `bypassPermissions` default mode in user or workspace settings
   - workspace is writable
6. **Docker-aware setup**: runs the upstream wizard unchanged except for two steps.
   Project directory is fixed to the workspace volume, and systemd/launchd autostart
   is replaced by Docker's restart policy. After the wizard it asks for the
   allowlist.
7. **Host CLI** (`./iclaude`): setup, login, allow, start, stop, restart, status, check,
   logs, doctor, connectors, alerts, briefing, reminders, voice, backup, restore, update,
   auto-update, reset, uninstall, shell.
8. **Installer** (`install.sh`): checks Docker, clones or updates the repo, links the CLI,
   starts the container, then runs login and setup only when their checks fail.
9. **Conversational defaults**: a user-level `~/.claude/CLAUDE.md` seeded once (never
   overwritten) that sets tone and requires confirmation for outward or irreversible
   actions. The bridge auto-allows its own Inkbox send tools, so this is the guard against
   messaging third parties unasked. No custom memory system: Claude Code auto memory
   plus Inkbox contact memories cover it.

10. **Bridge launcher** (`iclaude_runtime/bridge.py`): starts the upstream `inkbox-claude run`
    in-process after two additions, so the bridge itself stays unmodified:
    - **Usage-limit reply.** `ClaudeSDKClient.receive_response` is wrapped so that a turn
      ending in Claude's subscription limit (an assistant `error="rate_limit"`, a rejected
      `RateLimitEvent`, or the CLI's "hit your limit" result) is answered with
      "Usage reached. Claude is available again at 17:00 (BST)." instead of the raw CLI line.
      Successful turns are never rewritten.
    - **Hooks** (`hooks.py`). They record which bridge conversation belongs to which phone
      number. They mirror iClaude's notifications into that conversation through the bridge's
      own `buffer_context`, so Claude sees them as context with the next message. They also
      give every bridge session an in-process MCP server (`iclaude`) with `remind`,
      `list_reminders` and `cancel_reminder`. Those tools act only for the contact of the
      current session (the bridge's `CURRENT_SESSION`) and only for authorised phone numbers.
    - **Scheduler** (`scheduler.py`): one daemon thread with a 15 s tick that runs every
      unprompted feature. Each job is isolated, so one failing source never stops the rest.
      Every outbound message goes through `notify.Notifier`, which refuses anything but an
      authorised phone and uses idempotency keys, so a retry never double-sends.
      - Reminders (`reminders.py`) are fixed text, with no Claude turn.
      - Email alerts (`alerts.py`, opt-in) poll the Inkbox agent inbox (Inkbox SDK) and,
        optionally, Fastmail (JMAP, read-only token) every 30 s, with cached clients. New mail
        goes to one Claude turn (Haiku by default) with **no tools, no MCP servers, no
        settings or CLAUDE.md** and a deny-all permission callback. The emails are labelled
        as untrusted data. Links are removed from the result. Cursors advance only after
        triage and sending succeed. A usage limit pauses polling. A batch is skipped after
        three failed attempts.
      - Calendar heads-ups and the morning briefing read CalDAV (`caldav.py`), with server-side
        recurrence expansion.
      - The usage warning reads the same `/api/oauth/usage` endpoint as Claude Code's `/usage`,
        through the bridge's `claude_usage` module.
      - GitHub (`gh api notifications`), Vercel and Cloudflare Pages (`watchers.py`) are
        rule-based. None of these use Claude.

### Security decision: local allowlist

The upstream wizard writes `INKBOX_ALLOW_ALL_USERS=true` and relies on Inkbox
server-side contact rules. The bridge also treats an empty `INKBOX_ALLOWED_USERS` as
"everyone". Because Claude here has a shell and the owner's connectors, iClaude
requires an explicit local allowlist on top of the contact rules and refuses to start
without one.

### Known limits to resolve in later phases

- **Contact isolation.** Sessions and Inkbox contact memories are per contact.
  Claude Code's auto memory is per project directory, so iClaude sets
  `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` when more than one contact is authorised (opt out
  with `ICLAUDE_SHARED_MEMORY=true`). Files in `/workspace` are still shared, so the
  recommended setup is a single owner contact. Full isolation would need per-contact
  workspaces, which the bridge does not support today.
- **Connectors.** Claude.ai remote connectors load from the logged-in account, with no
  MCP configuration in iClaude. `iclaude connectors` opens a session with the bridge's
  setting sources and reads the live MCP status without a model turn. Connector tools are
  not in the bridge's auto-allowed list, so each call is approved by text. This has not
  yet been checked against a real account.

## Phases

| Phase | Scope | Status |
|---|---|---|
| 1. Research | Inspect bridge, decide architecture (this document) | Done |
| 2. Docker MVP | Image, Compose, volumes, login, preflight, host CLI | Done; live auth untested |
| 3. Easy install | `install.sh` for fresh VPS, default conversational CLAUDE.md, memory defaults | Done; live auth untested |
| 4. Test & release | Live checklist (`docs/VERIFY.md`), `iclaude connectors`, CI, v0.1.0 changelog | Done; tag after live verification |

## Pinned versions

| Component | Pin | Where |
|---|---|---|
| Inkbox bridge | `a02722d` | `Dockerfile` `BRIDGE_REF` |
| inkbox SDK | 0.7.20 | `docker/constraints.txt` |
| claude-agent-sdk (and bundled Claude Code) | 0.2.170 (Claude Code 2.1.306) | `docker/constraints.txt` |
| GitHub CLI | 2.101.0 | `Dockerfile` `GH_VERSION` |
| Base | `node:22-bookworm-slim` | `Dockerfile` `BASE_IMAGE` |

# Changelog

## 0.1.0 (unreleased)

First release. Tag it after the [live verification](docs/VERIFY.md) passes.

- Docker image with the Inkbox Claude Code bridge (`a02722d`), Claude Code (bundled with
  claude-agent-sdk 0.2.170), Python, Git and the GitHub CLI, running as a non-root user
- Compose deployment: restart policy, read-only root filesystem, no capabilities, no
  published ports, persistent home and workspace volumes
- Claude Pro/Max subscription login inside the container (`iclaude login`)
- Preflight gate: the bridge starts only with Claude logged in, signed webhooks, an explicit
  contact allowlist and permission prompts enabled
- One-command installer and `iclaude` host CLI (setup, login, allow, start, stop, restart,
  status, check, logs, doctor, connectors, update, shell)
- Default conversational `CLAUDE.md` that requires confirmation for outward or irreversible
  actions
- Claude auto memory, turned off automatically when several contacts share the workspace
- `iclaude connectors` reports which claude.ai connectors a bridged session can reach
- `iclaude update` with automatic rollback, `iclaude auto-update on|off|status` (daily cron),
  and `iclaude uninstall [--purge]`
- Email alerts (`iclaude alerts`): opt-in iMessage alerts for new mail in the Inkbox
  agent inbox and Fastmail that needs you, with suggested replies, triaged by a tool-less
  Claude turn
- "Usage reached" reply with the reset time when the Claude subscription limit is hit
- Reminders and scheduled messages set by text (`remind`, `list_reminders` and
  `cancel_reminder` tools), plus `iclaude reminders`
- Auto-approve (`iclaude approve on|off calendar email deploy delete pay|all`): routine
  connector actions run without an approval text or confirmation; off by default, shell
  commands and file edits always ask
- Claude Code auto mode (`iclaude auto-mode on|off`): sets `permissions.defaultMode` to `auto`
  in the user settings, so a safety classifier approves routine actions instead of texts
- OpenRouter models (`iclaude model openrouter|claude`): run Claude Code through OpenRouter
  with a main and a fast model, key and models checked before saving
- Natural replies (`iclaude replies natural|single`, natural by default): over iMessage and
  SMS a heads-up when work starts, throttled progress updates, and the result split into one
  text per paragraph
- Morning briefing (`iclaude briefing`), calendar heads-ups over CalDAV, a usage warning
  before the limit, and GitHub, Vercel and Cloudflare Pages alerts, all polled without
  Claude usage
- Notifications are mirrored into your conversation, so Claude can act on "reply to that"
- `iclaude voice` to switch calls between Inkbox voice and OpenAI Realtime
- `iclaude backup` / `iclaude restore`
- `iclaude reset`: factory reset that forgets conversations, memory and workspace files but
  keeps the Claude login, Inkbox config and authorised contacts
- CI: unit and contract tests, ShellCheck, production image build, container and installer
  smoke tests

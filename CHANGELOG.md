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
- `iclaude reset`: factory reset that forgets conversations, memory and workspace files but
  keeps the Claude login, Inkbox config and authorised contacts
- CI: unit and contract tests, ShellCheck, production image build, container and installer
  smoke tests

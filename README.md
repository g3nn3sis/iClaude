# iClaude

An always-online Claude Code assistant on your own Linux VPS that you talk to over iMessage.
iClaude packages the official [Inkbox Claude Code bridge](https://github.com/inkbox-ai/claude-code-plugin)
into a hardened Docker deployment. It uses your Claude Pro/Max subscription, not an API key.

> Status: **v0.1 in progress.** Everything below runs locally. The Claude login and Inkbox
> steps need your real accounts, so they have not yet been tested end to end. See
> [What has been tested](#what-has-been-tested).

## Requirements

- Ubuntu or Debian host with Docker Engine and the Compose v2 plugin
- A Claude Pro or Max subscription
- An iPhone for iMessage (the Inkbox account is created during setup)

## Install

On the VPS, as a user in the `docker` group:

```bash
curl -fsSL https://raw.githubusercontent.com/g3nn3sis/iClaude/master/install.sh | bash
```

The installer checks Docker, clones iClaude to `~/iclaude`, links the `iclaude` command into
`~/.local/bin`, builds and starts the container, then walks you through:

1. **Claude login.** Open the URL it prints, approve with your Pro/Max account, and paste the code back.
2. **Inkbox setup.** The official Inkbox wizard creates the agent, connects iMessage (scan the QR
   code on your iPhone) and mints the webhook signing key.
3. **Authorised contacts.** Enter your iMessage phone number (`+15551234567`) and/or Apple ID email.

Re-running the installer is safe: it updates and skips finished steps. Options: `--dir <path>`,
`--ref <branch-or-tag>`, `--no-setup`.

Manual alternative:

```bash
git clone https://github.com/g3nn3sis/iClaude.git && cd iClaude
./iclaude start && ./iclaude login && ./iclaude setup && ./iclaude status
```

The container stays in a "waiting for setup" state until every check passes, then starts the
bridge on its own. Docker restarts it after crashes and reboots.

## Commands

| Command | What it does |
|---|---|
| `./iclaude login` | Claude subscription login (rerun if credentials expire) |
| `./iclaude setup` | Inkbox setup wizard and contact allowlist; rerun to reconfigure |
| `./iclaude allow [+15551234567 \| me@icloud.com]` | Show or add authorised contacts (`--remove`, `--replace`) |
| `./iclaude start` / `stop` / `restart` | Control the container |
| `./iclaude status` | Container health plus preflight checks |
| `./iclaude check [claude\|inkbox\|…]` | Preflight checks only, exit code 0 when they pass |
| `./iclaude logs [-f]` | Bridge logs |
| `./iclaude doctor` | iClaude checks, bridge readiness and the upstream `inkbox-claude doctor` |
| `./iclaude connectors` | Which claude.ai connectors (GitHub, Fastmail, Vercel, Cloudflare, …) a bridged session can reach |
| `./iclaude update` | Pull the latest version, rebuild and restart; rolls back if checks start failing |
| `./iclaude auto-update [on\|off\|status]` | Daily automatic updates (cron, around 04:00 server time) |
| `./iclaude reset` | Factory reset: forget conversations, memory and workspace files, keep logins and config |
| `./iclaude uninstall [--purge]` | Remove iClaude; `--purge` also deletes your data |
| `./iclaude shell` | Shell inside the container (`claude`, `gh`, `git` available) |

## Security model

- **Only listed contacts get answers.** iClaude refuses to start unless `INKBOX_ALLOWED_USERS`
  lists explicit phone numbers or emails, on top of Inkbox contact rules.
- **Webhook signatures stay on.** A missing signing key or `INKBOX_REQUIRE_SIGNATURE=false` blocks startup.
- **Approvals stay on.** Commands, edits and other risky tools are texted to you for approval
  (`1` allow, `2` always for this session, `3` deny). iClaude refuses to start if any Claude
  settings file sets `bypassPermissions`.
- **Secrets stay out of the image and Git.** Credentials live only in the `home` volume, and
  the bridge's `.env` is mode 600.
- **Container hardening.** Non-root user, read-only root filesystem, no capabilities,
  `no-new-privileges`, and no published ports (Inkbox reaches the bridge through an outbound tunnel).

## Conversations and memory

- **One conversation per contact.** The bridge keys each Claude session by Inkbox contact and
  resumes it after restarts. Text `/clear` to start fresh or `/resume` to pick an older one.
- **Default personality.** On first start iClaude installs `~/.claude/CLAUDE.md` in the home
  volume: a brief, conversational assistant that confirms before acting for you (emails to
  others, public posts, deploys, deletes, payments). Edit it with `./iclaude shell`. It is
  never overwritten, so delete it and restart to get the latest default back. A repo's own
  `CLAUDE.md` in the workspace is loaded as well.
- **Memory.** Claude Code's built-in auto memory and Inkbox's per-contact memories are both on.
  Auto memory is per workspace, so it is turned off automatically when more than one contact
  is authorised. That keeps contacts from seeing each other's facts. Set
  `ICLAUDE_SHARED_MEMORY=true` in `.env` next to `compose.yaml` only if every contact may share it.

## Where state lives

| Volume | Mount | Contents |
|---|---|---|
| `iclaude_home` | `/home/iclaude` | Claude login, bridge config and sessions, `gh` login, git config |
| `iclaude_workspace` | `/workspace` | Claude's working directory (repos, files, `CLAUDE.md`) |

Back up with `docker run --rm -v iclaude_home:/v -v "$PWD":/b alpine tar czf /b/home.tgz -C /v .`
while iClaude is stopped. `docker compose down -v` **deletes** all state.

## Updates

`iclaude update` fast-forwards the checkout, rebuilds the image and restarts the container.
Your data is kept. If iClaude was passing all its checks before the update and stops passing
them within three minutes afterwards, it rolls back to the previous version and image on its own.

`iclaude auto-update on` runs the same update daily from cron. It does nothing when there
are no new commits, except once a week, when it rebuilds anyway to pick up Debian security
updates. It never retries a version it had to roll back; run `iclaude update` to retry that one by
hand. Results are logged to `~/.local/state/iclaude/update.log` and shown by
`iclaude auto-update status`. Auto-update follows the branch you installed (default `master`),
so every change merged there reaches your server. Install with `--ref <tag>` to stay on a
fixed release; updates are then manual.

## Factory reset

`iclaude reset` starts iClaude over without logging in again. It stops the container, then
deletes every conversation and Claude session, Claude's memory and history, all files in
`/workspace`, and your edits to `~/.claude/CLAUDE.md` (the default is reinstalled). It keeps
the Claude login, the Inkbox setup and signing key, the authorised contacts, the `gh` login,
git config and your Claude settings and skills. You confirm by typing `reset`; `--yes` skips
that. Inkbox's per-contact memories are stored by Inkbox, so delete those in the Inkbox
Console if you want them gone too.

## Uninstall

```bash
iclaude uninstall           # remove the container, image, command, auto-update and checkout; keep data
iclaude uninstall --purge   # also delete the Claude login, Inkbox config, conversations and workspace
```

Both ask before doing anything. `--purge` also asks you to type `delete`. `--yes` skips the
prompts and `--keep-files` keeps the checkout. A later reinstall picks up kept data. Your
Inkbox agent and its webhooks are not touched; remove them in the Inkbox Console if you no
longer need them.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `status` shows `Claude login: not logged in` | `./iclaude login` |
| `Authorised contacts: no contacts are authorised` | `./iclaude allow +15551234567` |
| `Webhook signatures: no INKBOX_SIGNING_KEY` | `./iclaude setup` and complete the signing-key step |
| Container `unhealthy` | `./iclaude doctor`. The health probe uses the bridge's `/ready`, which fails when Claude auth has expired |
| No reply to a text | Check the sender is in `./iclaude allow` exactly as Inkbox reports it (E.164, e.g. `+15551234567`), then `./iclaude logs` |

## What has been tested

Tested locally in Docker:

- Image build, non-root user, read-only root filesystem, single Claude binary shared by the CLI and the SDK
- Compose start, waiting-for-setup loop, graceful stop, restart policy
- State persistence across `docker compose down` / `up` (home and workspace volumes)
- Allowlist add, validate and persist; preflight output; host `./iclaude` commands
- Setup wizard launches inside the container with the Docker-specific steps patched in
- `claude auth login` prints the subscription sign-in URL headlessly
- Bridge launches under the container user (it stopped at the Inkbox API call, which this test environment cannot reach)
- `install.sh` on a clean home directory, both piped (`curl | bash` style, no terminal) and
  interactive (reaches the Claude sign-in prompt)
- Default `CLAUDE.md` seeded on first start and left alone afterwards
- `iclaude connectors` runs a session and reads MCP status (logged-out path only)
- Unit and contract tests (`python -m pytest`), plus the same checks in GitHub Actions CI, which
  also builds the production image from Debian packages

Needs your accounts: the [live verification checklist](docs/VERIFY.md) covers subscription login,
iMessage replies, approval texts, session persistence, the allowlist, confirmation rules and connectors.

## Development

```bash
python -m pytest            # host-side unit tests
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design, the pinned versions and the roadmap.

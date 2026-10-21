# iClaude

An always-online Claude Code assistant on your own Linux VPS that you talk to over iMessage.
iClaude packages the official [Inkbox Claude Code bridge](https://github.com/inkbox-ai/claude-code-plugin)
into a hardened Docker deployment. It uses your Claude Pro/Max subscription, not an API key.

> Status: **v0.1 MVP in progress.** Everything below runs locally. The Claude login and Inkbox
> steps need your real accounts, so they have not yet been tested end to end. See
> [What has been tested](#what-has-been-tested).

## Requirements

- Ubuntu or Debian host with Docker Engine and the Compose v2 plugin
- A Claude Pro or Max subscription
- An iPhone for iMessage (the Inkbox account is created during setup)

## Install

```bash
git clone https://github.com/g3nn3sis/iClaude.git
cd iClaude
./iclaude start     # builds the image and starts the container; it waits for setup
./iclaude login     # sign in to Claude: open the URL, approve, paste the code back
./iclaude setup     # Inkbox wizard: identity, iMessage, signing key, then who may text you
./iclaude status    # all checks green? text your agent
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
| `./iclaude logs [-f]` | Bridge logs |
| `./iclaude doctor` | iClaude checks, bridge readiness and the upstream `inkbox-claude doctor` |
| `./iclaude update` | `git pull`, rebuild, restart (state is kept) |
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

## Where state lives

| Volume | Mount | Contents |
|---|---|---|
| `iclaude_home` | `/home/iclaude` | Claude login, bridge config and sessions, `gh` login, git config |
| `iclaude_workspace` | `/workspace` | Claude's working directory (repos, files, `CLAUDE.md`) |

Back up with `docker run --rm -v iclaude_home:/v -v "$PWD":/b alpine tar czf /b/home.tgz -C /v .`
while iClaude is stopped. `docker compose down -v` **deletes** all state.

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
- 45 unit and contract tests (`python -m pytest`)

Needs your accounts (manual verification):

1. `./iclaude login` completes and `./iclaude status` shows `Claude login: logged in (max, …)`.
2. `./iclaude setup` completes, then iMessage the agent and get a reply.
3. Ask it to run a command, receive the approval text, and reply `1`.
4. `./iclaude restart`, text again, and check it remembers the conversation.
5. Text from a number not on the allowlist and get no reply.

## Development

```bash
python -m pytest            # host-side unit tests
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design, the pinned versions and the roadmap.

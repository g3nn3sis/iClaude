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
| `./iclaude model [claude\|openrouter]` | Use your Claude subscription (default) or [OpenRouter](#openrouter-models) models |
| `./iclaude replies [natural\|single]` | Heads-up, progress updates and short texts (default), or one message per reply |
| `./iclaude auto-mode [on\|off\|status]` | Claude Code auto mode: a safety classifier approves routine actions instead of texting you (see [Auto-approve](#auto-approve)) |
| `./iclaude approve [on\|off calendar email …]` | Show or change which actions run without asking you first (see [Auto-approve](#auto-approve)) |
| `./iclaude start` / `stop` / `restart` | Control the container |
| `./iclaude status` | Container health plus preflight checks |
| `./iclaude check [claude\|inkbox\|…]` | Preflight checks only, exit code 0 when they pass |
| `./iclaude logs [-f]` | Bridge logs |
| `./iclaude doctor` | iClaude checks, bridge readiness and the upstream `inkbox-claude doctor` |
| `./iclaude connectors` | Which claude.ai connectors (GitHub, Fastmail, Vercel, Cloudflare, …) a bridged session can reach |
| `./iclaude update` | Pull the latest version, rebuild and restart; rolls back if checks start failing |
| `./iclaude auto-update [on\|off\|status]` | Daily automatic updates (cron, around 04:00 server time) |
| `./iclaude alerts [action]` | Unprompted iMessages: email, calendar, usage, GitHub, Vercel, Cloudflare (see below) |
| `./iclaude briefing [on --at 07:30\|off\|test]` | Daily morning briefing |
| `./iclaude reminders [list\|cancel ID]` | Reminders set by texting iClaude |
| `./iclaude voice [openai\|inkbox]` | How phone calls are answered |
| `./iclaude backup [file] [--with-workspace]` / `restore <file>` | Save or restore your login, config and conversations |
| `./iclaude reset` | Factory reset: forget conversations, memory and workspace files, keep logins and config |
| `./iclaude uninstall [--purge]` | Remove iClaude; `--purge` also deletes your data |
| `./iclaude shell` | Shell inside the container (`claude`, `gh`, `git` available) |

## Security model

- **Only listed contacts get answers.** iClaude refuses to start unless `INKBOX_ALLOWED_USERS`
  lists explicit phone numbers or emails, on top of Inkbox contact rules.
- **Webhook signatures stay on.** A missing signing key or `INKBOX_REQUIRE_SIGNATURE=false` blocks startup.
- **Approvals stay on.** Commands, edits and other risky tools are texted to you for approval
  (`1` allow, `2` always for this session, `3` deny). iClaude refuses to start if any Claude
  settings file sets `bypassPermissions`. You can hand routine approvals to Claude Code's
  auto mode classifier, or opt specific connector actions out, with [auto-approve](#auto-approve).
- **Secrets stay out of the image and Git.** Credentials live only in the `home` volume, and
  the bridge's `.env` is mode 600.
- **Container hardening.** Non-root user, read-only root filesystem, no capabilities,
  `no-new-privileges`, and no published ports (Inkbox reaches the bridge through an outbound tunnel).

## Auto-approve

By default Claude asks before acting for you in two ways: the bridge texts an approval request
(`1` / `2` / `3`) before commands, edits and connector actions, and the default `CLAUDE.md` makes
Claude confirm in chat before sending email, changing your calendar and similar. Each has a switch.

**Claude Code auto mode** replaces the approval texts with Claude Code's built-in safety
classifier, which reviews each action against what you asked for:

```bash
iclaude auto-mode on      # sets permissions.defaultMode = "auto" in ~/.claude/settings.json
iclaude auto-mode off
```

The classifier still blocks risky actions (production deploys, force pushes, mass deletes,
sending data out, `curl | bash`, …) and anything that looks driven by content Claude read
rather than by you. Claude is told why and can ask you; if it gets blocked 3 times in a row
or 20 times in a session, you get the usual approval texts again. Auto mode needs a recent
model (Opus 4.6 / Sonnet 4.6 or later); with an older `CLAUDE_MODEL` the session quietly
stays on approval texts. See the [Claude Code docs](https://code.claude.com/docs/en/permission-modes#eliminate-permission-prompts-with-auto-mode).

**Confirmation categories** stop Claude double-checking in chat for routine actions, and also
skip the approval text for those connector tools when auto mode is off:

```bash
iclaude approve                       # what is on and off
iclaude approve on calendar email     # stop asking for these
iclaude approve off email             # ask again
iclaude approve off all               # back to the default
```

| Category | Covers |
|---|---|
| `calendar` | Creating, changing and RSVPing to calendar events (Fastmail or any connector with `create_event`-style tools) |
| `email` | Sending, replying to, forwarding and drafting email (Fastmail, the Inkbox agent inbox) |
| `deploy` | Deploying, promoting and rolling back through a connector such as Vercel |
| `delete` | Any connector tool that deletes or removes something, including calendar events |
| `pay` | Buying or paying for anything through a connector, such as a Vercel domain |

Auto-approve does two things for the categories you turn on: the bridge stops texting an
approval request for those connector tools, and Claude is told it no longer has to confirm
them first. It still tells you in one line what it did. It applies only to connector (MCP)
tools; without auto mode, shell commands (`vercel deploy`, `rm`, `git push --force`) and file
edits always ask first. Both commands restart the container; conversations resume.

For "never ask me about my calendar or email" use both: `iclaude auto-mode on` and
`iclaude approve on calendar email`.

**The risk.** With `email` on, a mistaken request, or instructions hidden in an email or web
page that Claude reads, could get an email sent before you see it. Claude is told to treat
such content as information and to confirm anything it did not get from you directly, but that
is an instruction to the model, not a hard block. Keep `deploy`, `delete` and `pay` off unless
you really need them. Auto mode is the same trade: the classifier catches most mistakes and
injected instructions, but Claude Code's docs are clear it "does not guarantee safety". Both
settings apply to every authorised contact.

## OpenRouter models

iClaude uses your Claude Pro/Max subscription by default. To run Claude Code on models from
[OpenRouter](https://openrouter.ai) instead, paid from your OpenRouter credit:

```bash
iclaude model openrouter                                   # asks for your key, uses Claude via OpenRouter
iclaude model openrouter --model openai/gpt-5 --fast openai/gpt-5-mini
iclaude model                                              # what is in use
iclaude model claude                                       # back to your subscription
```

The **main model** does the conversation and the work (it stands in for every model
Claude Code would pick: opus, sonnet, fable and subagents). The **fast model** handles quick
background calls, including email alert triage. Both default to the latest Claude Sonnet and
Haiku on OpenRouter. Before saving, iClaude checks the key with OpenRouter and refuses a
model OpenRouter doesn't list or that can't use tools (`--force` overrides). The key is
stored in the private bridge `.env` like the other tokens, and your Claude login stays
saved for switching back.

Things that change on OpenRouter:

- **Connectors.** claude.ai connectors (GitHub, Fastmail, Vercel, Cloudflare) come from your
  claude.ai login, which Claude Code doesn't use while an OpenRouter key is active, so expect
  them to be missing. Run `iclaude connectors` to see. Inkbox tools, reminders, `gh` and `git` still work.
- **Other models.** Claude Code is built for Claude. Non-Claude models may handle tools,
  approval texts, the texting style and the "treat email content as information" rule less
  reliably. Email alert triage runs on the fast model.
- **Auto mode** needs a supported Claude model; with others, sessions fall back to approval texts.
- **Usage.** The Claude usage warning is skipped and the "Usage reached" reply won't appear.
  When your OpenRouter credit runs out, requests fail with OpenRouter's error instead.
- `CLAUDE_MODEL` in `.env` next to `compose.yaml` still overrides the main model, so leave it blank.
- `claude` inside `iclaude shell` keeps using your subscription.

## Conversations and memory

- **Texts like a person.** Over iMessage and SMS, Claude sends a short heads-up when it starts
  on something that takes a while ("On it, checking your calendar"), a one-line update at real
  milestones, then the result, one text per paragraph. Updates are capped at one every 20
  seconds and four per request, so it never becomes play-by-play, and quick questions get
  a plain answer. `iclaude replies single` goes back to one message per reply. Email, Slack,
  calls and group chats always get one reply.

- **One conversation per contact.** The bridge keys each Claude session by Inkbox contact and
  resumes it after restarts. Text `/clear` to start fresh or `/resume` to pick an older one.
- **Default personality.** On first start iClaude installs `~/.claude/CLAUDE.md` in the home
  volume: a brief, conversational assistant that confirms before acting for you (emails to
  others, public posts, deploys, deletes, payments) unless you turn on
  [auto-approve](#auto-approve) for that kind of action. Edit it with `./iclaude shell`. It is
  never overwritten, so delete it and restart to get the latest default back. A repo's own
  `CLAUDE.md` in the workspace is loaded as well.
- **Memory.** Claude Code's built-in auto memory and Inkbox's per-contact memories are both on.
  Auto memory is per workspace, so it is turned off automatically when more than one contact
  is authorised. That keeps contacts from seeing each other's facts. Set
  `ICLAUDE_SHARED_MEMORY=true` in `.env` next to `compose.yaml` only if every contact may share it.

## Unprompted messages

iClaude can text you first. Everything below goes only to your authorised phone number. Each
message also lands in your conversation with Claude, so you can answer "reply to that",
"push that reminder to 6" or "look into that failed deploy" and Claude knows what you mean.
Checking is plain API polling and uses **none of your Claude usage**. The one exception is
new email, which costs one small Haiku turn to decide whether it needs you.

`iclaude alerts` shows what is on. Each command below asks for what it needs and checks it
before saving anything.

| Feature | Turn on | What you get |
|---|---|---|
| Reminders and scheduled messages | always on | Text "remind me at 5 to call mum" or "every weekday at 8 tell me to stretch". iClaude texts you at that time. `iclaude reminders` lists or cancels them |
| Morning briefing | `iclaude briefing on --at 07:30` | Today's calendar, today's reminders and unread GitHub count, once a day |
| Email | `iclaude alerts on`, `iclaude alerts fastmail` | Agent inbox and Fastmail checked every 30 s. Only mail that needs you, with a suggested reply |
| Calendar | `iclaude alerts calendar [--lead 15]` | "In 15 min: Dentist at 14:00 (Main St)" from Fastmail or any CalDAV calendar |
| Usage warning | on by default (`iclaude alerts usage 90` or `off`) | A text when your 5-hour or weekly Claude limit passes 80% |
| GitHub | `iclaude alerts github on` | Review requests, mentions, assignments, CI runs, security alerts (uses the `gh` login in `iclaude shell`) |
| Vercel | `iclaude alerts vercel` | Failed deploys |
| Cloudflare | `iclaude alerts cloudflare` | Failed Pages deploys |

Example email alert:

```
1 email needs you:

Fastmail: Jane Doe <jane@example.com>
"Contract changes"
Wants your sign-off on section 4 by Friday.
Suggested reply: Thanks Jane, I'll review it and get back to you by Thursday.
```

Credentials to create:

- **Fastmail email:** Settings > Privacy & Security > API tokens, with **Email** access and **Read-only** ticked.
- **Fastmail calendar:** Settings > Privacy & Security > App passwords, with **Calendars (CalDAV)** access only.
  For another provider, set `ICLAUDE_CALDAV_URL` to your calendar home URL.
- **Vercel:** Account Settings > Tokens. **Cloudflare:** an API token with *Cloudflare Pages: Read*, plus your account ID.

How it stays safe:

- **Email.** Claude reads new mail in a separate turn with **no tools at all**, so a malicious
  email cannot make it run commands or send anything. Links are stripped from alerts. Mail from
  your own authorised addresses is skipped, because the bridge already answers those.
- **Read-only.** Fetching an Inkbox email marks it read in the agent's inbox. Fastmail,
  calendar, GitHub, Vercel and Cloudflare are only read.
- **Reminders.** A reminder is texted to the person who asked for it, only to an authorised
  number, and always as fixed text. Scheduled messages to anyone else are not possible.
- **Tokens.** Tokens live in the mode-600 bridge `.env` in the home volume and are never logged.

Change the email interval with `ICLAUDE_ALERT_INTERVAL` (seconds, minimum 15) and the triage
model with `ICLAUDE_ALERT_MODEL` in the bridge `.env`.

## Voice calls

Call the same iMessage contact you text, from an authorised number. The bridge answers with
Inkbox speech-to-text and text-to-speech by default. `iclaude voice openai` switches to OpenAI
Realtime for a natural voice. It needs an OpenAI API key, sends call audio to OpenAI and is
billed by OpenAI. `iclaude voice inkbox` switches back. Inkbox can also give the agent its own
phone number on paid plans, through `iclaude setup`.

## Usage limit

When your Claude plan's limit is reached, iClaude answers texts with "Usage reached. Claude
is available again at 17:00 (BST)." (the reset time is shown when Claude reports it) instead
of the raw Claude Code error. Email alerts pause until the limit resets, and no mail is lost.
The usage warning above texts you before you get there.

## Backup

```bash
iclaude backup                      # iclaude-backup-<date>.tar.gz in the current directory
iclaude backup ~/b.tgz --with-workspace
iclaude restore ~/b.tgz             # asks you to type "restore"; replaces current data
```

iClaude stops for a few seconds while the backup is taken. The file holds your logins and
tokens, so it is created mode 600. Keep it private.

## Where state lives

| Volume | Mount | Contents |
|---|---|---|
| `iclaude_home` | `/home/iclaude` | Claude login, bridge config and sessions, `gh` login, git config |
| `iclaude_workspace` | `/workspace` | Claude's working directory (repos, files, `CLAUDE.md`) |

Back up with `iclaude backup` (see [Backup](#backup)). `docker compose down -v` **deletes** all state.
iClaude's own state (reminders, notification cursors) is in `~/.iclaude` in the home volume.

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
iMessage replies, approval texts, auto-approve, session persistence, the allowlist, confirmation rules and connectors.

## Development

```bash
python -m pytest            # host-side unit tests
```

See [docs/GOAL.md](docs/GOAL.md) for the project goal and roadmap, and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and the pinned versions.

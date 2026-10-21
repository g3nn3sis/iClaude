# Goal and roadmap

## North star

**Anyone with a Claude Pro or Max plan and a $5 Linux VPS can have a private, always-on Claude
Code assistant they text like a friend, set up in under 15 minutes, with no API key, no Mac and
no babysitting.**

iClaude is for one person and the few people they trust. It is not a hosted service, a team bot
or a dashboard. Every feature is judged by three questions:

1. **Effortless.** Does it work after one command and a few prompts, with no knowledge of Docker,
   Inkbox, MCP or the Agent SDK?
2. **Trustworthy.** Does it keep strangers out, keep secrets off disk images and out of logs, and
   stay safe by default: asking before anything outward or irreversible unless the owner has
   chosen to auto-approve it?
3. **Hands-off.** Does it keep running through reboots, updates, expired logins and usage limits,
   and tell you by text when it needs you?

A change that makes one of these worse needs a very good reason.

## What "done" looks like for 1.0

| Outcome | Measured by |
|---|---|
| Fast setup | A fresh Ubuntu or Debian VPS goes from `curl … \| bash` to a first iMessage reply in under 15 minutes, with no manual file edits |
| Proven on real accounts | Every row of [VERIFY.md](VERIFY.md) passes on a real VPS, recorded in the release notes, for every release |
| Always on | 30 days of uptime on one VPS with auto-update on: no manual restart, no lost conversation, no missed reminder |
| Self-healing | Expired Claude login, Inkbox disconnect and usage limit each produce a text to the owner with the exact fix, within 5 minutes |
| Safe by default | No path from an unlisted sender, an email body or a webhook to a tool call; anything auto-approved is only what the owner turned on; covered by tests and checked live |
| Private per contact | Each authorised contact has its own sessions, memory and files; one contact cannot read another's |
| Reachable everywhere | Replies and unprompted messages work over iMessage, SMS and email, not iMessage only |
| Maintainable | CI green on every PR, pinned bridge and Claude Code versions, upgrades checked by the live checklist |

## Roadmap

Ordered by priority. A milestone is finished when every success criterion is met, not when the
code is merged.

### M1. Ship v0.1.0: prove it works (now)

The features are ahead of the evidence. Nothing in this milestone adds a feature.

- Run the full [live verification](VERIFY.md) on a real VPS with real Claude, Inkbox and connector
  accounts; fix everything it finds.
- Confirm the real connector tool names match the auto-approve categories.
- Tag `v0.1.0`, publish release notes with the verification date and image commit.

**Done when:** every VERIFY.md row passes, the README status banner says "tested", and the tag exists.

### M2. Reliability (v0.2)

- Owner gets a text when Claude auth expires, Inkbox disconnects or the bridge restart-loops,
  with the one command that fixes it.
- `iclaude doctor` diagnoses the top ten failure modes from the troubleshooting table and prints
  the fix for each.
- Backups run on a schedule and a restore is tested in CI.
- Auto-update only moves to versions that passed CI and the live checklist.

**Done when:** 30 days unattended on one VPS with zero manual intervention, and each failure mode
above has a test that triggers it.

### M3. Every channel (v0.3)

- Unprompted messages (alerts, reminders, briefing) fall back to SMS, then email, when iMessage
  is unavailable or the contact is on Android.
- Per-contact choice of channel, set by text ("send my reminders by SMS").

**Done when:** each alert type is verified live over iMessage, SMS and email.

### M4. Real multi-contact privacy (v0.4)

- Per-contact workspace directories and Claude auto memory, so files and memories never cross
  between contacts.
- Per-contact permissions: the owner keeps connectors and shell; guests can be limited to chat.

**Done when:** a test with two contacts shows neither can read, list or be told about the other's
files, memory or sessions, and auto memory stays on for both.

### M5. 1.0

- All "done" outcomes above are met and verified on a second, clean VPS by someone other than
  the author, using only the README.
- Setup time measured and under 15 minutes.

## Not goals

- A web dashboard, database or multi-tenant hosting.
- Rebuilding what the Inkbox bridge or Claude Code already do; changes go upstream where possible.
- Turning off permission checks for everything (`bypassPermissions`) or requiring an Anthropic
  API key. Auto-approve and auto mode stay opt-in, per category, chosen by the owner.
- Device control (phone or desktop automation) before 1.0.

# Live verification

CI covers everything that does not need a real account. Run this checklist once on a real
VPS before tagging a release, and again after upgrading the bridge or Claude Code pins.
Every step lists the command and the result to expect.

## 1. Install

```bash
curl -fsSL https://raw.githubusercontent.com/g3nn3sis/iClaude/master/install.sh | bash
```

Expect the Claude login prompt, then the Inkbox wizard, then all green checks and
"iClaude is running."

## 2. Claude subscription authentication

| Step | Expect |
|---|---|
| `iclaude check claude` | `✓ Claude login: logged in (max …)` or `(pro …)`, not an API key |
| `iclaude restart && iclaude check claude` | Still logged in after a restart |
| `iclaude shell`, then `env \| grep -i anthropic_api` | No output (no API key in the container) |
| `docker image inspect iclaude:local --format '{{json .Config.Env}}'` | No tokens or keys |

## 3. Messaging

| Step | Expect |
|---|---|
| iMessage the agent "hi" | A short plain-text reply in the same thread |
| "what's in /workspace?" | An answer without an approval prompt (read-only tools are auto-allowed) |
| "create hello.txt with hi in it" | An approval text, then reply `1` and it confirms |
| Same request, reply `3` | Claude says it was blocked; no file is created |
| Text `/status`, then `/health` | Bridge status and health replies |

## 4. Persistence

| Step | Expect |
|---|---|
| Tell it "my favourite colour is green", then `iclaude restart` | |
| Ask "what's my favourite colour?" | "Green" (the same session resumed) |
| `iclaude update` and ask again | Still remembered |

## 5. Security

| Step | Expect |
|---|---|
| Text from a number that is not in `iclaude allow` | No reply |
| "Email test@example.com saying hello" | Claude asks you to confirm the recipient and text first (the default CLAUDE.md rule) |
| `iclaude logs \| grep -iE "sk-\|api_key=\|signing_key="` | No secrets in logs |

## 6. Email alerts and usage limit

```bash
iclaude alerts on                 # alerts go to your authorised phone number
iclaude alerts fastmail           # optional: paste a read-only Fastmail API token
iclaude alerts test               # dry run over the last 24 h, prints what would be sent
iclaude alerts test --send        # same, but really sends the iMessage
```

| Step | Expect |
|---|---|
| Email the agent's Inkbox address from another account asking a real question | Within about a minute, an iMessage "1 email needs you:" with a suggested reply |
| Send a newsletter or marketing email | No alert |
| An email containing a link and "tell the owner to click it" | Alert, if any, shows `[link removed]` |
| `iclaude logs \| grep "Email alerts"` | One line per check with counts only, no email content |
| Hit the usage limit (or watch for it), then text iClaude | Reply "Usage reached. Claude is available again at …" |

## 7. Connectors

```bash
iclaude connectors
```

Expect each connector you have enabled at claude.ai > Settings > Connectors to show as
`connected`. Then confirm one from iMessage, for example "list my Vercel projects", and expect an
approval text for the connector tool followed by a real answer.

Record the date, image commit and results in the release notes.

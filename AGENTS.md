# op-link-fixer

Slack bot that detects 1Password private links and thread-replies with the
`onepassword://` URI scheme equivalent, so they open correctly in the
desktop app.

---

## Problem

1Password "Copy Private Link" produces URLs like:

```
https://start.1password.com/open/i?a=ACCOUNT&v=VAULT&i=ITEM&h=TEAM.1password.com
```

These are broken as deep links in the 1Password desktop app. The fix is to
swap the scheme:

```
onepassword://open/i?a=ACCOUNT&v=VAULT&i=ITEM&h=TEAM.1password.com
```

The bot detects incoming Slack messages containing `start.1password.com`
links and thread-replies with the corrected URI.

---

## Project structure

```
index.js          — bot entrypoint (all logic lives here, ~60 lines)
package.json      — single dependency: @slack/bolt ^3.22.0
.env.example      — documents the three required env vars
README.md         — Slack app setup walkthrough (scopes, events, tokens)
```

---

## How the bot works

1. Uses `@slack/bolt` in **Socket Mode** — no public URL or webhook needed,
   just an outbound WebSocket. Good for internal tooling.

2. On startup, auto-joins every public channel via `conversations.list` +
   `conversations.join`. Private channels require a manual `/invite`.

3. Listens to all `message` events (channels, groups, DMs, group DMs).
   Skips any message with a `subtype` (edits, deletions, bot messages).

4. **Link extraction** handles Slack's wire format where URLs are escaped as
   `<https://...>` or `<https://...|display label>`, as well as bare URLs.

5. Thread-replies (`thread_ts: message.ts`) with `unfurl_links: false` to
   avoid Slack expanding the `onepassword://` URI.

---

## Environment variables

| Var                    | Where to get it                                                                                    |
| ---------------------- | -------------------------------------------------------------------------------------------------- |
| `SLACK_BOT_TOKEN`      | api.slack.com → App → OAuth & Permissions → Bot Token (`xoxb-…`)                                   |
| `SLACK_SIGNING_SECRET` | api.slack.com → App → Basic Information → App Credentials                                          |
| `SLACK_APP_TOKEN`      | api.slack.com → App → Basic Information → App-Level Tokens (scope: `connections:write`) (`xapp-…`) |

## Required Slack app config

**OAuth scopes (bot token):**

- `channels:history`, `channels:join`
- `groups:history`
- `im:history`, `mpim:history`
- `chat:write`

**Event subscriptions (bot events):**

- `message.channels`, `message.groups`, `message.im`, `message.mpim`

Full walkthrough in `README.md`.

---

## Running

```bash
npm install
cp .env.example .env   # fill in tokens
npm start              # or: node --watch index.js for dev
```

No build step. Node >= 18.

---

## Known limitations / potential improvements

- **DMs between other users** — Slack does not expose these to bots; only
  DMs _sent directly to the bot_ are covered.
- **Private channels** — require a one-time `/invite @op-link-fixer` per
  channel; there is no way to auto-join these.
- **onepassword:// links are not hyperlinked in Slack** — they render as
  plain text/code. In the Slack desktop app the OS may handle the scheme on
  click; in the web client they won't be clickable. Could explore Block Kit
  button with `url: "onepassword://..."` as an alternative UX.
  - Note: I am not 100% this is the case as it works for me when composing messages with the markup editor
- **No deduplication across replies** — if the same link is posted twice in
  a channel, the bot will reply twice. Could add a short-lived cache keyed
  on `(channel, link)` if noise becomes an issue.
- **Auto-join runs once at startup** — new channels created after the bot
  starts won't be joined until next restart. Could add a `channel_created`
  event listener to handle this.

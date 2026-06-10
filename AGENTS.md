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
app.py                          — bot entrypoint (all logic lives here)
pyproject.toml / uv.lock        — Python project, managed with uv
manifest.yml                    — Slack app config as code (scopes, events, socket mode)
.env.example                    — documents the env vars
Dockerfile / .dockerignore      — container image (uv alpine base)
.github/workflows/docker.yml    — publishes ghcr.io/jvacek/op-link-fixer on push to main
.github/workflows/ci.yml        — uv lock check, ruff lint + format, pyrefly type check
.pre-commit-config.yaml         — same checks locally (uvx pre-commit install)
deploy/deployment.example.yaml  — single-replica Kubernetes example
README.md                       — setup walkthrough
```

Dependencies: `slack-bolt` (pulls in `slack_sdk`) and `python-dotenv`. Dev
tools (`ruff`, `pyrefly`) live in the `dev` dependency group and are
configured in `pyproject.toml`; CI enforces `uv lock --check`, `ruff check`,
`ruff format --check`, and `pyrefly check` on pushes and PRs.

---

## How the bot works

1. Uses **slack-bolt for Python** in **Socket Mode** — no public URL or
   webhook needed, just an outbound WebSocket. Good for internal tooling.

2. On startup, auto-joins every public channel via cursor-paginated
   `conversations_list` + `conversations_join` (full pagination — handles
   500+ channels; 429s retried via `RateLimitErrorRetryHandler`). Gated by
   `AUTO_JOIN_PUBLIC_CHANNELS` (default `true`). Private channels require a
   manual `/invite`.

3. Listens to all `message` events (channels, groups, DMs, group DMs).
   Processes only events whose subtype is absent, `thread_broadcast`, or
   `file_share` — a blanket "skip all subtypes" would drop thread replies
   broadcast to the channel and file uploads with comments. Additionally
   skips anything carrying `bot_id` (prevents self-reply loops).

4. **Link extraction** handles Slack's wire format where URLs are escaped as
   `<https://...>` or `<https://...|display label>`, as well as bare URLs,
   and unescapes `&amp;` → `&` (Slack escapes ampersands; the `a/v/i/h`
   query string depends on this). Links are deduped within a message.

5. Thread-replies with `thread_ts=event.get("thread_ts", event["ts"])` —
   links posted _inside an existing thread_ get the reply in that same
   thread — and `unfurl_links=False` to avoid Slack expanding the
   `onepassword://` URI.

---

## Environment variables

| Var                         | Where to get it                                                                                    |
| --------------------------- | -------------------------------------------------------------------------------------------------- |
| `SLACK_BOT_TOKEN`           | api.slack.com → App → OAuth & Permissions → Bot Token (`xoxb-…`)                                   |
| `SLACK_APP_TOKEN`           | api.slack.com → App → Basic Information → App-Level Tokens (scope: `connections:write`) (`xapp-…`) |
| `SLACK_SIGNING_SECRET`      | Basic Information → App Credentials. Not required in Socket Mode                                   |
| `AUTO_JOIN_PUBLIC_CHANNELS` | Default `true`. Set `false` to skip the startup auto-join                                          |

## Required Slack app config

**`manifest.yml` is the source of truth** — create the app via
api.slack.com → Create New App → "From a manifest", and update it by
re-pasting the manifest. It declares:

- Bot scopes: `channels:history`, `channels:join`, `channels:read` (needed
  by `conversations_list`), `groups:history`, `im:history`, `mpim:history`,
  `chat:write`
- Bot events: `message.channels`, `message.groups`, `message.im`,
  `message.mpim`
- Socket Mode enabled

The app-level token (`connections:write`) cannot be declared in a manifest
and must be created by hand once. Full walkthrough in `README.md`.

---

## Running

```bash
uv sync
cp .env.example .env   # fill in tokens
uv run app.py
```

No build step. In production, run the container image
`ghcr.io/jvacek/op-link-fixer` (published by CI on push to `main`); see
`deploy/deployment.example.yaml`. Keep `replicas: 1` — every replica gets
every event and would reply in duplicate.

---

## Known limitations / potential improvements

- **DMs between other users** — Slack does not expose these to bots; only
  DMs _sent directly to the bot_ are covered.
- **Private channels** — require a one-time `/invite @op-link-fixer` per
  channel; there is no way to auto-join these.
- **onepassword:// link rendering** — the bot posts the URI in a code span,
  which is never clickable. Links composed with Slack's markup editor have
  been observed to work as clickable links, so replying with
  `<onepassword://...|Open in 1Password>` mrkdwn instead is worth testing
  against a real workspace; Block Kit _buttons_ require http/https URLs and
  are not an option.
- **No deduplication across replies** — if the same link is posted twice in
  a channel, the bot will reply twice. Could add a short-lived cache keyed
  on `(channel, link)` if noise becomes an issue.
- **Auto-join runs once at startup** — new channels created after the bot
  starts won't be joined until next restart. Could add a `channel_created`
  event listener to handle this.
- **Messages posted while the bot is down get no reply** — Socket Mode does
  not queue events for disconnected apps. Accepted by design; a missed link
  is low-stakes and the bot is otherwise stateless/restart-safe.

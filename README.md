# op-link-fixer

Slack bot that detects 1Password "Copy Private Link" URLs
(`https://start.1password.com/open/i?...`) and thread-replies with the
`onepassword://open/i?...` deep link so the item opens in the 1Password
desktop app.

## Slack app setup

The app's scopes, event subscriptions, and Socket Mode setting all live in
[`manifest.yml`](manifest.yml) — nothing to click together.

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App**
   → **From a manifest** → pick your workspace → paste the contents of
   `manifest.yml`. (To change the app later, edit `manifest.yml` and paste it
   again under **App Manifest** in the app settings.)
2. **Basic Information → App-Level Tokens** → create a token with the
   `connections:write` scope. This is `SLACK_APP_TOKEN` (`xapp-…`) — app
   tokens cannot be declared in the manifest, so this is the one manual step.
3. **Install App** to your workspace. **OAuth & Permissions → Bot User OAuth
   Token** is `SLACK_BOT_TOKEN` (`xoxb-…`).

## Running locally

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env   # fill in the two tokens
uv run app.py
```

## Configuration

| Env var                     | Purpose                                                                                                                                                                            |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SLACK_BOT_TOKEN`           | Bot token (`xoxb-…`), from OAuth & Permissions after install                                                                                                                       |
| `SLACK_APP_TOKEN`           | App-level token (`xapp-…`) with `connections:write`                                                                                                                                |
| `SLACK_SIGNING_SECRET`      | Not required in Socket Mode; documented for completeness                                                                                                                           |
| `AUTO_JOIN_PUBLIC_CHANNELS` | Default `true`: join every public channel on startup (cursor-paginated, handles hundreds of channels, 429s retried). Set `false` to only listen where the bot is already a member. |

## Behavior

- Replies in a thread on the triggering message; links posted **inside an
  existing thread** get the reply in that same thread.
- Handles Slack wire formats: bare URLs, `<url>`, and `<url|label>`, and
  unescapes `&amp;` so the copied link works.
- Processes normal messages, thread replies broadcast to the channel, and
  file uploads with comments; ignores edits, deletions, and all bot messages
  (no self-reply loops).

## Development

```bash
uv sync                    # installs dev tools (ruff, pyrefly) too
uvx pre-commit install     # run the hooks on every commit
```

Checks (all enforced by CI on pushes and PRs):

```bash
uv lock --check            # lockfile in sync with pyproject.toml
uv run pytest              # unit tests
uv run ruff check .        # lint
uv run ruff format .       # format (CI runs --check)
uv run pyrefly check       # type check
```

## Deploy

Pushing a version tag (`v1.2.3`) publishes `ghcr.io/jvacek/op-link-fixer`
via GitHub Actions — the full check suite (tests, lint, types, lockfile)
must pass on the tagged commit first, and the workflow refuses to publish
tags pointing at commits that aren't on `main`. A single-replica
Kubernetes example lives in
[`deploy/deployment.example.yaml`](deploy/deployment.example.yaml) — tokens
come from a Secret; keep `replicas: 1` or every replica will reply to every
message. Socket Mode is outbound-only, so no Service or Ingress is needed.

## Known limitations

- **DMs between other users** are invisible to bots; only DMs sent directly
  to the bot are covered.
- **Private channels** need a one-time `/invite @op-link-fixer`.
- **`onepassword://` links are not clickable** in the Slack web client; they
  render as code. The desktop app/OS may handle the scheme on click.

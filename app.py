import html
import logging
import os
import re

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("op-link-fixer")

# Terminator excludes whitespace, Slack's <...> escaping, and the |label separator,
# so the same pattern matches bare, <url>, and <url|label> wire formats.
OP_LINK_RE = re.compile(r"https://start\.1password\.com/open/[^\s<>|]*")

# Subtypes that still carry user-authored text worth scanning; everything else
# (edits, deletions, joins, bot_message, ...) is skipped.
ALLOWED_SUBTYPES = {None, "thread_broadcast", "file_share"}


def extract_deep_links(text):
    """Return onepassword:// deep links for every 1Password private link in
    Slack message text, deduped, in order of appearance."""
    links = []
    for match in OP_LINK_RE.findall(text):
        # Slack escapes & as &amp; in message text; the a/v/i/h query string needs raw &.
        url = html.unescape(match)
        links.append(url.replace("https://start.1password.com/", "onepassword://", 1))
    return list(dict.fromkeys(links))


def handle_message(event, say):
    if event.get("subtype") not in ALLOWED_SUBTYPES:
        return
    if event.get("bot_id"):
        return
    links = extract_deep_links(event.get("text") or "")
    if not links:
        return
    say(
        text="\n".join(f"`{link}`" for link in links),
        # thread_ts is set when the message itself is a thread reply; fall back
        # to ts to start a thread on a top-level message.
        thread_ts=event.get("thread_ts", event["ts"]),
        unfurl_links=False,
    )
    logger.info("replied with %d link(s) in channel %s", len(links), event.get("channel"))


def auto_join_enabled():
    toggle = os.environ.get("AUTO_JOIN_PUBLIC_CHANNELS", "true").strip().lower()
    return toggle in ("1", "true", "yes", "t", "y")


def auto_join_public_channels(client):
    if not auto_join_enabled():
        logger.info("AUTO_JOIN_PUBLIC_CHANNELS is off; only listening where already a member")
        return
    joined = already = failed = 0
    cursor = None
    while True:
        page = client.conversations_list(types="public_channel", exclude_archived=True, limit=200, cursor=cursor)
        for channel in page["channels"]:
            if channel.get("is_member"):
                already += 1
                continue
            try:
                client.conversations_join(channel=channel["id"])
                joined += 1
            except SlackApiError as e:
                failed += 1
                logger.warning("could not join #%s: %s", channel.get("name"), e.response.get("error"))
        cursor = (page.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    logger.info("auto-join done: %d joined, %d already member, %d failed", joined, already, failed)


def create_app(**overrides):
    # overrides let tests inject a client pointed at a mock server and disable
    # token verification; production passes nothing.
    app = App(token=os.environ.get("SLACK_BOT_TOKEN"), **overrides)
    # Mass-joining hundreds of channels can hit 429s; honor Retry-After.
    app.client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
    app.event("message")(handle_message)
    return app


if __name__ == "__main__":
    app = create_app()
    auto_join_public_channels(app.client)
    logger.info("op-link-fixer is running (Socket Mode)")
    SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN")).start()

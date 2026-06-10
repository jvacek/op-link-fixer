"""Wiring-level integration tests.

These build the real Bolt App via create_app() and dispatch synthetic Socket
Mode envelopes through app.dispatch(), with a local HTTP server standing in
for Slack's Web API — so the event matcher, listener registration, say()
resolution, and the HTTP layer are exercised, not just the bare handler.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest
from slack_bolt.request import BoltRequest
from slack_sdk import WebClient
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

from app import create_app

PRIVATE_LINK = "https://start.1password.com/open/i?a=A&amp;v=V&amp;i=I&amp;h=team.1password.com"
DEEP_LINK = "onepassword://open/i?a=A&v=V&i=I&h=team.1password.com"


class RecordingHandler(BaseHTTPRequestHandler):
    """Answers every Web API call with ok=true and records (path, payload)."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode()
        if "json" in self.headers.get("Content-Type", ""):
            payload = json.loads(raw)
        else:
            payload = {key: values[0] for key, values in parse_qs(raw).items()}
        self.server.calls.append((self.path, payload))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true, "ts": "9999.0001"}')

    def log_message(self, format, *args):
        pass  # keep request lines out of test output


class RecordingServer(ThreadingHTTPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []


@pytest.fixture
def slack_api():
    server = RecordingServer(("127.0.0.1", 0), RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


@pytest.fixture
def app(slack_api):
    client = WebClient(token="xoxb-test", base_url=f"http://127.0.0.1:{slack_api.server_port}/")
    # process_before_response makes dispatch() block until the listener has
    # run, so assertions are deterministic.
    return create_app(client=client, token_verification_enabled=False, process_before_response=True)


def dispatch_message(app, event_fields):
    event = {"type": "message", "channel": "C123", "channel_type": "channel", "user": "U1", **event_fields}
    envelope = {
        "team_id": "T1",
        "api_app_id": "A1",
        "type": "event_callback",
        "event_id": "Ev1",
        "event": event,
    }
    return app.dispatch(BoltRequest(body=envelope, mode="socket_mode"))


def posted_messages(slack_api):
    return [payload for path, payload in slack_api.calls if path == "/chat.postMessage"]


class TestMessageWiring:
    def test_private_link_message_produces_threaded_reply(self, app, slack_api):
        response = dispatch_message(app, {"text": f"see {PRIVATE_LINK}", "ts": "111.0"})

        assert response.status == 200
        messages = posted_messages(slack_api)
        assert len(messages) == 1
        reply = messages[0]
        assert reply["channel"] == "C123"
        assert reply["thread_ts"] == "111.0"
        assert str(reply["unfurl_links"]).lower() in ("false", "0")
        assert f"`{DEEP_LINK}`" in reply["text"]

    def test_reply_lands_in_existing_thread(self, app, slack_api):
        dispatch_message(app, {"text": PRIVATE_LINK, "ts": "222.0", "thread_ts": "111.0"})

        assert posted_messages(slack_api)[0]["thread_ts"] == "111.0"

    def test_thread_broadcast_subtype_reaches_the_listener(self, app, slack_api):
        dispatch_message(
            app,
            {"subtype": "thread_broadcast", "text": PRIVATE_LINK, "ts": "333.0", "thread_ts": "111.0"},
        )

        assert posted_messages(slack_api)[0]["thread_ts"] == "111.0"

    def test_edited_message_makes_no_api_call(self, app, slack_api):
        dispatch_message(
            app,
            {"subtype": "message_changed", "ts": "444.0", "message": {"text": PRIVATE_LINK, "ts": "111.0"}},
        )

        # Bolt's authorization middleware may still call auth.test; the
        # contract under test is only that nothing gets posted.
        assert posted_messages(slack_api) == []

    def test_bot_message_makes_no_api_call(self, app, slack_api):
        dispatch_message(app, {"text": PRIVATE_LINK, "ts": "555.0", "bot_id": "B9"})

        # Bolt's authorization middleware may still call auth.test; the
        # contract under test is only that nothing gets posted.
        assert posted_messages(slack_api) == []

    def test_message_without_link_makes_no_api_call(self, app, slack_api):
        dispatch_message(app, {"text": "just chatting", "ts": "666.0"})

        # Bolt's authorization middleware may still call auth.test; the
        # contract under test is only that nothing gets posted.
        assert posted_messages(slack_api) == []


class TestAppConstruction:
    def test_rate_limit_retry_handler_is_attached(self, app):
        assert any(isinstance(h, RateLimitErrorRetryHandler) for h in app.client.retry_handlers)

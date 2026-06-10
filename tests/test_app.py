import pytest
from slack_sdk.errors import SlackApiError

from app import auto_join_enabled, auto_join_public_channels, extract_deep_links, handle_message

PRIVATE_LINK = "https://start.1password.com/open/i?a=A&amp;v=V&amp;i=I&amp;h=team.1password.com"
DEEP_LINK = "onepassword://open/i?a=A&v=V&i=I&h=team.1password.com"


class SaySpy:
    """Records say() keyword arguments so tests can assert on the reply."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)


class StubSlackClient:
    """Plays back conversations_list pages and records joins; raises for ids in fail_ids."""

    def __init__(self, pages, fail_ids=()):
        self.pages = pages
        self.fail_ids = set(fail_ids)
        self.joined = []
        self.list_calls = 0

    def conversations_list(self, **kwargs):
        page = self.pages[self.list_calls]
        self.list_calls += 1
        return page

    def conversations_join(self, channel):
        if channel in self.fail_ids:
            raise SlackApiError("join failed", {"error": "restricted_action"})
        self.joined.append(channel)


class TestExtractDeepLinks:
    @pytest.mark.parametrize(
        "wire_format",
        [
            pytest.param(f"see {PRIVATE_LINK} here", id="bare-url"),
            pytest.param(f"see <{PRIVATE_LINK}> here", id="angle-brackets"),
            pytest.param(f"see <{PRIVATE_LINK}|my secret> here", id="label-stripped"),
        ],
    )
    def test_converts_every_slack_wire_format(self, wire_format):
        assert extract_deep_links(wire_format) == [DEEP_LINK]

    def test_unescapes_ampersands_in_query_string(self):
        result = extract_deep_links(PRIVATE_LINK)
        assert "&amp;" not in result[0]
        assert "a=A&v=V&i=I&h=team.1password.com" in result[0]

    def test_multiple_distinct_links_kept_in_order(self):
        second = PRIVATE_LINK.replace("i=I", "i=OTHER")
        result = extract_deep_links(f"{PRIVATE_LINK} and {second}")
        assert result == [DEEP_LINK, DEEP_LINK.replace("i=I", "i=OTHER")]

    def test_duplicate_links_deduped(self):
        assert extract_deep_links(f"{PRIVATE_LINK} again <{PRIVATE_LINK}>") == [DEEP_LINK]

    def test_other_urls_ignored(self):
        assert extract_deep_links("https://example.com/open/i?a=A and https://1password.com") == []

    def test_empty_text_yields_no_links(self):
        assert extract_deep_links("") == []


class TestHandleMessage:
    def test_replies_in_new_thread_on_top_level_message(self):
        say = SaySpy()

        handle_message({"text": PRIVATE_LINK, "ts": "111.0", "channel": "C1"}, say)

        assert len(say.calls) == 1
        reply = say.calls[0]
        assert reply["thread_ts"] == "111.0"
        assert reply["unfurl_links"] is False
        assert f"`{DEEP_LINK}`" in reply["text"]

    def test_replies_in_existing_thread_when_message_is_a_reply(self):
        say = SaySpy()

        handle_message({"text": PRIVATE_LINK, "ts": "222.0", "thread_ts": "111.0", "channel": "C1"}, say)

        assert say.calls[0]["thread_ts"] == "111.0"

    @pytest.mark.parametrize("subtype", ["thread_broadcast", "file_share"])
    def test_processes_allowlisted_subtypes(self, subtype):
        say = SaySpy()

        handle_message({"subtype": subtype, "text": PRIVATE_LINK, "ts": "1.0", "channel": "C1"}, say)

        assert len(say.calls) == 1

    @pytest.mark.parametrize("subtype", ["message_changed", "message_deleted", "bot_message", "channel_join"])
    def test_ignores_other_subtypes(self, subtype):
        say = SaySpy()

        handle_message({"subtype": subtype, "text": PRIVATE_LINK, "ts": "1.0"}, say)

        assert say.calls == []

    def test_ignores_bot_messages(self):
        say = SaySpy()

        handle_message({"bot_id": "B42", "text": PRIVATE_LINK, "ts": "1.0"}, say)

        assert say.calls == []

    def test_no_reply_when_message_has_no_1password_link(self):
        say = SaySpy()

        handle_message({"text": "just chatting", "ts": "1.0"}, say)

        assert say.calls == []

    def test_no_reply_when_message_has_no_text_field(self):
        say = SaySpy()

        handle_message({"ts": "1.0"}, say)

        assert say.calls == []


class TestAutoJoinEnabled:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " Yes "])
    def test_truthy_values(self, value, monkeypatch):
        monkeypatch.setenv("AUTO_JOIN_PUBLIC_CHANNELS", value)
        assert auto_join_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def test_falsy_values(self, value, monkeypatch):
        monkeypatch.setenv("AUTO_JOIN_PUBLIC_CHANNELS", value)
        assert auto_join_enabled() is False

    def test_defaults_to_enabled_when_unset(self, monkeypatch):
        monkeypatch.delenv("AUTO_JOIN_PUBLIC_CHANNELS", raising=False)
        assert auto_join_enabled() is True


class TestAutoJoinPublicChannels:
    @staticmethod
    def page(channels, next_cursor=""):
        return {"channels": channels, "response_metadata": {"next_cursor": next_cursor}}

    def test_makes_no_api_calls_when_disabled(self, monkeypatch):
        monkeypatch.setenv("AUTO_JOIN_PUBLIC_CHANNELS", "false")
        client = StubSlackClient(pages=[])

        auto_join_public_channels(client)

        assert client.list_calls == 0

    def test_joins_channels_across_all_pages(self, monkeypatch):
        monkeypatch.setenv("AUTO_JOIN_PUBLIC_CHANNELS", "true")
        client = StubSlackClient(
            pages=[
                self.page([{"id": "C1", "is_member": False}], next_cursor="cursor-2"),
                self.page([{"id": "C2", "is_member": False}]),
            ]
        )

        auto_join_public_channels(client)

        assert client.joined == ["C1", "C2"]
        assert client.list_calls == 2

    def test_skips_channels_already_joined(self, monkeypatch):
        monkeypatch.setenv("AUTO_JOIN_PUBLIC_CHANNELS", "true")
        client = StubSlackClient(pages=[self.page([{"id": "C1", "is_member": True}, {"id": "C2", "is_member": False}])])

        auto_join_public_channels(client)

        assert client.joined == ["C2"]

    def test_one_failed_join_does_not_abort_the_rest(self, monkeypatch):
        monkeypatch.setenv("AUTO_JOIN_PUBLIC_CHANNELS", "true")
        client = StubSlackClient(
            pages=[
                self.page(
                    [
                        {"id": "C1", "is_member": False, "name": "general"},
                        {"id": "C2", "is_member": False, "name": "random"},
                    ]
                )
            ],
            fail_ids={"C1"},
        )

        auto_join_public_channels(client)

        assert client.joined == ["C2"]

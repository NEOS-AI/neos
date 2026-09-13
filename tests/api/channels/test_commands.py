import pytest

from neos.api.channels.commands import (
    ChannelCommandKind,
    neutralize_untrusted_inline,
    parse_channel_command,
)

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(
    ("text", "kind", "rest"),
    [
        ("/code fix the test", ChannelCommandKind.CODE, "fix the test"),
        ("!code fix the test", ChannelCommandKind.CODE, "fix the test"),
        ("<@U_BOT> /code fix it", ChannelCommandKind.CODE, "fix it"),
        ("/code@NeosBot fix it", ChannelCommandKind.CODE, "fix it"),
        ("/stop", ChannelCommandKind.STOP, ""),
        ("!status", ChannelCommandKind.STATUS, ""),
        ("!approve ca_1", ChannelCommandKind.APPROVE, "ca_1"),
        ("!deny", ChannelCommandKind.DENY, ""),
        ("hello <@U_BOT>", ChannelCommandKind.CHAT, "hello <@U_BOT>"),
        ("/code", ChannelCommandKind.CODE, ""),
        ("/learn remember this", ChannelCommandKind.LEARN, "remember this"),
        ("!learn remember this", ChannelCommandKind.LEARN, "remember this"),
        ("<@U_BOT> /learn a fact", ChannelCommandKind.LEARN, "a fact"),
        ("/learn@NeosBot a fact", ChannelCommandKind.LEARN, "a fact"),
        ("/new", ChannelCommandKind.NEW, ""),
        ("/reset", ChannelCommandKind.NEW, ""),
        ("!new", ChannelCommandKind.NEW, ""),
        ("!reset", ChannelCommandKind.NEW, ""),
        ("<@U_BOT> /new", ChannelCommandKind.NEW, ""),
        ("/compact keep the plan", ChannelCommandKind.COMPACT, "keep the plan"),
        ("!compact", ChannelCommandKind.COMPACT, ""),
        ("/compact@NeosBot shrink", ChannelCommandKind.COMPACT, "shrink"),
        ("/clear", ChannelCommandKind.CLEAR, ""),
        ("!clear", ChannelCommandKind.CLEAR, ""),
        ("<@U_BOT> /clear", ChannelCommandKind.CLEAR, ""),
        ("/cost", ChannelCommandKind.COST, ""),
        ("!cost", ChannelCommandKind.COST, ""),
        ("/export", ChannelCommandKind.EXPORT, ""),
        ("!export", ChannelCommandKind.EXPORT, ""),
        ("/help", ChannelCommandKind.HELP, ""),
        ("/help compact", ChannelCommandKind.HELP, "compact"),
        ("/loop 5m check", ChannelCommandKind.LOOP, "5m check"),
        ("/plan auth", ChannelCommandKind.PROMPT, "auth"),
        ("/diff", ChannelCommandKind.DIFF, ""),
        ("!diff", ChannelCommandKind.DIFF, ""),
        ("/not-a-command", ChannelCommandKind.UNKNOWN, ""),
    ],
)
def test_parse_channel_command(text: str, kind: ChannelCommandKind, rest: str) -> None:
    command = parse_channel_command(text)
    assert command.kind is kind
    assert command.rest == rest


def test_clear_is_not_aliased_to_new() -> None:
    assert parse_channel_command("/clear").kind is ChannelCommandKind.CLEAR
    assert parse_channel_command("/reset").kind is ChannelCommandKind.NEW
    assert parse_channel_command("/new").kind is ChannelCommandKind.NEW
    assert parse_channel_command("/clear").kind is not ChannelCommandKind.NEW


def test_neutralize_strips_control_and_bidi_and_flattens_newlines() -> None:
    raw = "Alice\x00\x07\u202e\nBob\r\nCarol"
    cleaned = neutralize_untrusted_inline(raw)
    assert "\x00" not in cleaned
    assert "\x07" not in cleaned
    assert "\u202e" not in cleaned
    assert "\n" not in cleaned
    assert "\r" not in cleaned
    assert cleaned == "Alice Bob Carol"


def test_neutralize_caps_length() -> None:
    assert len(neutralize_untrusted_inline("x" * 500)) == 240
    assert neutralize_untrusted_inline("abcdef", max_len=3) == "abc"
    assert neutralize_untrusted_inline("  hi  ") == "hi"


def test_neutralize_empty_and_non_string() -> None:
    assert neutralize_untrusted_inline("") == ""
    assert neutralize_untrusted_inline(None) == ""  # type: ignore[arg-type]

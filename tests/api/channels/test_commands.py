import pytest

from neos.api.channels.commands import ChannelCommandKind, parse_channel_command

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
    ],
)
def test_parse_channel_command(text: str, kind: ChannelCommandKind, rest: str) -> None:
    command = parse_channel_command(text)
    assert command.kind is kind
    assert command.rest == rest

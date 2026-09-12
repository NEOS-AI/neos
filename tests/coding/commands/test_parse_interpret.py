from __future__ import annotations

import pytest

from neos.coding.commands import (
    interpret_coding_command,
    parse_slash_command,
)
from neos.coding.commands.types import CommandDisposition, CommandFamily

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(
    ("text", "name", "args", "slash"),
    [
        ("/compact keep the plan", "compact", "keep the plan", True),
        ("!cost", "cost", "", True),
        ("/loop@NeosBot 5m check deploy", "loop", "5m check deploy", True),
        ("<@U_BOT> /plan the cache", "plan", "the cache", True),
        ("hello there", "", "", False),
        ("/", "", "", False),
    ],
)
def test_parse_slash_command(text, name, args, slash) -> None:
    parsed = parse_slash_command(text)
    assert parsed.name == name
    assert parsed.args == args
    assert parsed.slash is slash


def test_interpret_chat_is_not_a_command() -> None:
    decision = interpret_coding_command("Inspect cache first")
    assert decision.disposition is CommandDisposition.CHAT


def test_interpret_unknown_slash() -> None:
    decision = interpret_coding_command("/not-a-real-command")
    assert decision.disposition is CommandDisposition.UNKNOWN
    assert "Unknown command" in decision.message


def test_interpret_loop_is_denied() -> None:
    decision = interpret_coding_command("/loop 5m check the deploy")
    assert decision.disposition is CommandDisposition.DENIED
    assert decision.spec is not None
    assert decision.spec.family is CommandFamily.DISABLED
    assert "disabled" in decision.message.lower()
    assert "cron" in decision.message.lower()


def test_interpret_compact_applies_in_loop() -> None:
    decision = interpret_coding_command("/compact keep the plan")
    assert decision.disposition is CommandDisposition.APPLY_IN_LOOP
    assert decision.canonical_text == "/compact keep the plan"


def test_interpret_plan_injects_prompt() -> None:
    decision = interpret_coding_command("/plan the auth path")
    assert decision.disposition is CommandDisposition.INJECT
    assert "Critical Files" in decision.inject_text
    assert "auth path" in decision.inject_text
    assert decision.inject_text.startswith("Switch to plan")


def test_interpret_clear_is_not_new() -> None:
    clear = interpret_coding_command("/clear")
    reset = interpret_coding_command("/reset")
    assert clear.spec is not None and clear.spec.name == "clear"
    assert reset.spec is not None and reset.spec.name == "new"
    assert clear.disposition is CommandDisposition.APPLY_IN_LOOP
    assert reset.disposition is CommandDisposition.CHANNEL

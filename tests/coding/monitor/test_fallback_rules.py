"""Q5 fallback rules FB1~FB6 -- what stops a task when Jev cannot answer.

Roadmap track Q (docs/OPENAI_DOTS_ANALYSIS_260930.md §6.1). The rules read
only the ledger. Each rule is tested at its threshold and one below it, so a
mutation that shifts a comparison by one is caught.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from neos.coding.domain.events import make_event
from neos.coding.monitor.rules import (
    RULESET_VERSION,
    FallbackThresholds,
    fallback_verdict,
)

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 9, 30, tzinfo=UTC)
LIMITS = FallbackThresholds(
    user_only=1,
    mode_ceiling=2,
    denial_window=10,
    denials_in_window=3,
    repeated_call=3,
    refusals=1,
    spend_multiple=4.0,
    spend_warmup_turns=5,
)


def ev(kind: str, **payload):
    ev.seq += 1
    return make_event(
        task_id="ct_1", seq=ev.seq, event_type=kind, payload=payload, now=NOW, run_id="cr_1"
    )


ev.seq = 0


def denied(reason: str):
    return ev("tool.denied", name="execute.v1", reason_code=reason)


def done(name: str = "read_file.v1"):
    return ev("tool.completed", name=name)


def started(name: str, preview: str):
    return ev("tool.started", name=name, preview=preview)


def turn(tokens: int):
    return ev("model.completed", stop_reason="tool_use", input_tokens=tokens, output_tokens=0)


def test_a_quiet_trajectory_has_no_hit() -> None:
    assert fallback_verdict([done(), done(), turn(100)], LIMITS) is None


def test_fb1_one_user_only_attempt_is_enough() -> None:
    hit = fallback_verdict([denied("policy_user_only")], LIMITS)

    assert (hit.rule, hit.observed, hit.threshold) == ("FB1", 1, 1)


def test_fb2_counts_ceiling_denials() -> None:
    one = [denied("policy_mode_ceiling")]

    assert fallback_verdict(one, LIMITS) is None
    assert fallback_verdict(one + [denied("policy_mode_ceiling")], LIMITS).rule == "FB2"


def test_fb3_looks_only_at_the_recent_window() -> None:
    """Three denials, but the first slides out of a window of ten outcomes."""
    old = [denied("policy_approval_denied")]
    recent = [done() for _ in range(8)] + [denied("policy_approval_denied")] * 2

    assert fallback_verdict(old + recent, LIMITS) is None
    assert fallback_verdict(recent[1:] + [denied("policy_approval_denied")], LIMITS).rule == "FB3"


def test_fb4_the_same_call_again_and_again() -> None:
    twice = [started("execute.v1", "pytest -q")] * 2

    assert fallback_verdict(twice, LIMITS) is None
    hit = fallback_verdict(twice + [started("execute.v1", "pytest -q")], LIMITS)
    assert (hit.rule, hit.observed) == ("FB4", 3)


def test_fb4_different_input_is_a_different_call() -> None:
    calls = [started("execute.v1", f"pytest -k t{i}") for i in range(5)]

    assert fallback_verdict(calls, LIMITS) is None


def test_fb5_a_refusal() -> None:
    assert fallback_verdict([ev("model.refused", stop_reason="refusal")], LIMITS).rule == "FB5"


def test_fb6_a_turn_far_above_the_running_median() -> None:
    warm = [turn(100) for _ in range(5)]

    assert fallback_verdict(warm + [turn(400)], LIMITS) is None
    hit = fallback_verdict(warm + [turn(401)], LIMITS)
    assert hit.rule == "FB6"


def test_fb6_does_not_judge_during_warmup() -> None:
    assert fallback_verdict([turn(10)] * 4 + [turn(10_000)], LIMITS) is None


def test_fb6_ignores_turns_that_do_not_report_usage() -> None:
    """Old ledgers have `model.completed` without tokens. Absent is not zero."""
    silent = [ev("model.completed", stop_reason="tool_use") for _ in range(9)]

    assert fallback_verdict(silent + [turn(10_000)], LIMITS) is None


def test_the_stricter_rule_is_named_first() -> None:
    both = [denied("policy_mode_ceiling")] * 2 + [denied("policy_user_only")]

    assert fallback_verdict(both, LIMITS).rule == "FB1"


def test_the_ruleset_has_a_version() -> None:
    """§9: a judgement without its rule version cannot be reproduced."""
    assert RULESET_VERSION


@pytest.mark.parametrize(
    "field,value",
    [
        ("user_only", 2),
        ("mode_ceiling", 3),
        ("denials_in_window", 4),
        ("repeated_call", 4),
        ("refusals", 2),
        ("spend_multiple", 4.5),
        ("spend_warmup_turns", 6),
        ("denial_window", 9),
    ],
)
def test_config_may_only_make_the_rules_stricter(field: str, value) -> None:
    """Decision 9: thresholds live in settings and move one way only."""
    from pydantic import ValidationError

    from neos.config.schema import JevMonitorConfig

    with pytest.raises(ValidationError):
        JevMonitorConfig(**{field: value})

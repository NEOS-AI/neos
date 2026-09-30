"""Q5: the trajectory monitor -- Jev judges, FB1~FB6 stand in when it cannot.

Shadow only (decision 5): every judgement is one `monitor.judged` payload with
`enforced: False`. Nothing here pauses a task. What is tested is what the
ledger will say, because the ledger is what calibrates the threshold later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from neos.coding.domain.events import make_event
from neos.coding.monitor.monitor import TrajectoryMonitor
from neos.coding.monitor.rules import RULESET_VERSION, FallbackThresholds
from neos.jev.gate import JevProviderBlocked, RiskScore

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 9, 30, tzinfo=UTC)
LIMITS = FallbackThresholds(1, 2, 10, 3, 3, 1, 4.0, 5)


class Scorer:
    def __init__(self, probability=0.1, error: Exception | None = None):
        self.probability = probability
        self.error = error
        self.states = []

    async def score_tool_risk(self, state):
        self.states.append(state)
        if self.error is not None:
            raise self.error
        return RiskScore(probability=self.probability, model="jev-1.13.0", rubric_digest="abc123")


def monitor(scorer, every_n=2):
    return TrajectoryMonitor(
        scorer=scorer, pause_at_or_above=0.8, limits=LIMITS, every_n_tool_results=every_n
    )


_seq = iter(range(1, 10_000))


def ev(kind, **payload):
    return make_event(
        task_id="ct_1", seq=next(_seq), event_type=kind, payload=payload, now=NOW, run_id="cr_1"
    )


def results(n, reason=None):
    if reason:
        return [ev("tool.denied", name="execute.v1", reason_code=reason) for _ in range(n)]
    return [ev("tool.completed", name="read_file.v1") for _ in range(n)]


def test_it_is_due_every_n_tool_results_since_the_last_judgement() -> None:
    m = monitor(Scorer())

    assert not m.due(results(1))
    assert m.due(results(2))
    judged = ev("monitor.judged", tool_results=2)
    assert not m.due(results(2) + [judged] + results(1))
    assert m.due(results(2) + [judged] + results(2))


@pytest.mark.asyncio
async def test_a_jev_answer_is_recorded_with_everything_needed_to_reproduce_it() -> None:
    payload = await monitor(Scorer(probability=0.85)).judge(results(2), mode="background")

    assert payload["judge"] == "jev"
    assert payload["probability"] == 0.85
    assert payload["pause_at_or_above"] == 0.8
    assert payload["would_pause"] is True
    assert payload["rubric_digest"] == "abc123"
    assert payload["model"] == "jev-1.13.0"
    assert payload["enforced"] is False
    assert payload["tool_results"] == 2


@pytest.mark.asyncio
async def test_the_threshold_itself_would_pause() -> None:
    """`pause_at_or_above` -- the boundary is on the pausing side (S13)."""
    payload = await monitor(Scorer(probability=0.8)).judge(results(2), mode="interactive")

    assert payload["would_pause"] is True


@pytest.mark.asyncio
async def test_below_the_threshold_it_would_not_pause() -> None:
    payload = await monitor(Scorer(probability=0.79)).judge(results(2), mode="interactive")

    assert payload["would_pause"] is False


@pytest.mark.asyncio
async def test_jev_sees_the_trajectory_not_the_transcript() -> None:
    """The monitor reads the ledger: tools, outcomes, reasons, mode."""
    scorer = Scorer()
    events = [ev("tool.started", name="execute.v1", preview="pytest")] + results(
        1, "policy_mode_ceiling"
    ) + results(1)

    await monitor(scorer).judge(events, mode="background")

    [state] = scorer.states
    assert state["mode"] == "background"
    assert state["denials_by_reason"] == {"policy_mode_ceiling": 1}
    assert [step["outcome"] for step in state["recent_tool_results"]] == ["denied", "completed"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [TimeoutError(), JevProviderBlocked("403"), RuntimeError("boom")]
)
async def test_when_jev_cannot_answer_the_fallback_rules_judge(error) -> None:
    """D-L1 for the monitor: an unanswered call falls back, and says so."""
    events = results(1, "policy_user_only") + results(1)

    payload = await monitor(Scorer(error=error)).judge(events, mode="autonomous")

    assert payload["judge"] == "fallback_rules"
    assert payload["jev_unavailable"] is True
    assert payload["jev_reason"] == type(error).__name__
    assert payload["ruleset"] == RULESET_VERSION
    assert payload["rule"] == "FB1"
    assert payload["would_pause"] is True
    assert payload["enforced"] is False


@pytest.mark.asyncio
async def test_a_quiet_fallback_says_it_would_not_pause() -> None:
    payload = await monitor(Scorer(error=TimeoutError())).judge(results(2), mode="interactive")

    assert payload["judge"] == "fallback_rules"
    assert payload["would_pause"] is False
    assert payload["rule"] is None


@pytest.mark.asyncio
async def test_a_missing_probability_is_unavailable_not_zero() -> None:
    """Zero would read as "safe". No answer is no answer."""
    payload = await monitor(Scorer(probability=None)).judge(
        results(1, "policy_user_only") + results(1), mode="interactive"
    )

    assert payload["judge"] == "fallback_rules"
    assert payload["jev_reason"] == "no_probability"
    assert payload["rule"] == "FB1"

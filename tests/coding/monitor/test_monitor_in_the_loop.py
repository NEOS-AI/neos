"""Q5 in the loop: the monitor judges at the model-turn safe point, in shadow.

The monitor reads the ledger through the event store's `list_after` -- the
production `PostgresCodingService` has it. It appends `monitor.judged` and
changes nothing else: a crashing monitor must not change the run.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding.model.base import ModelCompleted, ModelUsage
from neos.coding.monitor.monitor import TrajectoryMonitor
from neos.coding.monitor.rules import FallbackThresholds
from neos.jev.gate import RiskScore
from tests.coding.loop.support import (
    INPUT,
    Events,
    completed,
    harness,
    tool_call,
)

pytestmark = pytest.mark.no_db


class _Arrivals(list):
    """`yielded.append(event)` lands the event in the ledger in arrival order."""

    def __init__(self, ledger):
        super().__init__()
        self._ledger = ledger

    def append(self, event):
        super().append(event)
        self._ledger.arrive(event)


class LedgerEvents(Events):
    """The sink the loop appends to, plus a reader over the whole ledger.

    Like the production ledger, one task has one `seq` and seq order is commit
    order (Q5b MP6: the monitor reads with a cursor). The fake repository and the
    fake sink number their events independently (1.. and 100..), so the ledger
    renumbers each event as it arrives -- appended by the loop, or yielded to
    the driver (which records it in `yielded`).
    """

    def __init__(self):
        super().__init__()
        self.ledger = []
        self.yielded = _Arrivals(self)

    async def append(self, *, task_id, event_type, payload, **ids):
        event = await super().append(
            task_id=task_id, event_type=event_type, payload=payload, **ids
        )
        self.arrive(event)
        return event

    def arrive(self, event):
        self.ledger.append(replace(event, seq=len(self.ledger) + 1))

    async def list_after(self, task_id, *, after_seq=0, limit=500):
        return [e for e in self.ledger if e.seq > after_seq][:limit]


class Scorer:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    async def score_tool_risk(self, state):
        self.calls += 1
        if self.error:
            raise self.error
        return RiskScore(probability=0.2, model="jev-1.13.0", rubric_digest="abc")


def _three_reads():
    return [
        [tool_call(f"r{i}", "read_file.v1", {"path": f"f{i}.py"}), completed()]
        for i in range(3)
    ] + [[ModelCompleted("end_turn", ModelUsage(1, 1))]]


async def _run(monitor, *, events=None):
    """Drive the durable loop step by step (one model turn XOR one tool per call)."""
    h = harness(_three_reads(), monitor=monitor)
    ledger = events if events is not None else LedgerEvents()
    h.deps = type(h.deps)(repository=h.deps.repository, events=ledger, lease=h.deps.lease)
    checkpoint = None
    for _ in range(12):
        async for event in h.loop.run(INPUT, checkpoint, h.deps):
            if hasattr(ledger, "yielded"):
                ledger.yielded.append(event)
        if not h.model.turns:  # the closing end_turn was consumed
            break
        checkpoint = h.repository.checkpoints[-1]
    return h, ledger


def _monitor(scorer, every_n=2):
    return TrajectoryMonitor(
        scorer=scorer,
        pause_at_or_above=0.8,
        limits=FallbackThresholds(1, 2, 10, 3, 3, 1, 4.0, 5),
        every_n_tool_results=every_n,
    )


def _judged(ledger):
    return [e for e in ledger.items if e.type == "monitor.judged"]


@pytest.mark.asyncio
async def test_the_monitor_judges_every_n_tool_results_in_shadow() -> None:
    scorer = Scorer()
    h, ledger = await _run(_monitor(scorer, every_n=2))

    [judged] = _judged(ledger)
    assert judged.payload["judge"] == "jev"
    assert judged.payload["tool_results"] == 2
    assert judged.payload["enforced"] is False
    assert [call.name for call in h.executor.calls] == ["read_file.v1"] * 3


@pytest.mark.asyncio
async def test_no_monitor_no_judgement() -> None:
    _h, ledger = await _run(None)

    assert _judged(ledger) == []


@pytest.mark.asyncio
async def test_a_sink_that_cannot_be_read_is_not_judged() -> None:
    """Without `list_after` there is no ledger to read -- the monitor stays out."""
    scorer = Scorer()
    await _run(_monitor(scorer), events=Events())

    assert scorer.calls == 0


@pytest.mark.asyncio
async def test_a_broken_monitor_does_not_change_the_run() -> None:
    """Shadow means nothing downstream moves. Mutation: let the error escape."""

    class Broken:
        def due(self, events):
            raise RuntimeError("monitor bug")

    h, ledger = await _run(Broken())

    assert [call.name for call in h.executor.calls] == ["read_file.v1"] * 3
    assert _judged(ledger) == []


def test_it_is_off_unless_asked() -> None:
    from neos.config.schema import JevConfig
    from neos.jev.assembly import build_trajectory_monitor

    assert build_trajectory_monitor(JevConfig()) is None
    assert build_trajectory_monitor(JevConfig(enabled=True)) is None


@pytest.mark.parametrize(
    "fields",
    [
        # 켜려면 멈춤 경계를 적어야 한다 -- 기본값은 없다(§12.4).
        {"enabled": True, "monitor": {"shadow_enabled": True}},
        # 켤 수 없는 플래그는 읽는 사람을 틀리게 만든다.
        {"enabled": False, "monitor": {"shadow_enabled": True, "pause_at_or_above": 0.8}},
    ],
)
def test_a_misconfigured_monitor_fails_at_boot(fields) -> None:
    from pydantic import ValidationError

    from neos.config.schema import JevConfig

    with pytest.raises(ValidationError):
        JevConfig(**fields)


def test_the_factory_refuses_a_monitor_without_a_key_or_a_pinned_model() -> None:
    from neos.config.schema import JevConfig
    from neos.jev.assembly import MisconfiguredJev, build_trajectory_monitor

    on = {"shadow_enabled": True, "pause_at_or_above": 0.8}
    with pytest.raises(MisconfiguredJev):
        build_trajectory_monitor(JevConfig(enabled=True, model="jev-1.13.0", monitor=on), api_key="")
    with pytest.raises(MisconfiguredJev):
        build_trajectory_monitor(JevConfig(enabled=True, monitor=on), api_key="k")


def test_a_configured_monitor_carries_the_settings() -> None:
    from neos.config.schema import JevConfig
    from neos.jev.assembly import build_trajectory_monitor

    config = JevConfig(
        enabled=True,
        model="jev-1.13.0",
        monitor={"shadow_enabled": True, "pause_at_or_above": 0.7, "denials_in_window": 2},
    )

    built = build_trajectory_monitor(config, api_key="k", client=object())

    assert isinstance(built, TrajectoryMonitor)
    assert built._pause_at == 0.7
    assert built._limits.denials_in_window == 2

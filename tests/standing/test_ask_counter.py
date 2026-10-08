"""Q9c: `standing_ask_total{outcome}` counts each ask outcome where it is decided
(design §9.1 · controller ruling after Q9b). Outcomes are read by name."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from neos.coding.domain.approvals import evaluate_approval
from neos.config.schema import ChannelConfig
from neos.observability.metrics import metrics
from neos.standing.asks import AgentAsks, ReplyDestination, resolve_reply_destination
from tests.coding.loop.support import INPUT, NOW, completed, harness, tool_call

pytestmark = pytest.mark.no_db

AGENT_TASK = replace(INPUT, mode="autonomous", agent_id="sa_q9", owner_id="u_q9")


def _count(outcome: str) -> float:
    return metrics.standing_ask_total.labels(outcome=outcome)._value.get()


async def _ask_once(destination, *, pending=False):
    h = harness(
        [[tool_call("a1", "ask_user.v1", {"questions": ["q?"]}), completed()], [completed()]],
        approval_evaluator=evaluate_approval,
    )

    async def find(agent_id, owner_id):
        return destination

    h.loop._asks = AgentAsks(store=h.repository.asks, destination=find)
    if pending:
        await h.repository.asks.open(
            agent_id="sa_q9", task_id="ct_x", run_id="cr_x", tool_call_id="x",
            questions=["earlier"], reply_session_id=None, asked_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
    [event async for event in h.loop.run(AGENT_TASK, None, h.deps)]


@pytest.mark.parametrize(
    ("outcome", "destination", "pending"),
    [
        ("asked", ReplyDestination("slack", "D1", None), False),
        ("refused_pending", ReplyDestination("slack", "D1", None), True),
        ("refused_no_channel", None, False),
    ],
)
@pytest.mark.asyncio
async def test_the_loop_counts_its_ask_outcome(outcome, destination, pending) -> None:
    before = {name: _count(name) for name in ("asked", "refused_pending", "refused_no_channel")}

    await _ask_once(destination, pending=pending)

    after = {name: _count(name) for name in before}
    assert {name: after[name] - before[name] for name in before} == {
        name: (1.0 if name == outcome else 0.0) for name in before
    }


@pytest.mark.asyncio
async def test_a_failed_lookup_is_counted() -> None:
    class Broken:
        async def reply_session(self, agent_id):
            raise RuntimeError("db down")

    before = _count("lookup_failed")

    destination = await resolve_reply_destination(
        "sa_1", "u_1", threads=Broken(), notices=None, channels=ChannelConfig()
    )

    assert destination is None
    assert _count("lookup_failed") == before + 1


@pytest.mark.asyncio
async def test_an_answer_is_counted(monkeypatch) -> None:
    from tests.api.channels.test_gateway_ask_answers import World, _settings, _slack

    _settings(monkeypatch)
    world = World()
    await world.waiting()
    before = _count("answered")

    await world.gateway.dispatch(_slack("main"))
    await world.gateway.dispatch(_slack("not an answer any more"))

    assert _count("answered") == before + 1

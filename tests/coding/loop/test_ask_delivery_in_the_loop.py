"""Q9b in the loop: the question's notice rides the ask's transaction, the worker
never calls the gateway, and the port wired by `_prepare_real_coding_loop` does
nothing while the flag is off (design §6.2 · §9.1, row (h))."""

from __future__ import annotations

from dataclasses import replace

import pytest

from neos.coding import runtime as runtime_module
from neos.coding.domain.approvals import evaluate_approval
from neos.config.schema import AppConfig
from neos.standing.asks import AgentAsks, ReplyDestination
from tests.coding.loop.support import INPUT, completed, harness, tool_call

pytestmark = pytest.mark.no_db

AGENT = "sa_q9"
AGENT_TASK = replace(INPUT, mode="autonomous", agent_id=AGENT, owner_id="u_q9")
ASK = {"questions": ["Which branch?", "Run tests?"]}


def _turns():
    return [[tool_call("a1", "ask_user.v1", ASK), completed()], [completed()]]


async def _run(h, input=AGENT_TASK):
    return [event async for event in h.loop.run(input, None, h.deps)]


def _port(h, destination):
    async def find(agent_id, owner_id):
        return destination

    return AgentAsks(store=h.repository.asks, destination=find, max_body_chars=3500)


@pytest.mark.asyncio
async def test_the_notice_rides_the_ask_transaction() -> None:
    """Mutation: drop `notice=` from the loop's call -> nothing is ever sent."""
    h = harness(_turns(), approval_evaluator=evaluate_approval)
    h.loop._asks = _port(h, ReplyDestination("telegram", "42", "v2:telegram:dm:42:-"))

    await _run(h)

    ask = await h.repository.asks.waiting_for_agent(AGENT)
    [(notice, target)] = h.repository.notices
    assert notice.dedupe_key == f"question:{ask.ask_id}"
    assert notice.kind == "question_asked"
    assert (target.channel_type, target.channel_id) == ("telegram", "42")
    assert "Which branch?" in notice.body and "one line per question" in notice.body


@pytest.mark.asyncio
async def test_the_worker_never_calls_the_gateway(monkeypatch) -> None:
    """Mutation: send from the loop -> a worker-side send that would be lost."""
    from neos.api.channels.gateway import ChannelGateway

    calls = []

    async def send(self, *args, **kwargs):
        calls.append(args)

    monkeypatch.setattr(ChannelGateway, "send_to_channel", send)
    monkeypatch.setattr(ChannelGateway, "get_instance", classmethod(lambda cls: calls.append("get") or None))
    h = harness(_turns(), approval_evaluator=evaluate_approval)
    h.loop._asks = _port(h, ReplyDestination("slack", "D1", "v2:slack:T1:D1:-"))

    events = await _run(h)

    assert [e.type for e in events][-2:] == ["question.asked", "task.status.changed"]
    assert calls == []


def _real_loop(standing: dict):
    config = AppConfig.model_validate(
        {
            "coding_model": {
                "enabled": True,
                "model": "claude-test",
                "input_cost_micros_per_million": 3_000_000,
                "output_cost_micros_per_million": 15_000_000,
            },
            "sandbox": {"enabled": True},
            "secrets": {"anthropic_api_key": "test-key"},
            "standing_agents": standing,
        }
    )
    return runtime_module._create_real_coding_loop(config=config, sandboxes=object())


ON = {
    "enabled": True,
    "ask": {"enabled": True, "expire_hours": 6},
    "notifications": {"enabled": True, "max_body_chars": 999},
    "threads": {"enabled": True},
}


def test_the_real_loop_wires_the_port() -> None:
    loop = _real_loop(ON)

    assert isinstance(loop._asks, AgentAsks)
    assert loop._asks.enabled() is True
    assert loop._asks.expire_hours == 6
    assert loop._asks.max_body_chars == 999


@pytest.mark.parametrize("off", ["enabled", "ask", "notifications", "threads"])
def test_the_port_is_wired_but_inactive_when_any_flag_is_off(off) -> None:
    standing = {key: (dict(value) if isinstance(value, dict) else value) for key, value in ON.items()}
    if off == "enabled":
        standing["enabled"] = False
    else:
        standing[off]["enabled"] = False

    loop = _real_loop(standing)

    assert loop._asks is not None
    assert loop._asks.enabled() is False


@pytest.mark.asyncio
async def test_flag_off_with_the_port_wired_is_unchanged() -> None:
    """Design row (h) with the REAL wired port. Mutation: drop the `enabled()`
    check from `_answerable_ask` -> the flag-off agent task asks."""
    wired = _real_loop({**ON, "ask": {"enabled": False}})._asks
    baseline = harness(_turns(), approval_evaluator=evaluate_approval)
    h = harness(_turns(), approval_evaluator=evaluate_approval)
    h.loop._asks = wired

    without = await _run(baseline)
    with_port = await _run(h)

    def shape(events):
        return [
            (e.type, {k: v for k, v in e.payload.items() if k != "part_id"}) for e in events
        ]

    assert shape(with_port) == shape(without)
    assert [e.payload.get("reason_code") for e in with_port if e.type == "tool.denied"] == [
        "policy_approval_denied"
    ]
    assert h.repository.asks.rows == {} and h.repository.notices == []

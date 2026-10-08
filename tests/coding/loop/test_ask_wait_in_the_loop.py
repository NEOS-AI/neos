"""Q9a in the loop: an agent's autonomous task asks its owner and waits.

docs/Q9_ASK_AND_WAIT_DESIGN_261005.md §5. Only an agent's `autonomous` task takes
the question branch; interactive keeps its approval card (Q9-2), background keeps
its READ_ONLY ceiling (Q9-1), and a human-opened autonomous task still folds to
DENY. Each test names the mutation it kills.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from neos.coding.domain.approvals import evaluate_approval
from neos.coding.loop.anthropic import AnthropicLoopConfig
from neos.coding.loop.durable import CodingLoopWaitingUser
from neos.standing.asks import AgentAsks, ReplyDestination
from tests.coding.loop.support import (
    INPUT,
    NOW,
    completed,
    harness,
    tool_call,
)

pytestmark = pytest.mark.no_db

AGENT = "sa_q9"
AGENT_TASK = replace(INPUT, mode="autonomous", agent_id=AGENT, owner_id="u_q9")
ASK = {"questions": ["Which branch should I use?"]}
SLACK = ReplyDestination("slack", "D1", "v2:slack:T1:D1:-")


def _ask_turns():
    return [[tool_call("a1", "ask_user.v1", ASK), completed()], [completed()]]


def _with_asks(h, destination=SLACK, hours=24):
    calls = []

    async def find(agent_id, owner_id):
        calls.append((agent_id, owner_id))
        return destination

    h = h.rebuilt(
        asks=AgentAsks(store=h.repository.asks, destination=find, expire_hours=hours)
    )
    return h, calls


async def _run(h, input, checkpoint=None):
    return [event async for event in h.loop.run(input, checkpoint, h.deps)]


def _denials(events):
    return [e.payload.get("reason_code") for e in events if e.type == "tool.denied"]


@pytest.mark.asyncio
async def test_an_agent_autonomous_task_asks_and_waits() -> None:
    """(a) Mutation: drop the question branch -> the fold denies it as today."""
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval)
    h, asked_for = _with_asks(h)

    events = await _run(h, AGENT_TASK)

    assert [e.type for e in events][-2:] == ["question.asked", "task.status.changed"]
    asked, status = events[-2:]
    assert status.payload == {"status": "waiting_user"}
    assert asked.checkpoint_id == status.checkpoint_id == h.repository.checkpoints[-1].checkpoint_id
    assert asked.tool_call_id == "a1"
    assert asked.payload["questions"] == ["Which branch should I use?"]
    assert asked.payload["reply_channel_type"] == "slack"
    assert asked.payload["expires_at"] == (NOW + timedelta(hours=24)).isoformat()
    assert "D1" not in str(asked.payload)  # no channel id or session key to the FE
    assert h.executor.calls == []  # no tool result yet
    assert h.repository.task_statuses["ct_1"] == "waiting_user"
    assert h.repository.active_run.status.value == "running"
    assert asked_for == [(AGENT, "u_q9")]
    ask = await h.repository.asks.waiting_for_agent(AGENT)
    assert (ask.task_id, ask.run_id, ask.tool_call_id) == ("ct_1", "cr_1", "a1")
    assert ask.reply_session_id == "v2:slack:T1:D1:-"
    head = h.repository.checkpoints[-1].loop_state
    assert head["pending_tool_calls"][head["pending_tool_index"]]["tool_call_id"] == "a1"


@pytest.mark.asyncio
async def test_expiry_comes_from_the_port() -> None:
    """Mutation: hard-code the expiry -> the configured hours are ignored."""
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval)
    h, _ = _with_asks(h, hours=3)

    await _run(h, AGENT_TASK)

    ask = await h.repository.asks.waiting_for_agent(AGENT)
    assert ask.expires_at == NOW + timedelta(hours=3)


async def _events_and_state(input, *, with_port):
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval)
    if with_port:
        h, _ = _with_asks(h)
    events = await _run(h, input)
    # part ids are random per run; everything else must match
    return h, [
        (e.type, {k: v for k, v in e.payload.items() if k != "part_id"}) for e in events
    ]


@pytest.mark.asyncio
async def test_interactive_is_byte_for_byte_unchanged() -> None:
    """(b) Q9-2. Mutation: drop the `mode == autonomous` check -> interactive asks."""
    _, without = await _events_and_state(INPUT, with_port=False)
    h, with_port = await _events_and_state(replace(INPUT, agent_id=AGENT), with_port=True)

    assert with_port == without
    assert [kind for kind, _ in with_port][-2:] == ["approval.requested", "task.status.changed"]
    assert h.repository.asks.rows == {}


@pytest.mark.asyncio
async def test_background_keeps_its_ceiling() -> None:
    """(c) Q9-1. Mutation: let background into the branch -> it asks."""
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval)
    h, _ = _with_asks(h)

    events = await _run(h, replace(AGENT_TASK, mode="background"))

    assert _denials(events) == ["policy_mode_ceiling"]
    assert h.repository.asks.rows == {}
    assert h.repository.task_statuses["ct_1"] == "running"


@pytest.mark.asyncio
async def test_a_human_opened_autonomous_task_still_folds_to_deny() -> None:
    """(d) Mutation: drop the `agent_id` check -> a task with nobody to answer waits forever."""
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval)
    h, _ = _with_asks(h)

    events = await _run(h, replace(AGENT_TASK, agent_id=None))

    assert _denials(events) == ["policy_approval_denied"]
    assert h.repository.asks.rows == {}


@pytest.mark.asyncio
async def test_with_the_port_off_an_agent_task_folds_as_today() -> None:
    """(h) `ask_effective` false -> no port -> the unattended fold, unchanged."""
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval)

    events = await _run(h, AGENT_TASK)

    assert _denials(events) == ["policy_approval_denied"]
    assert h.repository.task_statuses["ct_1"] == "running"


@pytest.mark.asyncio
async def test_a_second_question_of_the_same_agent_is_refused_and_the_task_runs_on() -> None:
    """(e) Review Focus 3. Mutation: treat `None` as a wait -> the task hangs."""
    h = harness(
        [
            [tool_call("a1", "ask_user.v1", ASK), completed()],
            [tool_call("r1", "read_file.v1", {"path": "a.txt"}), completed()],
            [completed()],
        ],
        approval_evaluator=evaluate_approval,
    )
    h, _ = _with_asks(h)
    await h.repository.asks.open(
        agent_id=AGENT,
        task_id="ct_other",
        run_id="cr_other",
        tool_call_id="x1",
        questions=["earlier"],
        reply_session_id=None,
        asked_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    events = await _run(h, AGENT_TASK)

    assert _denials(events) == ["ask_pending"]
    assert not [e for e in events if e.type == "question.asked"]
    assert h.repository.task_statuses["ct_1"] == "running"
    denied = [e for e in events if e.type == "tool.denied"][0]
    assert denied.payload.get("denied_by") != "user"
    # the task keeps going: the next invocation asks the model again
    before = len(h.model.requests)
    await _run(h, AGENT_TASK, h.repository.checkpoints[-1])
    assert len(h.model.requests) == before + 1


@pytest.mark.asyncio
async def test_no_reply_channel_refuses_and_does_not_wait() -> None:
    """(f) Mutation: ask without a destination -> nobody can answer, the task hangs."""
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval)
    h, _ = _with_asks(h, destination=None)

    events = await _run(h, AGENT_TASK)

    assert _denials(events) == ["no_reply_channel"]
    assert h.repository.asks.rows == {}
    assert h.repository.task_statuses["ct_1"] == "running"


@pytest.mark.asyncio
async def test_an_allow_listed_ask_still_asks() -> None:
    """(g) ALLOW would run `ask_user` with empty answers. Mutation: return
    `validated` on ALLOW -> the executor runs it unanswered."""
    config = AnthropicLoopConfig(
        model="claude-test", system="code", approval_allow_tools=frozenset({"ask_user.v1"})
    )
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval, config=config)
    h, _ = _with_asks(h)

    events = await _run(h, AGENT_TASK)

    assert [e.type for e in events][-2:] == ["question.asked", "task.status.changed"]
    assert h.executor.calls == []


@pytest.mark.asyncio
async def test_an_operator_deny_list_still_denies() -> None:
    """Only the fold is skipped. Mutation: skip the evaluator on the branch -> deny ignored."""
    config = AnthropicLoopConfig(
        model="claude-test", system="code", approval_deny_tools=frozenset({"ask_user.v1"})
    )
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval, config=config)
    h, _ = _with_asks(h)

    events = await _run(h, AGENT_TASK)

    assert _denials(events) == ["policy_approval_denied"]
    assert h.repository.asks.rows == {}


@pytest.mark.asyncio
async def test_a_global_unattended_operator_setting_still_folds() -> None:
    """The operator's narrowing wins. Mutation: pass `unattended=False` past the config OR."""
    config = AnthropicLoopConfig(model="claude-test", system="code", approval_unattended=True)
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval, config=config)
    h, _ = _with_asks(h)

    events = await _run(h, AGENT_TASK)

    assert _denials(events) == ["policy_approval_denied"]


@pytest.mark.asyncio
async def test_a_waiting_question_does_not_move_on_resume() -> None:
    """(i) Mutation: ask again instead of raising -> a second question, or a hang."""
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval)
    h, _ = _with_asks(h)
    await _run(h, AGENT_TASK)
    h.repository.task_statuses["ct_1"] = "running"  # a stray continuation got a lease
    asked_requests = len(h.model.requests)

    with pytest.raises(CodingLoopWaitingUser):
        await _run(h, AGENT_TASK, h.repository.checkpoints[-1])

    assert len(h.model.requests) == asked_requests
    assert h.executor.calls == []
    assert len(h.repository.asks.rows) == 1


@pytest.mark.asyncio
async def test_an_answer_reaches_the_tool_input_after_validation() -> None:
    """Mutation: drop `_with_answers` on the branch -> the tool runs with no answers."""
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval)
    h, _ = _with_asks(h)
    await _run(h, AGENT_TASK)
    ask = await h.repository.asks.waiting_for_agent(AGENT)
    await h.repository.asks.answer(ask.ask_id, ["main"], now=NOW)
    h.repository.task_statuses["ct_1"] = "running"

    await _run(h, AGENT_TASK, h.repository.checkpoints[-1])

    assert [call.name for call in h.executor.calls] == ["ask_user.v1"]
    assert h.executor.calls[0].input["answers"] == ["main"]
    assert h.executor.calls[0].input["questions"] == ASK["questions"]


@pytest.mark.parametrize(("closed", "reason"), [("expired", "ask_expired"), ("cancelled", "ask_cancelled")])
@pytest.mark.asyncio
async def test_a_closed_question_is_refused_on_resume(closed, reason) -> None:
    """Q-C: expiry does not end the task -- the loop resumes and the call is refused.
    Mutation: map every closed status to one code -> the reason lies."""
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval)
    h, _ = _with_asks(h)
    await _run(h, AGENT_TASK)
    if closed == "expired":
        await h.repository.asks.expire_due(NOW + timedelta(days=2))
    else:
        await h.repository.asks.cancel_for_task("ct_1")
    h.repository.task_statuses["ct_1"] = "running"

    events = await _run(h, AGENT_TASK, h.repository.checkpoints[-1])

    assert _denials(events) == [reason]
    assert h.executor.calls == []


@pytest.mark.asyncio
async def test_cancelling_a_waiting_task_frees_the_agent() -> None:
    """(j) Mutation: drop the ask close from `mark_task_cancelled` -> `ask_pending` forever."""
    h = harness(_ask_turns(), approval_evaluator=evaluate_approval)
    h, _ = _with_asks(h)
    await _run(h, AGENT_TASK)

    await h.repository.mark_task_cancelled(task_id="ct_1", now=NOW)

    assert await h.repository.asks.waiting_for_agent(AGENT) is None
    fresh = await h.repository.asks.open(
        agent_id=AGENT,
        task_id="ct_2",
        run_id="cr_2",
        tool_call_id="b1",
        questions=["next"],
        reply_session_id=None,
        asked_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    assert fresh is not None

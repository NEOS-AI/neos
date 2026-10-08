"""Q9c gap 2: what the gateway records is what the resumed `ask_user.v1` receives.

One in-memory run repository is shared by the loop and the gateway: the loop asks,
the owner answers in a DM (two lines for two questions, decision Q-B), the loop is
resumed from the latest checkpoint, and the tool's `pairs` match the answer lines.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from neos.api.channels.base import ChannelMessage
from neos.api.channels.gateway import ChannelGateway
from neos.coding.domain.approvals import evaluate_approval
from neos.coding.tools.executor import SandboxToolExecutor
from neos.config.schema import ChannelPrincipal
from neos.standing.ask_answers import ChannelAskAnswers
from neos.standing.asks import AgentAsks, ReplyDestination
from neos.standing.channel_threads import ChannelAgentThreads
from neos.standing.store import InMemoryStandingAgentStore
from neos.standing.threads import InMemoryAgentThreadStore
from tests.api.channels.conftest import install_channel_settings
from tests.coding.loop.support import INPUT, completed, harness, tool_call

pytestmark = pytest.mark.no_db

OWNER = "u_alice"
NOW = datetime(2026, 7, 19, tzinfo=UTC)
QUESTIONS = [
    "Which branch?",
    {"prompt": "Run tests?", "options": [{"label": "yes"}, {"label": "no"}]},
]


class Workflow:
    async def execute_workflow(self, payload, use_checkpointer=True):
        return {"final_response": "chat"}


@pytest.mark.asyncio
async def test_the_answer_lines_reach_the_resumed_tool_as_pairs(monkeypatch) -> None:
    installed = install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        principals=[ChannelPrincipal(platform="slack", platform_user_id="U_alice", user_id=OWNER)],
    )
    standing = installed.config.standing_agents
    standing.enabled = True
    standing.threads.enabled = True
    standing.notifications.enabled = True
    standing.ask.enabled = True

    agents = InMemoryStandingAgentStore()
    threads = InMemoryAgentThreadStore(agents)
    agent = await agents.create(OWNER, "Dot")
    h = harness(
        [[tool_call("a1", "ask_user.v1", {"questions": QUESTIONS}), completed()], [completed()]],
        approval_evaluator=evaluate_approval,
    )

    async def destination(agent_id, owner_id):
        return ReplyDestination("slack", "D_alice", "v2:slack:T1:D_alice:-")

    h = h.rebuilt(asks=AgentAsks(store=h.repository.asks, destination=destination))
    h.repository.task_owners["ct_1"] = OWNER
    task = replace(INPUT, mode="autonomous", agent_id=agent.agent_id, owner_id=OWNER)
    [event async for event in h.loop.run(task, None, h.deps)]
    assert h.repository.task_statuses["ct_1"] == "waiting_user"

    async def resume(ask, owner_id, answers, channel_type):
        return await h.repository.answer_user_question(
            ask_id=ask.ask_id,
            owner_id=owner_id,
            answers=answers,
            channel_type=channel_type,
            now=NOW,
        )

    gateway = ChannelGateway(
        Workflow(),
        agent_threads=ChannelAgentThreads(agents, threads),
        ask_answers=ChannelAskAnswers(agents, threads, h.repository.asks, resume=resume),
    )
    reply = await gateway.dispatch(
        ChannelMessage(
            user_id=OWNER,
            session_id="v2:slack:T1:D_alice:-",
            text="1. release/2.4\n2. no",
            channel_type="slack",
            channel_id="D_alice",
            metadata={"slack_user_id": "U_alice", "is_dm": True, "idempotency_key": "ev-1"},
        )
    )
    assert reply.startswith("Answer recorded")

    [event async for event in h.loop.run(task, h.repository.checkpoints[-1], h.deps)]

    [call] = h.executor.calls
    assert call.name == "ask_user.v1"
    pairs = SandboxToolExecutor._ask_user(call).entries[0]["pairs"]
    assert pairs == [
        {"question": "Which branch?", "answer": "release/2.4"},
        {"question": "Run tests?", "answer": "no"},
    ]

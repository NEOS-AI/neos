"""Q8d: a web conversation attached to the agent thread reads the thread, end to end
through ChatStreamPipeline.run (docs/Q8_CROSS_CHANNEL_THREAD_DESIGN_261005.md §8).

The LLM fake records the `messages` it was handed -- the assertion reads exactly
what the model would see. Stores are in memory (their Postgres twins share one
contract, tests/standing/test_agent_threads_contract.py).
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.api.services.chat_stream_pipeline import ChatStreamPipeline  # noqa: E402
from neos.standing.channel_threads import ChannelAgentThreads, web_session_id  # noqa: E402
from neos.standing.models import StandingAgentStatus  # noqa: E402
from neos.standing.store import InMemoryStandingAgentStore  # noqa: E402
from neos.standing.threads import InMemoryAgentThreadStore, thread_window  # noqa: E402

pytestmark = pytest.mark.no_db

OWNER = "u_alice"
CONVERSATION = "conv_agent"
SLACK_DM = "v2:slack:T1:D_alice:-"


class Storage:
    """The chat service fake: stores messages, hands back the tail like the real one."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def add_message(self, **kwargs):
        record = {"message_id": f"m{len(self.messages) + 1}", **kwargs}
        self.messages.append(record)
        return record

    async def get_conversation_messages(self, conversation_id, limit=20):
        return [m for m in self.messages if m["conversation_id"] == conversation_id][-limit:]


class RecordingLLM:
    def __init__(self) -> None:
        self.messages: list[dict] | None = None

    async def generate_response_stream_with_tools(self, **kwargs):
        self.messages = kwargs["conversation_messages"]
        yield {"type": "start", "model": kwargs["model_name"], "provider": "anthropic"}
        yield {"type": "content", "content": "the launch is friday"}
        yield {
            "type": "complete",
            "full_content": "the launch is friday",
            "model_name": kwargs["model_name"],
            "provider": "anthropic",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "cost": {"total_cost": 0},
            "latency_ms": 1,
        }


@pytest.fixture
def flags(monkeypatch):
    from neos.config.settings import settings

    for module in (
        "neos.api.services.chat_stream_pipeline",
        "neos.api.services.chat_stream_strategy",
    ):
        monkeypatch.setattr(f"{module}.app_settings.ENABLE_WORKFLOW_IN_CHAT", False, raising=False)
    monkeypatch.setattr(
        "neos.api.services.chat_stream_strategy.app_settings.TOOL_SEARCH_ENABLED", False
    )
    monkeypatch.setattr(
        "neos.api.services.chat_system_prompt_builder.app_settings.ARTIFACTS_ENABLED", False
    )
    monkeypatch.setattr(
        "neos.api.services.chat_system_prompt_builder.app_settings.INLINE_VIS_ENABLED", False
    )
    monkeypatch.setattr(settings.config.standing_agents, "enabled", True)
    monkeypatch.setattr(settings.config.standing_agents.threads, "enabled", True)
    return settings


async def _world(*, attach_web: bool = True, status=StandingAgentStatus.ACTIVE):
    agents = InMemoryStandingAgentStore()
    threads = InMemoryAgentThreadStore(agents)
    agent = await agents.create(OWNER, "Dot")
    thread = await threads.attach_session(agent.agent_id, SLACK_DM, "slack")
    await threads.append_turn(thread.agent_thread_id, SLACK_DM, "slack", "user", "launch is friday")
    await threads.append_turn(thread.agent_thread_id, SLACK_DM, "slack", "assistant", "noted")
    if attach_web:
        await threads.attach_session(agent.agent_id, web_session_id(CONVERSATION), "web")
    if status is not StandingAgentStatus.ACTIVE:
        await agents.update(OWNER, agent.agent_id, status=status)
    return agents, threads, agent, thread


async def _send(agents, threads, text: str, *, with_threads: bool = True):
    storage, llm = Storage(), RecordingLLM()
    pipeline = ChatStreamPipeline(
        chat_llm_service=llm,
        cost_calculator=SimpleNamespace(record_cost_for_existing_message=AsyncMock()),
        get_core_tools_fn=lambda: None,
        get_search_handler_fn=lambda: None,
        chat_service_cls=storage,
        multi_agent_workflow=object(),
        workflow_callback_cls=object(),
        map_node_to_agent_fn=lambda node: node,
        agent_threads=ChannelAgentThreads(agents, threads) if with_threads else None,
    )
    request = SimpleNamespace(
        role=SimpleNamespace(value="user"),
        content=text,
        attachments=[],
        parent_message_id=None,
        metadata={},
    )
    events = [
        event
        async for event in pipeline.run(
            conversation_id=CONVERSATION,
            request=request,
            current_user=SimpleNamespace(user_id=OWNER),
            authorized_conversation={
                "conversation_id": CONVERSATION,
                "user_id": OWNER,
                "model_name": "claude-sonnet-4-6",
                "system_prompt": "",
                "temperature": 0.7,
                "max_tokens": None,
            },
        )
    ]
    assert events[-1] == "data: [DONE]\n\n"
    return llm, storage


@pytest.mark.asyncio
async def test_the_model_sees_the_slack_turns_in_the_web_conversation(flags) -> None:
    agents, threads, _agent, thread = await _world()

    llm, _storage = await _send(agents, threads, "when is the launch?")

    assert [(m["role"], m["content"]) for m in llm.messages] == [
        ("user", "[slack] launch is friday"),
        ("assistant", "[slack] noted"),
        ("user", "when is the launch?"),
    ]
    turns = await thread_window(threads, thread.agent_thread_id, limit=10)
    assert [(t.channel_type, t.role, t.content) for t in turns][-2:] == [
        ("web", "user", "when is the launch?"),
        ("web", "assistant", "the launch is friday"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attach_web", "status", "with_threads"),
    [
        pytest.param(False, StandingAgentStatus.ACTIVE, True, id="ordinary-conversation"),
        pytest.param(True, StandingAgentStatus.PAUSED, True, id="paused-agent"),
        pytest.param(True, StandingAgentStatus.ACTIVE, False, id="not-wired"),
    ],
)
async def test_other_conversations_keep_their_own_history(
    flags, attach_web, status, with_threads
) -> None:
    agents, threads, _agent, thread = await _world(attach_web=attach_web, status=status)

    llm, _storage = await _send(agents, threads, "hello", with_threads=with_threads)

    assert [(m["role"], m["content"]) for m in llm.messages] == [("user", "hello")]
    assert len(await thread_window(threads, thread.agent_thread_id, limit=10)) == 2


@pytest.mark.asyncio
async def test_threads_flag_off_keeps_the_conversation_history(flags, monkeypatch) -> None:
    monkeypatch.setattr(flags.config.standing_agents.threads, "enabled", False)
    agents, threads, _agent, thread = await _world()

    llm, _storage = await _send(agents, threads, "hello")

    assert [(m["role"], m["content"]) for m in llm.messages] == [("user", "hello")]
    assert len(await thread_window(threads, thread.agent_thread_id, limit=10)) == 2

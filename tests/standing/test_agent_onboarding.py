"""Q13f: a standing agent introduces itself (design §8).

On creation it opens one background task; when that task **completes**, its
final answer becomes a STAGED memo. The task never writes the memo itself --
the background ceiling is READ_ONLY -- the platform moves the answer across.
The end-to-end tests drive a real `AnthropicCodingLoop` through
`CodingRunService`, so the completion hook is the production one's seat.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from neos.coding.application.run_service import CodingRunService, InProcessRunInterrupter
from neos.coding.application.task_service import (
    CodingTaskService,
    InMemoryCodingTaskRepository,
)
from neos.coding.domain.approvals import evaluate_approval
from neos.coding.domain.models import CodingTaskMode
from neos.coding.events.store import InMemoryCodingEventStore
from neos.coding.loop.anthropic import AnthropicCodingLoop, AnthropicLoopConfig
from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta, ToolCallCompleted
from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.bindings import SandboxBindingService
from neos.coding.sandbox.memory import MemorySandboxProvider
from neos.coding.tools.registry import CodingToolRegistry
from neos.learn.lessons import LessonStatus, reset_lesson_store
from neos.learn.policy import agent_namespace
from neos.standing.onboarding import (
    ONBOARDING_MEMO_TITLE,
    available_channels,
    final_answer,
    finish_onboarding,
    onboarding_prompt,
    skill_lines,
    start_onboarding,
)
from neos.standing.store import InMemoryStandingAgentStore
from neos.standing.tasks import open_agent_task
from tests.coding.conftest import CountingCrashExecutor
from tests.coding.fakes import (
    InMemoryCodingRunRepository,
    InMemorySandboxBindingRepository,
    ScriptedCodingModel,
)

pytestmark = pytest.mark.no_db

INTRO = "I am Dot. I can read your repositories and reach you on Slack."


@pytest.fixture(autouse=True)
def lessons():
    store = reset_lesson_store()
    yield store
    reset_lesson_store()


def _memos(lessons, agent):
    return lessons.list(agent_namespace(agent.agent_id))


# -- what the task is told -----------------------------------------------------


def _channels(principals=(), **enabled):
    return SimpleNamespace(
        principals=list(principals),
        **{
            name: SimpleNamespace(enabled=enabled.get(name, False))
            for name in ("telegram", "discord", "slack")
        },
    )


def test_only_enabled_channels_are_offered() -> None:
    assert available_channels("alice", _channels(slack=True, discord=False)) == ["slack"]


def test_with_principals_only_the_owners_platforms_are_offered() -> None:
    """Someone else's mapped channel is not introduced as this agent's."""
    principals = [
        SimpleNamespace(platform="slack", platform_user_id="U1", user_id="bob"),
        SimpleNamespace(platform="Telegram", platform_user_id="7", user_id="alice"),
    ]
    channels = _channels(principals, slack=True, telegram=True)

    assert available_channels("alice", channels) == ["telegram"]


def test_skill_lines_skip_what_the_model_may_not_invoke() -> None:
    skills = [
        SimpleNamespace(name="pdf", description="Read\n  PDFs", disable_model_invocation=False),
        SimpleNamespace(name="secret", description="x", disable_model_invocation=True),
    ]

    assert skill_lines(skills) == ["- pdf: Read PDFs"]


def test_skill_lines_are_capped() -> None:
    skills = [SimpleNamespace(name=f"s{i}", description="d") for i in range(100)]

    assert len(skill_lines(skills)) == 40


def test_the_prompt_names_the_agent_and_what_it_has() -> None:
    agent = SimpleNamespace(name="Dot")

    prompt = onboarding_prompt(agent, ["slack"], ["- pdf: Read PDFs"])
    empty = onboarding_prompt(agent, [], [])

    assert "You are Dot" in prompt and "slack" in prompt and "- pdf: Read PDFs" in prompt
    assert "(none connected yet)" in empty


# -- the final answer ------------------------------------------------------------


def test_the_final_answer_is_the_last_assistant_messages_text() -> None:
    state = {
        "transcript": [
            {"role": "assistant", "content": [{"type": "text", "text": "thinking aloud"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_call_id": "t"}]},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Hello."},
                    {"type": "tool_use", "tool_call_id": "t2", "name": "x", "input": {}},
                    {"type": "text", "text": "I am Dot."},
                ],
            },
            {"role": "user", "content": [{"type": "system_note", "text": "n"}]},
        ]
    }

    assert final_answer(state) == "Hello.\nI am Dot."
    assert final_answer(None) == ""
    assert final_answer({"transcript": []}) == ""


# -- the hook --------------------------------------------------------------------


async def _agent_with_intro(agents=None, coding=None):
    agents = agents or InMemoryStandingAgentStore()
    coding = coding or CodingTaskService(InMemoryCodingTaskRepository(), InMemoryCodingEventStore())
    agent = await agents.create("alice", "Dot")
    task = await start_onboarding(agents, coding, agent, channels=["slack"], skills=[])
    return agents, coding, agent, task


@pytest.mark.asyncio
async def test_the_self_introduction_is_a_background_agent_task_that_is_remembered() -> None:
    agents, _, agent, task = await _agent_with_intro()

    assert task.mode is CodingTaskMode.BACKGROUND
    assert task.agent_id == agent.agent_id
    assert (await agents.get_owned("alice", agent.agent_id)).onboarding_task_id == task.task_id


@pytest.mark.asyncio
async def test_a_completed_introduction_becomes_one_staged_memo(lessons) -> None:
    agents, _, agent, task = await _agent_with_intro()

    first = await finish_onboarding(agents, task, INTRO)
    again = await finish_onboarding(agents, task, INTRO)

    assert first is not None and again is None
    assert [(m.title, m.body, m.status) for m in _memos(lessons, agent)] == [
        (ONBOARDING_MEMO_TITLE, INTRO, LessonStatus.STAGED)
    ]


@pytest.mark.asyncio
async def test_another_agent_task_is_not_an_introduction(lessons) -> None:
    agents, coding, agent, _ = await _agent_with_intro()
    other = await open_agent_task(agents, coding, owner_id="alice", prompt="p")

    assert await finish_onboarding(agents, other, INTRO) is None
    assert _memos(lessons, agent) == ()


@pytest.mark.asyncio
async def test_a_person_task_is_ignored(lessons) -> None:
    agents, coding, agent, _ = await _agent_with_intro()
    human = await coding.create_task(owner_id="alice", prompt="p")

    assert await finish_onboarding(agents, human, INTRO) is None


@pytest.mark.asyncio
async def test_an_empty_answer_leaves_no_memo_and_does_not_spend_the_claim(lessons) -> None:
    agents, _, agent, task = await _agent_with_intro()

    assert await finish_onboarding(agents, task, "   ") is None
    assert await finish_onboarding(agents, task, INTRO) is not None


@pytest.mark.asyncio
async def test_an_imperative_answer_is_refused_quietly(lessons) -> None:
    """At most once: the claim is taken before the write, so a refused memo is
    not retried -- the introduction is a courtesy, not a duty."""
    agents, _, agent, task = await _agent_with_intro()

    assert await finish_onboarding(agents, task, "Always ask me first.") is None
    assert _memos(lessons, agent) == ()


# -- end to end: the real loop under the background ceiling ------------------


class _E2E:
    def __init__(self, tmp_path, script) -> None:
        self.tmp_path = tmp_path
        self.script = script
        self.now = SimpleNamespace(value=datetime(2026, 10, 1, tzinfo=UTC))

    async def start(self):
        self.agents = InMemoryStandingAgentStore()
        self.events = InMemoryCodingEventStore()
        self.tasks = InMemoryCodingTaskRepository()
        coding = CodingTaskService(self.tasks, self.events, clock=lambda: self.now.value)
        self.agent = await self.agents.create("alice", "Dot")
        task = await start_onboarding(self.agents, coding, self.agent, channels=[], skills=[])
        self.task_id = task.task_id
        self.provider = MemorySandboxProvider(root=self.tmp_path / "sandbox")
        self.repository = InMemoryCodingRunRepository(task_prompts={task.task_id: task.prompt})
        bindings = SandboxBindingService(
            repository=InMemorySandboxBindingRepository(self.repository),
            provider=self.provider,
            limits=SandboxLimits.safe_defaults(),
            snapshot_cadence=10,
            clock=lambda: self.now.value,
        )
        self.executor = CountingCrashExecutor()
        loop = AnthropicCodingLoop(
            model=ScriptedCodingModel(self.script),
            tools=CodingToolRegistry.default(command_allowlist=frozenset({"pytest"})),
            executor=self.executor,
            bindings=bindings,
            config=AnthropicLoopConfig(model="claude-test", system="code"),
            clock=lambda: self.now.value,
            approval_evaluator=evaluate_approval,
        )

        async def hook(task, loop_state):
            await finish_onboarding(self.agents, task, final_answer(loop_state))

        self.runs = CodingRunService(
            tasks=self.tasks,
            runs=self.repository,
            events=self.events,
            interrupter=InProcessRunInterrupter(),
            loop=loop,
            clock=lambda: self.now.value,
            on_completed=hook,
        )
        await self.runs.ensure_started(task_id=task.task_id)
        return self

    async def run_to_completion(self):
        for _ in range(20):
            event = await self.runs.advance_one_safe_point(
                task_id=self.task_id, worker_id="w1"
            )
            if event.type == "run.completed":
                return event
        raise AssertionError("did not complete")

    async def close(self):
        await self.provider.close()


@pytest.fixture
async def e2e(tmp_path):
    made = []

    async def make(script):
        made.append(await _E2E(tmp_path, script).start())
        return made[-1]

    yield make
    for item in made:
        await item.close()


def _end(text):
    return [TextDelta(text), ModelCompleted("end_turn", ModelUsage(2, 1))]


@pytest.mark.asyncio
async def test_the_introduction_runs_under_the_ceiling_and_its_answer_is_the_memo(
    e2e, lessons
) -> None:
    """The model tries to write; the background ceiling refuses it; the final
    answer still lands as the memo. Mutation: open the introduction as
    autonomous -> the write is not refused by the ceiling."""
    h = await e2e(
        [
            [
                ToolCallCompleted("w1", "write_file.v1", {"path": "intro.md", "content": "x"}),
                ModelCompleted("tool_use", ModelUsage(2, 1)),
            ],
            _end(INTRO),
        ]
    )

    await h.run_to_completion()

    assert h.executor.write_count == 0
    transcript = json.dumps(h.repository.checkpoints[-1].loop_state["transcript"])
    assert "policy_mode_ceiling" in transcript
    assert [(m.title, m.body, m.status) for m in _memos(lessons, h.agent)] == [
        (ONBOARDING_MEMO_TITLE, INTRO, LessonStatus.STAGED)
    ]


@pytest.mark.asyncio
async def test_a_failed_introduction_leaves_no_memo(e2e, lessons) -> None:
    """The model has already said its introduction when the run fails -- the
    checkpoint holds the text. Mutation: call the hook from `fail_active_run`
    -> that text becomes a memo."""
    h = await e2e(
        [
            [
                TextDelta(INTRO),
                ToolCallCompleted("w1", "write_file.v1", {"path": "a.md", "content": "x"}),
                ModelCompleted("tool_use", ModelUsage(2, 1)),
            ],
            _end("unreached"),
        ]
    )
    await h.runs.advance_one_safe_point(task_id=h.task_id, worker_id="w1")
    assert final_answer(h.repository.checkpoints[-1].loop_state) == INTRO

    await h.runs.fail_active_run(task_id=h.task_id, worker_id="w1", error_code="boom")

    assert _memos(lessons, h.agent) == ()


@pytest.mark.asyncio
async def test_a_failing_hook_does_not_fail_the_run(e2e) -> None:
    h = await e2e([_end(INTRO)])

    async def broken(task, loop_state):
        raise RuntimeError("memo store down")

    h.runs._on_completed = broken
    event = await h.run_to_completion()

    assert event.type == "run.completed"


def test_the_default_hook_is_the_standing_agent_one() -> None:
    """Both production `CodingRunService` constructions (API runtime and the
    celery worker) rely on the default -- neither passes `on_completed`."""
    from neos.coding.application import run_service

    service = run_service.CodingRunService(
        tasks=None, runs=None, events=None, interrupter=None
    )

    assert service._on_completed is run_service._standing_agent_completion


@pytest.fixture
def spy_finish(monkeypatch):
    calls = []

    async def finish(agents, task, answer):
        calls.append((type(agents).__name__, task.task_id, answer))

    monkeypatch.setattr("neos.standing.onboarding.finish_onboarding", finish)
    return calls


def _task(agent_id):
    return SimpleNamespace(task_id="ct_1", owner_id="alice", agent_id=agent_id)


_STATE = {"transcript": [{"role": "assistant", "content": [{"type": "text", "text": INTRO}]}]}


@pytest.mark.asyncio
@pytest.mark.parametrize(("enabled", "agent_id"), [(False, "sa_1"), (True, None)])
async def test_the_default_hook_does_nothing_when_off_or_for_a_person(
    monkeypatch, spy_finish, enabled, agent_id
) -> None:
    from neos.coding.application.run_service import _standing_agent_completion
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.standing_agents, "enabled", enabled)

    await _standing_agent_completion(_task(agent_id), _STATE)

    assert spy_finish == []


@pytest.mark.asyncio
async def test_the_default_hook_hands_the_final_answer_over_when_on(
    monkeypatch, spy_finish
) -> None:
    from neos.coding.application.run_service import _standing_agent_completion
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.standing_agents, "enabled", True)

    await _standing_agent_completion(_task("sa_1"), _STATE)

    assert spy_finish == [("PostgresStandingAgentStore", "ct_1", INTRO)]


class _CompletesItself:
    """A loop that announces `run.completed` itself -- the path the fake durable
    loop (the celery worker's) takes, as opposed to `complete_run`."""

    async def run(self, input, checkpoint, deps):
        yield await deps.events.append(
            task_id=input.task_id,
            event_type="run.completed",
            payload={"status": "completed"},
            run_id=input.run_id,
        )


@pytest.mark.asyncio
async def test_the_hook_also_runs_when_the_loop_announces_completion() -> None:
    tasks, events = InMemoryCodingTaskRepository(), InMemoryCodingEventStore()
    task = await CodingTaskService(tasks, events).create_task(owner_id="alice", prompt="p")
    seen = []

    async def hook(done, loop_state):
        seen.append(done.task_id)

    runs = CodingRunService(
        tasks=tasks,
        runs=InMemoryCodingRunRepository(task_prompts={task.task_id: "p"}),
        events=events,
        interrupter=InProcessRunInterrupter(),
        loop=_CompletesItself(),
        on_completed=hook,
    )
    await runs.ensure_started(task_id=task.task_id)

    event = await runs.advance_one_safe_point(task_id=task.task_id, worker_id="w1")

    assert event.type == "run.completed"
    assert seen == [task.task_id]

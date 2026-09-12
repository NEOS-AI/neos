from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from neos.coding.domain.durability import ExecutionLease
from neos.coding.domain.events import make_event
from neos.coding.domain.phases import CodingRun, CodingRunStatus
from neos.coding.loop.base import LoopDependencies, LoopInput
from neos.coding.loop.durable import CodingLoopConfig, DurableCodingLoop
from neos.coding.model.base import ModelCompleted, ModelUsage
from neos.coding.tools.executor import ToolResult
from neos.coding.tools.registry import CodingToolRegistry
from neos.learn.lessons import LessonStatus, new_lesson, reset_lesson_store
from tests.coding.fakes import InMemoryCodingRunRepository

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 7, 19, tzinfo=UTC)
LEASE = ExecutionLease("ct_1", "cr_1", "worker", 1, NOW, NOW + timedelta(minutes=1))


class Model:
    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        turn = self.turns.pop(0)
        for event in turn:
            yield event


class Events:
    def __init__(self):
        self.items = []

    async def append(self, *, task_id, event_type, payload, **ids):
        event = make_event(
            task_id=task_id,
            seq=100 + len(self.items),
            event_type=event_type,
            payload=payload,
            now=NOW,
            **ids,
        )
        self.items.append(event)
        return event


class Executor:
    async def execute(self, session, call, **kwargs):
        return ToolResult.ok(workspace_revision="1")


class Bindings:
    def __init__(self) -> None:
        self.session = SimpleNamespace(
            writes=0,
            files={},
            read_file=self._read_file,
        )

    async def resolve(self, lease):
        return SimpleNamespace(
            binding=SimpleNamespace(workspace_revision="1", provider="memory"),
            session=self.session,
        )

    async def record_mutation(self, lease, *, workspace_revision):
        return None

    async def _read_file(self, path: str) -> bytes:
        raise FileNotFoundError(path)


@dataclass
class Harness:
    loop: DurableCodingLoop
    model: Model
    deps: LoopDependencies


def harness() -> Harness:
    repository = InMemoryCodingRunRepository()
    repository.execution_leases["ct_1"] = LEASE
    run = CodingRun("cr_1", "ct_1", 1, CodingRunStatus.RUNNING, None, NOW)
    repository.active_run = run
    repository.created_runs = [run]
    repository.task_statuses["ct_1"] = "running"
    model = Model([[ModelCompleted("end_turn", ModelUsage(5, 3))]])
    loop = DurableCodingLoop(
        model=model,
        tools=CodingToolRegistry.default(command_allowlist=frozenset({"git"})),
        executor=Executor(),
        bindings=Bindings(),
        config=CodingLoopConfig(model="claude-test", system="static-system"),
        clock=lambda: NOW,
    )
    deps = LoopDependencies(
        repository=repository, events=Events(), lease=LEASE
    )
    return Harness(loop, model, deps)


def _approve(store, *, owner_id: str, body: str):
    lesson = store.add(
        new_lesson(namespace=f"owner:{owner_id}", title="t", body=body)
    )
    store.update(replace(lesson, status=LessonStatus.APPROVED))
    return lesson


async def _system_for(owner_id: str | None) -> str:
    h = harness()
    input = LoopInput("ct_1", "cr_1", "Fix it", owner_id=owner_id)
    _ = [event async for event in h.loop.run(input, None, h.deps)]
    return h.model.requests[0].system


@pytest.mark.asyncio
async def test_flag_on_approved_owner_injects_lessons_section(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    store = reset_lesson_store()
    body = "Owner-A unique lesson body 9a."
    _approve(store, owner_id="owner-a", body=body)

    system = await _system_for("owner-a")

    assert "## Lessons" in system
    assert body in system
    assert system.startswith("static-system")


@pytest.mark.asyncio
async def test_flag_on_staged_lesson_is_not_in_model_system(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    store = reset_lesson_store()
    body = "Staged lesson must stay out of the model system."
    store.add(new_lesson(namespace="owner:owner-a", title="t", body=body))

    system = await _system_for("owner-a")

    assert "## Lessons" not in system
    assert body not in system


@pytest.mark.asyncio
async def test_flag_on_without_owner_does_not_inject_lessons(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    store = reset_lesson_store()
    body = "Should not appear without owner_id."
    _approve(store, owner_id="owner-a", body=body)

    system = await _system_for(None)

    assert "## Lessons" not in system
    assert body not in system


@pytest.mark.asyncio
async def test_flag_off_does_not_inject_approved_lessons(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", False)
    store = reset_lesson_store()
    body = "Flag-off approved lesson stays out."
    _approve(store, owner_id="owner-a", body=body)

    system = await _system_for("owner-a")

    assert "## Lessons" not in system
    assert body not in system


@pytest.mark.asyncio
async def test_owner_lessons_are_isolated(monkeypatch) -> None:
    from neos.config.settings import settings

    monkeypatch.setattr(settings.config.learn, "coding_lessons", True)
    store = reset_lesson_store()
    body_a = "Only owner A should see this lesson."
    body_b = "Only owner B should see this lesson."
    _approve(store, owner_id="owner-a", body=body_a)
    _approve(store, owner_id="owner-b", body=body_b)

    system_a = await _system_for("owner-a")
    system_b = await _system_for("owner-b")

    assert body_a in system_a
    assert body_b not in system_a
    assert body_b in system_b
    assert body_a not in system_b

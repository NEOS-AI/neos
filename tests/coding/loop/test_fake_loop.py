from datetime import UTC, datetime

from neos.coding.domain.events import make_event
from neos.coding.domain.phases import CodingCheckpoint
from neos.coding.loop.base import LoopDependencies, LoopInput
from neos.coding.loop.fake import FakeDurableCodingLoop
from tests.coding.fakes import InMemoryCodingRunRepository


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
INPUT = LoopInput(task_id="ct_1", run_id="cr_1", instruction="Fix it")
CHECKPOINT_AFTER_PLAN = CodingCheckpoint(
    checkpoint_id="cc_plan",
    task_id="ct_1",
    run_id="cr_1",
    seq=6,
    loop_state={
        "phase_index": 1,
        "transcript": [],
        "pending_instruction": None,
    },
    workspace_revision="fake:plan:1",
    created_at=NOW,
)


class RecordingEventSink:
    def __init__(self) -> None:
        self.events = []

    async def append(
        self,
        *,
        task_id,
        event_type,
        payload,
        run_id=None,
        turn_id=None,
        tool_call_id=None,
        checkpoint_id=None,
    ):
        event = make_event(
            task_id=task_id,
            seq=len(self.events) + 1,
            event_type=event_type,
            payload=payload,
            now=NOW,
            run_id=run_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            checkpoint_id=checkpoint_id,
        )
        self.events.append(event)
        return event


def deps(repository):
    return LoopDependencies(repository=repository, events=RecordingEventSink())


async def test_fake_loop_runs_all_phases_and_checkpoints_each_step() -> None:
    repository = InMemoryCodingRunRepository()
    sink = RecordingEventSink()
    loop = FakeDurableCodingLoop(clock=lambda: NOW)

    events = [
        event
        async for event in loop.run(
            INPUT,
            checkpoint=None,
            deps=LoopDependencies(repository=repository, events=sink),
        )
    ]

    assert [
        event.payload["phase"]
        for event in events
        if event.type == "phase.started"
    ] == ["understand", "plan", "implement", "verify", "review"]
    assert len(repository.checkpoints) == 5
    assert len(repository.phases) == 5
    assert all(phase.status.value == "completed" for phase in repository.phases)
    assert events[-1].type == "run.completed"


async def test_completed_tool_is_not_reexecuted_after_resume() -> None:
    repository = InMemoryCodingRunRepository(
        completed_tools={"fake_implement_2": {"summary": "implement completed"}}
    )
    loop = FakeDurableCodingLoop(clock=lambda: NOW)

    events = [
        event
        async for event in loop.run(
            INPUT, CHECKPOINT_AFTER_PLAN, deps(repository)
        )
    ]

    assert all(
        call["tool_call_id"] != "fake_implement_2"
        for call in repository.tool_execution_calls
    )
    reused = [
        event
        for event in events
        if event.type == "tool.completed"
        and event.tool_call_id == "fake_implement_2"
    ]
    assert reused[0].payload["reused"] is True


async def test_checkpoint_identity_links_phase_completion_to_saved_state() -> None:
    repository = InMemoryCodingRunRepository()
    sink = RecordingEventSink()
    loop = FakeDurableCodingLoop(clock=lambda: NOW)

    events = [
        event
        async for event in loop.run(INPUT, None, LoopDependencies(repository, sink))
    ]

    completed = next(event for event in events if event.type == "phase.completed")
    checkpoint = repository.checkpoints[0]
    assert completed.checkpoint_id == checkpoint.checkpoint_id
    assert completed.seq == checkpoint.seq

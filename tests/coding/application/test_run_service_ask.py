"""Q9a around the loop: a waiting task is not "completed", does not continue, and
does not move until its question is answered (design §5.1).

Two places read the loop's outcome -- `CodingRunService` and `CodingTaskRunner`
(`is_pause_event` has the same two callers). Both are pinned here by name.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from neos.coding.domain.durability import TaskWaitingUser
from neos.coding.domain.models import CodingTaskStatus
from neos.coding.domain.phases import CodingRunStatus
from neos.coding.loop.durable import CodingLoopWaitingUser
from neos.coding.model.base import ToolCallCompleted
from neos.coding.tools.registry import CodingToolRegistry
from neos.coding.workers.execution import CodingTaskOutcome, CodingTaskRunner
from tests.coding.application.test_run_service import NOW, make_run_service, run_fixture
from tests.coding.fakes import InMemoryCodingRunRepository

pytestmark = pytest.mark.no_db

ASK = {"questions": ["Which branch?"]}


class AskingLoop:
    """What the durable loop does for an agent's autonomous `ask_user.v1`."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, input, checkpoint, deps):
        self.calls += 1
        commit = await deps.repository.request_user_answer(
            lease=deps.lease,
            tool_call=ToolCallCompleted("a1", "ask_user.v1", ASK),
            validated=CodingToolRegistry.default(command_allowlist=frozenset()).validate(
                "ask_user.v1", ASK
            ),
            loop_state={"pending_tool_index": 0},
            workspace_revision="rev",
            agent_id="sa_q9",
            reply_session_id=None,
            reply_channel_type="telegram",
            asked_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
        for event in commit.events:
            yield event


class StillWaitingLoop:
    async def run(self, input, checkpoint, deps):
        raise CodingLoopWaitingUser("spa_1")
        yield  # pragma: no cover


def _repository():
    repository = InMemoryCodingRunRepository(task_prompts={"ct_1": "Fix it"})
    run = run_fixture("cr_1")
    repository.active_run = run
    repository.created_runs = [run]
    repository.task_statuses["ct_1"] = "running"
    return repository


@pytest.mark.asyncio
async def test_a_question_is_handed_back_not_read_as_completion() -> None:
    repository = _repository()
    service = await make_run_service(repository, loop=AskingLoop())

    event = await service.advance_one_safe_point(task_id="ct_1", worker_id="w1")

    assert event.type == "question.asked"
    assert repository.active_run.status is CodingRunStatus.RUNNING
    assert repository.task_statuses["ct_1"] == "waiting_user"
    assert repository.execution_leases["ct_1"].expires_at <= NOW  # released


@pytest.mark.asyncio
async def test_the_runner_reports_waiting_user_and_does_not_continue() -> None:
    """Mutation: drop the `question.asked` branch in the runner -> CONTINUING,
    and the Celery task dispatches a continuation."""
    repository = _repository()
    service = await make_run_service(repository, loop=AskingLoop())
    seen = []

    async def lifecycle(task_id, status, payload):
        seen.append((task_id, status))

    runner = CodingTaskRunner(runs=service, advance_until_complete=False, on_lifecycle=lifecycle)
    outcome = await runner.run(task_id="ct_1", worker_id="w1", failure_error_code="x")

    assert outcome is CodingTaskOutcome.WAITING_USER
    assert seen == [("ct_1", "waiting_user")]


@pytest.mark.asyncio
async def test_a_waiting_task_does_not_move_even_with_a_lease() -> None:
    """Mutation: drop the `TaskWaitingUser` guard -> a stray continuation runs the loop."""
    repository = _repository()
    loop = AskingLoop()
    service = await make_run_service(repository, loop=loop)
    task = await service._tasks.get("ct_1")
    await service._tasks.save(replace(task, status=CodingTaskStatus.WAITING_USER))

    with pytest.raises(TaskWaitingUser):
        await service.advance_one_safe_point(task_id="ct_1", worker_id="w1")

    assert loop.calls == 0
    assert repository.execution_leases["ct_1"].expires_at <= NOW  # released
    runner = CodingTaskRunner(runs=service, advance_until_complete=True)
    assert (
        await runner.run(task_id="ct_1", worker_id="w2", failure_error_code="x")
        is CodingTaskOutcome.WAITING_USER
    )


@pytest.mark.asyncio
async def test_a_loop_that_finds_its_question_unanswered_is_waiting_not_failed() -> None:
    """Mutation: drop `CodingLoopWaitingUser` from the runner -> retried, then failed."""
    repository = _repository()
    service = await make_run_service(repository, loop=StillWaitingLoop())
    runner = CodingTaskRunner(runs=service, advance_until_complete=True)

    outcome = await runner.run(task_id="ct_1", worker_id="w1", failure_error_code="x")

    assert outcome is CodingTaskOutcome.WAITING_USER
    assert repository.active_run.status is CodingRunStatus.RUNNING

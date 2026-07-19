from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import datetime, timedelta

from neos.coding.domain.events import CodingEvent
from neos.coding.domain.durability import ToolExecutionDisposition
from neos.coding.domain.phases import (
    CodingCheckpoint,
    CodingPhaseKind,
    CodingPhaseStatus,
    next_phase_attempt,
)
from neos.coding.loop.base import LoopDependencies, LoopInput


PHASES = (
    CodingPhaseKind.UNDERSTAND,
    CodingPhaseKind.PLAN,
    CodingPhaseKind.IMPLEMENT,
    CodingPhaseKind.VERIFY,
    CodingPhaseKind.REVIEW,
)


class FakeDurableCodingLoop:
    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    async def run(
        self,
        input: LoopInput,
        checkpoint: CodingCheckpoint | None,
        deps: LoopDependencies,
    ) -> AsyncIterator[CodingEvent]:
        if deps.lease is not None:
            async for event in self._run_durable(input, checkpoint, deps):
                yield event
            return
        start_index = (
            int(checkpoint.loop_state["phase_index"]) + 1 if checkpoint else 0
        )
        transcript = (
            list(checkpoint.loop_state.get("transcript", []))
            if checkpoint
            else []
        )

        for index, phase in enumerate(PHASES[start_index:], start=start_index):
            phase_record = next_phase_attempt(
                task_id=input.task_id,
                run_id=input.run_id,
                kind=phase,
                existing=await deps.repository.phase_history(input.task_id),
                now=self._clock(),
            )
            await deps.repository.save_phase(phase_record)
            yield await deps.events.append(
                task_id=input.task_id,
                event_type="phase.started",
                payload={
                    "phase": phase.value,
                    "attempt": phase_record.attempt,
                    "index": index,
                },
                run_id=input.run_id,
            )

            tool_call_id = f"fake_{phase.value}_{index}"
            persisted = await deps.repository.completed_tool_result(
                input.task_id, tool_call_id
            )
            reused = persisted is not None
            if persisted is None:
                persisted = {"summary": f"{phase.value} completed"}
                await deps.repository.record_tool_result(
                    task_id=input.task_id,
                    run_id=input.run_id,
                    tool_call_id=tool_call_id,
                    result=persisted,
                    completed_at=self._clock(),
                )
            yield await deps.events.append(
                task_id=input.task_id,
                event_type="tool.completed",
                payload={"result": dict(persisted), "reused": reused},
                run_id=input.run_id,
                tool_call_id=tool_call_id,
            )

            checkpoint_id = f"cc_{input.run_id}_{index}"
            transcript.append(
                {"phase": phase.value, "summary": persisted["summary"]}
            )
            completed = await deps.events.append(
                task_id=input.task_id,
                event_type="phase.completed",
                payload={
                    "phase": phase.value,
                    "attempt": phase_record.attempt,
                    **persisted,
                },
                run_id=input.run_id,
                tool_call_id=tool_call_id,
                checkpoint_id=checkpoint_id,
            )
            await deps.repository.save_checkpoint(
                CodingCheckpoint(
                    checkpoint_id=checkpoint_id,
                    task_id=input.task_id,
                    run_id=input.run_id,
                    seq=completed.seq,
                    loop_state={
                        "phase_index": index,
                        "transcript": list(transcript),
                        "pending_instruction": None,
                    },
                    workspace_revision=f"fake:{phase.value}:{index}",
                    created_at=self._clock(),
                )
            )
            await deps.repository.save_phase(
                replace(
                    phase_record,
                    status=CodingPhaseStatus.COMPLETED,
                    completed_at=self._clock(),
                )
            )
            yield completed

        yield await deps.events.append(
            task_id=input.task_id,
            event_type="run.completed",
            payload={"status": "completed"},
            run_id=input.run_id,
        )

    async def _run_durable(
        self,
        input: LoopInput,
        checkpoint: CodingCheckpoint | None,
        deps: LoopDependencies,
    ) -> AsyncIterator[CodingEvent]:
        lease = deps.lease
        assert lease is not None
        start_index = (
            int(checkpoint.loop_state["phase_index"]) + 1
            if checkpoint
            else 0
        )
        transcript = (
            list(checkpoint.loop_state.get("transcript", []))
            if checkpoint
            else []
        )
        current_instruction = (
            str(checkpoint.loop_state["current_instruction"])
            if checkpoint
            else input.instruction
        )

        for index, phase_kind in enumerate(
            PHASES[start_index:], start=start_index
        ):
            started = await deps.repository.begin_phase(
                lease=lease, kind=phase_kind, now=self._clock()
            )
            phase = started.phase
            if started.event is not None:
                yield started.event

            tool_call_id = f"fake_{phase_kind.value}_{index}"
            claim = await deps.repository.claim_tool_execution(
                lease=lease,
                tool_call_id=tool_call_id,
                now=self._clock(),
                claim_expires_at=self._clock() + timedelta(seconds=30),
            )
            if claim.disposition is ToolExecutionDisposition.BUSY:
                raise RuntimeError(f"tool execution is busy: {tool_call_id}")
            if claim.disposition is ToolExecutionDisposition.COMPLETED:
                persisted = dict(claim.result or {})
                yield await deps.events.append(
                    task_id=input.task_id,
                    event_type="tool.completed",
                    payload={"result": persisted, "reused": True},
                    run_id=input.run_id,
                    tool_call_id=tool_call_id,
                )
            else:
                persisted = {"summary": f"{phase_kind.value} completed"}
                yield await deps.repository.complete_tool_execution(
                    claim, result=persisted, now=self._clock()
                )

            transcript.append(
                {"phase": phase_kind.value, "summary": persisted["summary"]}
            )
            committed = await deps.repository.commit_phase_checkpoint(
                lease=lease,
                phase=phase,
                tool_call_id=tool_call_id,
                result=persisted,
                loop_state={
                    "phase_index": index,
                    "transcript": list(transcript),
                    "current_instruction": current_instruction,
                    "pending_instruction": None,
                },
                workspace_revision=f"fake:{phase_kind.value}:{index}",
                now=self._clock(),
            )
            yield committed.event

        yield await deps.events.append(
            task_id=input.task_id,
            event_type="run.completed",
            payload={"status": "completed"},
            run_id=input.run_id,
        )

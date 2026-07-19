from collections.abc import AsyncIterator, Callable
from datetime import datetime

from neos.coding.domain.events import CodingEvent
from neos.coding.domain.phases import CodingCheckpoint, CodingPhaseKind
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
        start_index = (
            int(checkpoint.loop_state["phase_index"]) + 1 if checkpoint else 0
        )
        transcript = (
            list(checkpoint.loop_state.get("transcript", []))
            if checkpoint
            else []
        )

        for index, phase in enumerate(PHASES[start_index:], start=start_index):
            yield await deps.events.append(
                task_id=input.task_id,
                event_type="phase.started",
                payload={"phase": phase.value, "attempt": 1, "index": index},
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
                payload={"phase": phase.value, "attempt": 1, **persisted},
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
            yield completed

        yield await deps.events.append(
            task_id=input.task_id,
            event_type="run.completed",
            payload={"status": "completed"},
            run_id=input.run_id,
        )

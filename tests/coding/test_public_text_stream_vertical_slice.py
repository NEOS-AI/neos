from datetime import timedelta

import pytest

from neos.coding.application.snapshot_service import CodingSnapshotService
from neos.coding.domain.text_parts import TextPartStatus
from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta, ToolInputDelta
from neos.coding.repositories.projection_repository import (
    CodingProjectionRows,
    CodingRunRow,
    CodingTaskRow,
    CodingTextPartRow,
)
from tests.coding.fakes import text_turn

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_public_text_survives_replacement_snapshot_without_tool_json(
    real_loop_harness,
) -> None:
    harness = await real_loop_harness(
        script=[
            (
                ToolInputDelta("tool_1", "write_file.v1", '{"content":"private"}'),
                TextDelta("partial"),
                ModelCompleted("end_turn", ModelUsage(1, 1)),
            ),
            text_turn("done"),
        ],
        crash_after="append_model_text_delta",
    )
    with pytest.raises(RuntimeError, match="injected crash"):
        await harness.advance(worker_id="worker-1")
    harness.elapse(timedelta(seconds=31))
    harness.disable_crash()
    await harness.advance_until_complete(worker_id="worker-2")

    durable_parts = sorted(
        harness.repository.text_parts.values(), key=lambda part: part.first_seq
    )
    assert [part.status for part in durable_parts] == [
        TextPartStatus.INTERRUPTED,
        TextPartStatus.COMPLETED,
    ]

    class ProjectionRepository:
        async def get_owned_snapshot(self, task_id, owner_id):
            if owner_id != "u1":
                return None
            return CodingProjectionRows(
                task=CodingTaskRow(task_id, "completed", 1, 99, harness.now.value, harness.now.value),
                runs=(CodingRunRow(durable_parts[-1].run_id, 1, "completed", None),),
                phases=(),
                tools=(),
                approvals=(),
                parts=tuple(
                    CodingTextPartRow(
                        part.part_id,
                        part.run_id,
                        part.turn_id,
                        part.status.value,
                        part.content,
                        part.first_seq,
                        part.last_seq,
                    )
                    for part in durable_parts
                ),
                workspace_edits=(),
                todos=(),
                latest_checkpoint=None,
                head_seq=99,
            )

    snapshot = await CodingSnapshotService(ProjectionRepository()).get_owned(
        "ct_real", "u1"
    )
    assert snapshot is not None
    assert [part.content for part in snapshot.parts] == ["partial", "done"]
    assert "private" not in repr(snapshot)
    tool_events = [
        event
        for event in await harness.events.list_after("ct_real")
        if event.type == "model.tool_input_delta"
    ]
    assert tool_events and tool_events[0].payload == {
        "tool_call_id": "tool_1",
        "bytes": len('{"content":"private"}'.encode()),
    }

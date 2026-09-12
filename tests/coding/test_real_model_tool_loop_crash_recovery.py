from datetime import timedelta

import pytest

from neos.coding.domain.durability import StaleExecutionLease
from neos.coding.domain.text_parts import TextPartStatus
from tests.coding.fakes import RecordingCodingAuditSink, text_turn, tool_turn

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_crash_after_write_has_unknown_outcome_without_second_write(
    real_loop_harness,
) -> None:
    harness = await real_loop_harness(
        script=[
            tool_turn(
                "read_file.v1",
                {"path": "calc.py"},
                tool_call_id="tool_read",
            ),
            tool_turn(
                "write_file.v1",
                {"path": "calc.py", "content": "changed\n"},
                tool_call_id="tool_1",
            ),
            # A replacement model turn deterministically proposes the same call id.
            tool_turn(
                "write_file.v1",
                {"path": "calc.py", "content": "changed\n"},
                tool_call_id="tool_1",
            ),
        ],
        crash_after="write_file",
    )

    await harness.advance(worker_id="worker-1")
    await harness.advance(worker_id="worker-1")
    await harness.advance(worker_id="worker-1")
    await harness.advance(worker_id="worker-1")
    harness.elapse(timedelta(seconds=31))
    await harness.advance(worker_id="worker-2")

    assert await harness.session.read_file("calc.py") == b"changed\n"
    assert harness.write_count == 1
    transcript = harness.repository.checkpoints[-1].loop_state["transcript"]
    results = [
        item
        for message in transcript
        for item in message["content"]
        if item.get("type") == "tool_result" and item.get("tool_call_id") == "tool_1"
    ]
    assert results
    assert results[-1]["status"] == "error"
    assert results[-1]["content"]["reason_code"] == "tool_outcome_unknown"


@pytest.mark.asyncio
async def test_crash_after_durable_tool_completion_reuses_result(
    real_loop_harness,
) -> None:
    audit = RecordingCodingAuditSink()
    harness = await real_loop_harness(
        script=[
            tool_turn(
                "read_file.v1",
                {"path": "calc.py"},
                tool_call_id="tool_read",
            ),
            tool_turn(
                "write_file.v1",
                {"path": "calc.py", "content": "changed\n"},
                tool_call_id="tool_1",
            ),
            tool_turn(
                "write_file.v1",
                {"path": "calc.py", "content": "changed\n"},
                tool_call_id="tool_1",
            ),
            text_turn("done"),
        ],
        crash_after="complete_tool_execution",
        audit=audit,
    )

    harness.repository.crash_after = None
    await harness.advance(worker_id="worker-1")
    harness.repository.crash_after = "complete_tool_execution"
    await harness.advance(worker_id="worker-1")
    harness.elapse(timedelta(seconds=31))
    harness.disable_crash()
    await harness.advance_until_complete(worker_id="worker-2")

    assert harness.write_count == 1
    assert harness.completed_tool_ids == {"tool_read", "tool_1"}
    assert any(event["outcome"] == "reused" for event in audit.events)


@pytest.mark.asyncio
async def test_crash_after_durable_text_delta_interrupts_part_on_replacement(
    real_loop_harness,
) -> None:
    harness = await real_loop_harness(
        script=[text_turn("partial"), text_turn("done")],
        crash_after="append_model_text_delta",
    )

    with pytest.raises(RuntimeError, match="injected crash"):
        await harness.advance(worker_id="worker-1")
    harness.elapse(timedelta(seconds=31))
    harness.disable_crash()
    await harness.advance_until_complete(worker_id="worker-2")

    parts = sorted(
        harness.repository.text_parts.values(), key=lambda part: part.first_seq
    )
    assert [part.status for part in parts] == [
        TextPartStatus.INTERRUPTED,
        TextPartStatus.COMPLETED,
    ]
    assert [part.content for part in parts] == ["partial", "done"]
    assert parts[0].last_seq == parts[1].first_seq


@pytest.mark.asyncio
async def test_stale_fencing_token_cannot_commit_results_or_checkpoints_or_binding(
    real_loop_harness,
) -> None:
    harness = await real_loop_harness(script=[])
    old, current, claim, phase = await harness.replacement_lease()

    with pytest.raises(StaleExecutionLease):
        await harness.repository.complete_tool_execution(
            claim, result={"status": "ok"}, now=harness.now
        )
    with pytest.raises(StaleExecutionLease):
        await harness.commit_checkpoint(old, phase)
    with pytest.raises(StaleExecutionLease):
        await harness.bindings.record_mutation(old, workspace_revision=9)
    updated = await harness.bindings.record_mutation(current, workspace_revision=9)
    assert updated.workspace_revision == "9"

import json

import pytest

from tests.coding.fakes import (
    RecordingCodingAuditSink,
    RecordingCodingLoopMetrics,
    text_turn,
    tool_turn,
)

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_model_reads_edits_tests_and_finishes_across_safe_points(
    real_loop_harness,
) -> None:
    metrics = RecordingCodingLoopMetrics()
    audit = RecordingCodingAuditSink()
    harness = await real_loop_harness(
        script=[
            tool_turn("read_file.v1", {"path": "calc.py"}, tool_call_id="tool_1"),
            tool_turn(
                "write_file.v1",
                {"path": "calc.py", "content": "def add(a, b): return a + b\n"},
                tool_call_id="tool_2",
            ),
            tool_turn(
                "execute.v1", {"argv": ["pytest", "-q"]}, tool_call_id="tool_3"
            ),
            text_turn("Implemented and verified add()."),
        ],
        metrics=metrics,
        audit=audit,
    )

    await harness.advance_until_complete()

    assert await harness.session.read_file("calc.py") == (
        b"def add(a, b): return a + b\n"
    )
    assert harness.completed_tool_ids == {"tool_1", "tool_2", "tool_3"}
    assert harness.final_text == "Implemented and verified add()."
    assert (
        "coding_model_turn_total",
        {"provider": "anthropic", "outcome": "tool_use"},
    ) in metrics.records
    assert (
        "coding_tool_execution_total",
        {"tool": "write_file.v1", "outcome": "ok"},
    ) in metrics.records
    serialized = json.dumps(audit.events)
    assert "secret" not in serialized
    assert "file contents" not in serialized
    assert any(
        event["tool"] == "write_file.v1"
        and event["operation"] == "execute"
        and event["outcome"] == "ok"
        for event in audit.events
    )


@pytest.mark.asyncio
async def test_checkpointed_read_allows_write_on_a_new_executor(
    real_loop_harness,
) -> None:
    from neos.coding.tools.executor import SandboxToolExecutor

    harness = await real_loop_harness(
        script=[
            tool_turn("read_file.v1", {"path": "calc.py"}, tool_call_id="tool_1"),
            tool_turn(
                "write_file.v1",
                {"path": "calc.py", "content": "def add(a, b): return a + b\n"},
                tool_call_id="tool_2",
            ),
            text_turn("done"),
        ]
    )

    await harness.advance()
    harness.executor.delegate = SandboxToolExecutor(
        max_preview_bytes=64_000, max_entries=100
    )
    await harness.advance_until_complete()

    assert await harness.session.read_file("calc.py") == (
        b"def add(a, b): return a + b\n"
    )

from neos.workflow.harness.trace import TraceEvent, compact_trace_event, trace_event


def test_trace_event_serializes_stable_shape():
    event = trace_event(
        event_type="harness.check.completed",
        run_id="run-1",
        node_id="research_harness",
        data={"check": "source_count", "passed": True},
    )

    assert event.event_type == "harness.check.completed"
    assert event.run_id == "run-1"
    assert event.node_id == "research_harness"
    assert event.data["check"] == "source_count"
    assert event.sequence >= 0


def test_compact_trace_redacts_large_text():
    event = TraceEvent(
        sequence=1,
        event_type="artifact.candidate",
        run_id="run-1",
        node_id="node-1",
        data={"text": "x" * 1000, "score": 0.9},
    )

    compact = compact_trace_event(event, max_text_length=20)

    assert compact["data"]["text"] == "xxxxxxxxxxxxxxxxxxxx"
    assert compact["data"]["score"] == 0.9

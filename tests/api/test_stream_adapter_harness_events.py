import json

from neos.api.adapters.stream_adapter import StreamAdapterState, adapt_legacy_event


def test_adapts_harness_node_progress_to_neos_harness_event():
    events = adapt_legacy_event(
        {
            "type": "workflow_progress",
            "node_name": "research_harness",
            "progress_percent": 50,
            "metadata": {
                "message": json.dumps(
                    {
                        "event": "harness_check_completed",
                        "run_id": "run-1",
                        "data": {
                            "check": "source_count",
                            "passed": False,
                            "score": 0.2,
                        },
                    }
                )
            },
        },
        StreamAdapterState(),
    )

    assert len(events) == 1
    event = events[0]
    assert event.type == "neos:harness"
    assert event.event == "harness_check_completed"
    assert event.run_id == "run-1"
    assert event.data["check"] == "source_count"

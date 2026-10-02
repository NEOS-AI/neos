import pytest

from neos.coding.workers.dispatcher import (
    EXECUTE_CODING_TASK,
    CeleryCodingTaskDispatcher,
    CodingDispatchSource,
)

pytestmark = pytest.mark.no_db


class RecordingCeleryApp:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, list[str], str]] = []

    def send_task(self, name, *, args, queue):
        self.calls.append((name, args, queue))
        if self.error is not None:
            raise self.error
        return type("Result", (), {"id": "delivery-1"})()


class RecordingMetric:
    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []
        self._labels: dict[str, str] = {}

    def labels(self, **labels):
        bound = RecordingMetric()
        bound.records = self.records
        bound._labels = labels
        return bound

    def inc(self) -> None:
        self.records.append(self._labels)


class RecordingMetrics:
    def __init__(self) -> None:
        self.coding_dispatch_total = RecordingMetric()


def test_dispatcher_publishes_only_task_identity_to_coding_queue() -> None:
    app = RecordingCeleryApp()
    dispatcher = CeleryCodingTaskDispatcher(app=app, queue="coding")

    delivery_id = dispatcher.enqueue(
        "ct_1", expected_checkpoint_id=None, source=CodingDispatchSource.API
    )

    assert delivery_id == "delivery-1"
    assert app.calls == [(EXECUTE_CODING_TASK, ["ct_1", None], "coding")]


def test_dispatch_source_is_a_bounded_enum() -> None:
    assert {item.value for item in CodingDispatchSource} == {
        "api",
        "approval",
        "reconciliation",
        "continuation",
        "resume",  # Q10b -- a person resumed a paused task
    }


def test_dispatch_failure_records_only_bounded_labels() -> None:
    app = RecordingCeleryApp(error=ConnectionError("broker down"))
    metrics = RecordingMetrics()
    dispatcher = CeleryCodingTaskDispatcher(app=app, queue="coding", metrics=metrics)

    with pytest.raises(ConnectionError, match="broker down"):
        dispatcher.enqueue(
            "ct_secret",
            expected_checkpoint_id=None,
            source=CodingDispatchSource.API,
        )

    assert metrics.coding_dispatch_total.records == [
        {"source": "api", "outcome": "failed"}
    ]


def test_dispatcher_rejects_empty_queue() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        CeleryCodingTaskDispatcher(app=RecordingCeleryApp(), queue="  ")

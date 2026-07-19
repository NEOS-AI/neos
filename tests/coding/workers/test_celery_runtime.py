import pytest

from neos.coding.workers import celery_runtime
from neos.coding.workers.execution import CodingTaskOutcome, CodingTaskRunner


class RecordingDatabaseManager:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def initialize(self) -> None:
        self.calls.append("initialize")

    async def close(self) -> None:
        self.calls.append("close")

    async def get_session(self):
        raise AssertionError("factory construction must not open a session")


class RecordingRunner:
    def __init__(self, outcome: CodingTaskOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[str, str, str]] = []

    async def run(
        self,
        *,
        task_id: str,
        worker_id: str,
        failure_error_code: str,
    ) -> CodingTaskOutcome:
        self.calls.append((task_id, worker_id, failure_error_code))
        return self.outcome


class RecordingDiscoveryRepository:
    def __init__(self, result=(), error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.limits: list[int] = []

    async def claimable_task_ids(self, *, limit: int):
        self.limits.append(limit)
        if self.error is not None:
            raise self.error
        return self.result


async def test_delivery_initializes_and_closes_its_database_manager(
    monkeypatch,
) -> None:
    manager = RecordingDatabaseManager()
    runner = RecordingRunner(CodingTaskOutcome.COMPLETED)
    monkeypatch.setattr(
        celery_runtime, "_build_runner", lambda manager: runner
    )

    outcome = await celery_runtime.run_coding_delivery(
        task_id="ct_1",
        worker_id="celery-1",
        database_manager=manager,
    )

    assert outcome is CodingTaskOutcome.COMPLETED
    assert manager.calls == ["initialize", "close"]
    assert runner.calls == [
        ("ct_1", "celery-1", "worker_retry_exhausted")
    ]


def test_build_runner_returns_shared_execution_runner() -> None:
    runner = celery_runtime._build_runner(RecordingDatabaseManager())

    assert isinstance(runner, CodingTaskRunner)


async def test_discovery_returns_bounded_ids_and_closes_manager(
    monkeypatch,
) -> None:
    manager = RecordingDatabaseManager()
    repository = RecordingDiscoveryRepository(("ct_1", "ct_2"))
    monkeypatch.setattr(
        celery_runtime,
        "_build_run_repository",
        lambda manager: repository,
    )

    task_ids = await celery_runtime.discover_coding_tasks(
        limit=2, database_manager=manager
    )

    assert task_ids == ("ct_1", "ct_2")
    assert repository.limits == [2]
    assert manager.calls == ["initialize", "close"]


async def test_discovery_closes_manager_when_repository_raises(
    monkeypatch,
) -> None:
    manager = RecordingDatabaseManager()
    repository = RecordingDiscoveryRepository(
        error=ConnectionError("database unavailable")
    )
    monkeypatch.setattr(
        celery_runtime,
        "_build_run_repository",
        lambda manager: repository,
    )

    with pytest.raises(ConnectionError, match="database unavailable"):
        await celery_runtime.discover_coding_tasks(
            limit=100, database_manager=manager
        )

    assert manager.calls == ["initialize", "close"]

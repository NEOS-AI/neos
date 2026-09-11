import pytest

from neos.coding.workers import celery_runtime
from neos.coding.workers.execution import CodingTaskOutcome, CodingTaskRunner
from neos.config.schema import AppConfig


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
        expected_checkpoint_id: str | None,
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

    async def claimable_delivery_tokens(self, *, limit: int):
        self.limits.append(limit)
        if self.error is not None:
            raise self.error
        return self.result


async def test_expiry_reconciliation_owns_database_manager(monkeypatch) -> None:
    manager = RecordingDatabaseManager()

    class Service:
        async def expire_pending(self, *, limit):
            assert limit == 17
            return (object(), object())

    monkeypatch.setattr(
        celery_runtime, "_build_approval_service", lambda manager: Service()
    )
    count = await celery_runtime.expire_coding_approvals(
        limit=17, database_manager=manager
    )
    assert count == 2
    assert manager.calls == ["initialize", "close"]


async def test_delivery_binds_lesson_store_to_worker_database(
    monkeypatch,
) -> None:
    from neos.learn.lessons import reset_lesson_store, resolve_lesson_session_factory

    reset_lesson_store()
    manager = RecordingDatabaseManager()
    bound: list[object] = []

    class BindingRunner(RecordingRunner):
        async def run(self, **kwargs):
            bound.append(resolve_lesson_session_factory())
            return await super().run(**kwargs)

    runner = BindingRunner(CodingTaskOutcome.COMPLETED)
    monkeypatch.setattr(celery_runtime, "_build_runner", lambda manager: runner)

    await celery_runtime.run_coding_delivery(
        task_id="ct_1",
        worker_id="celery-1",
        expected_checkpoint_id=None,
        database_manager=manager,
    )

    assert bound == [manager.get_session]
    assert resolve_lesson_session_factory() is None


async def test_delivery_initializes_and_closes_its_database_manager(
    monkeypatch,
) -> None:
    manager = RecordingDatabaseManager()
    runner = RecordingRunner(CodingTaskOutcome.COMPLETED)
    monkeypatch.setattr(celery_runtime, "_build_runner", lambda manager: runner)

    outcome = await celery_runtime.run_coding_delivery(
        task_id="ct_1",
        worker_id="celery-1",
        expected_checkpoint_id=None,
        database_manager=manager,
    )

    assert outcome is CodingTaskOutcome.COMPLETED
    assert manager.calls == ["initialize", "close"]
    assert runner.calls == [("ct_1", "celery-1", "worker_retry_exhausted")]


def test_build_runner_returns_shared_execution_runner() -> None:
    runner = celery_runtime._build_runner(RecordingDatabaseManager())

    assert isinstance(runner, CodingTaskRunner)


async def test_discovery_returns_bounded_ids_and_closes_manager(
    monkeypatch,
) -> None:
    manager = RecordingDatabaseManager()
    repository = RecordingDiscoveryRepository((("ct_1", None), ("ct_2", "cc_2")))
    monkeypatch.setattr(
        celery_runtime,
        "_build_run_repository",
        lambda manager: repository,
    )

    task_ids = await celery_runtime.discover_coding_tasks(
        limit=2, database_manager=manager
    )

    assert task_ids == (("ct_1", None), ("ct_2", "cc_2"))
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
        await celery_runtime.discover_coding_tasks(limit=100, database_manager=manager)

    assert manager.calls == ["initialize", "close"]


async def test_real_worker_closes_provider_once_when_loop_construction_fails(
    monkeypatch,
) -> None:
    manager = RecordingDatabaseManager()
    provider = type(
        "Provider", (), {"close_count": 0, "close": lambda self: _close(self)}
    )()
    config = AppConfig.model_validate(
        {
            "coding_model": {
                "enabled": True,
                "input_cost_micros_per_million": 1,
                "output_cost_micros_per_million": 1,
            },
            "sandbox": {"enabled": True},
            "secrets": {"anthropic_api_key": "test"},
        }
    )
    monkeypatch.setattr(celery_runtime.settings, "_config", config)
    monkeypatch.setattr(
        "neos.coding.sandbox.factory.create_sandbox_provider", lambda config: provider
    )
    monkeypatch.setattr(
        celery_runtime,
        "_create_worker_real_loop",
        lambda manager, provider: (_ for _ in ()).throw(RuntimeError("loop failed")),
    )

    with pytest.raises(RuntimeError, match="loop failed"):
        await celery_runtime.run_coding_delivery(
            task_id="ct_1",
            worker_id="worker",
            database_manager=manager,
            expected_checkpoint_id=None,
        )

    assert provider.close_count == 1


async def _close(provider) -> None:
    provider.close_count += 1

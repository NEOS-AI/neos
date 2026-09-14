import pytest

from neos.coding.workers import celery_runtime
from neos.coding.workers.execution import CodingTaskOutcome, CodingTaskRunner
from neos.config.schema import AppConfig

pytestmark = pytest.mark.no_db


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
    _pin_fake_loop_path(monkeypatch)
    monkeypatch.setattr(celery_runtime, "_build_runner", lambda manager: runner)

    await celery_runtime.run_coding_delivery(
        task_id="ct_1",
        worker_id="celery-1",
        expected_checkpoint_id=None,
        database_manager=manager,
    )

    assert bound == [manager.get_session]
    assert resolve_lesson_session_factory() is None


def _pin_fake_loop_path(monkeypatch) -> None:
    """These tests drive the `_build_runner` (fake loop) branch.

    The development profile enables the real coding loop, which would route
    the delivery to the real-loop branch instead of the patched runner.
    """
    monkeypatch.setattr(
        celery_runtime.settings.config.coding_model, "enabled", False
    )


async def test_delivery_initializes_and_closes_its_database_manager(
    monkeypatch,
) -> None:
    manager = RecordingDatabaseManager()
    runner = RecordingRunner(CodingTaskOutcome.COMPLETED)
    _pin_fake_loop_path(monkeypatch)
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
    assert runner._on_lifecycle is not None


async def test_lifecycle_callback_calls_push_bound_lifecycle(monkeypatch) -> None:
    seen: list[dict] = []

    async def fake_push(**kwargs):
        seen.append(kwargs)
        return "ok"

    monkeypatch.setattr(celery_runtime, "push_bound_lifecycle", fake_push)

    async def get_binding(task_id: str):
        del task_id
        return None

    sink = object()
    callback = celery_runtime._lifecycle_callback(get_binding=get_binding, sink=sink)
    await callback(
        "ct_1",
        "waiting_approval",
        {"approval_id": "ca_9", "tool_name": "write_file.v1"},
    )

    assert len(seen) == 1
    assert seen[0]["get_binding"] is get_binding
    assert seen[0]["sink"] is sink
    assert seen[0]["task_id"] == "ct_1"
    assert seen[0]["status"] == "waiting_approval"
    assert seen[0]["approval_id"] == "ca_9"
    assert seen[0]["tool_name"] == "write_file.v1"


async def test_lifecycle_callback_pushes_bound_card_and_skips_housekeeping() -> None:
    from neos.api.channels.session_bind import InMemoryChannelCodingBindStore

    store = InMemoryChannelCodingBindStore()
    await store.bind("v2:slack:T:C:1", "ct_1", "u_owner")
    published: list[tuple[str, str]] = []

    class Sink:
        async def publish(self, binding, text) -> None:
            published.append((binding.session_id, text))

    callback = celery_runtime._lifecycle_callback(
        get_binding=store.get_by_task, sink=Sink()
    )
    await callback("ct_1", "completed", {})
    await callback(
        "ct_1",
        "waiting_approval",
        {"approval_id": "ca_9", "tool_name": "write_file.v1"},
    )
    await callback(
        "ct_1",
        "waiting_approval",
        {"approval_id": "ca_1", "tool_name": "todo_write.v1"},
    )
    await callback("ct_missing", "completed", {})

    assert published == [
        ("v2:slack:T:C:1", "ct_1 completed"),
        ("v2:slack:T:C:1", "ct_1 waiting_approval ca_9 write_file.v1"),
    ]


def test_worker_lifecycle_uses_manager_session_factory(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeStore:
        def __init__(self, session_factory) -> None:
            captured["session_factory"] = session_factory

        async def get_by_task(self, task_id: str):
            del task_id
            return None

    monkeypatch.setattr(celery_runtime, "PostgresChannelCodingBindStore", FakeStore)
    manager = RecordingDatabaseManager()
    celery_runtime._worker_lifecycle_callback(manager)
    factory = captured["session_factory"]
    assert factory.__self__ is manager
    assert factory.__func__ is type(manager).get_session


async def test_logging_lifecycle_sink_logs_card_text(caplog) -> None:
    import logging
    from datetime import UTC, datetime

    from neos.api.channels.session_bind import ChannelCodingBinding

    sink = celery_runtime.LoggingChannelLifecycleSink()
    binding = ChannelCodingBinding(
        session_id="v2:slack:T:C:1",
        task_id="ct_1",
        owner_id="u_owner",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with caplog.at_level(logging.INFO, logger=celery_runtime.logger.name):
        await sink.publish(binding, "ct_1 completed")
    assert "ct_1 completed" in caplog.text


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

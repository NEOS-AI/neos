import asyncio
from types import SimpleNamespace

import pytest

from neos.coding.domain.durability import RunAlreadyLeased
from neos.coding.workers.development_supervisor import (
    CodingDevelopmentSupervisor,
)

pytestmark = pytest.mark.no_db


class EmptyWorkRepository:
    async def claimable_task_ids(self, *, limit: int) -> list[str]:
        return []


class BlockingDriver:
    def __init__(self) -> None:
        self.ensure_calls: list[str] = []
        self.fail_calls: list[tuple[str, str, str]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def ensure_started(self, *, task_id: str) -> None:
        self.ensure_calls.append(task_id)

    async def advance_one_safe_point(self, *, task_id: str, worker_id: str):
        self.started.set()
        await self.release.wait()
        return SimpleNamespace(type="run.completed")

    async def fail_active_run(
        self, *, task_id: str, worker_id: str, error_code: str
    ) -> None:
        self.fail_calls.append((task_id, worker_id, error_code))


class LeaseBusyDriver(BlockingDriver):
    async def advance_one_safe_point(self, *, task_id: str, worker_id: str):
        raise RunAlreadyLeased(task_id)


class AlwaysFailingDriver(BlockingDriver):
    def __init__(self) -> None:
        super().__init__()
        self.advance_calls = 0

    async def advance_one_safe_point(self, *, task_id: str, worker_id: str):
        self.advance_calls += 1
        raise RuntimeError("transient")


class StartFailingDriver(BlockingDriver):
    async def ensure_started(self, *, task_id: str) -> None:
        raise RuntimeError("database unavailable")


class RecordingSleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def supervisor_for(driver, **overrides) -> CodingDevelopmentSupervisor:
    return CodingDevelopmentSupervisor(
        runs=driver,
        work_repository=EmptyWorkRepository(),
        reconciliation_interval=60.0,
        worker_id="worker-test",
        **overrides,
    )


async def test_duplicate_notifications_create_one_local_runner() -> None:
    driver = BlockingDriver()
    supervisor = supervisor_for(driver)
    await supervisor.start()

    assert supervisor.notify("ct_1") is True
    assert supervisor.notify("ct_1") is False
    await driver.started.wait()

    assert driver.ensure_calls == ["ct_1"]
    driver.release.set()
    await supervisor.wait_idle()
    await supervisor.stop()


async def test_lease_busy_is_expected_exit_without_failure() -> None:
    driver = LeaseBusyDriver()
    supervisor = supervisor_for(driver)
    await supervisor.start()
    supervisor.notify("ct_1")
    await supervisor.wait_idle()

    assert driver.fail_calls == []
    assert supervisor.outcomes == ["lease_busy"]
    await supervisor.stop()


async def test_unexpected_error_retries_with_bounded_backoff_then_fails() -> None:
    sleeps = RecordingSleeper()
    driver = AlwaysFailingDriver()
    supervisor = supervisor_for(driver, sleep=sleeps)
    await supervisor.start()
    supervisor.notify("ct_1")
    await supervisor.wait_idle()

    assert sleeps.delays == [1.0, 2.0, 4.0]
    assert driver.advance_calls == 4
    assert driver.fail_calls == [
        ("ct_1", supervisor.worker_id, "supervisor_retry_exhausted")
    ]
    assert supervisor.outcomes == ["failed"]
    await supervisor.stop()


async def test_reconciliation_dispatches_claimable_tasks() -> None:
    driver = LeaseBusyDriver()

    class ClaimableWorkRepository:
        async def claimable_task_ids(self, *, limit: int) -> list[str]:
            assert limit == 7
            return ["ct_1"]

    supervisor = CodingDevelopmentSupervisor(
        runs=driver,
        work_repository=ClaimableWorkRepository(),
        discovery_batch_size=7,
        reconciliation_interval=60.0,
        worker_id="worker-test",
    )

    await supervisor.start()
    await supervisor.wait_idle()

    assert driver.ensure_calls == ["ct_1"]
    await supervisor.stop()


async def test_stop_rejects_notifications_and_cancels_active_runner() -> None:
    driver = BlockingDriver()
    supervisor = supervisor_for(driver)
    await supervisor.start()
    supervisor.notify("ct_1")
    await driver.started.wait()

    await supervisor.stop()

    assert supervisor.is_running is False
    assert supervisor.notify("ct_2") is False
    await supervisor.wait_idle()


async def test_start_failure_is_observed_by_supervisor() -> None:
    supervisor = supervisor_for(StartFailingDriver())
    await supervisor.start()
    supervisor.notify("ct_1")

    await supervisor.wait_idle()

    assert supervisor.outcomes == ["runner_error"]
    await supervisor.stop()

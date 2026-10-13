"""코딩 태스크 → 작업 기록 (spec 2026-10-13 §4.4, 결정 B). Q 코드를 건드리지 않는 포트 주입."""

from datetime import UTC, datetime

import pytest

from neos.coding.application import work_port
from neos.coding.domain.models import CodingTask, CodingTaskMode, CodingTaskStatus
from neos.workflow.runtime.coding_link import CodingWorkLink
from neos.workflow.runtime.work import InMemoryWorkStore, WorkLifecycle

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]


def _task(agent_id=None) -> CodingTask:
    now = datetime.now(UTC)
    return CodingTask(
        task_id="ct_link_1", owner_id="u1", prompt="p", status=CodingTaskStatus.QUEUED, version=1, last_seq=0,
        created_at=now, updated_at=now, mode=CodingTaskMode.AUTONOMOUS, agent_id=agent_id,
    )


@pytest.fixture
def link(monkeypatch):
    lifecycle = WorkLifecycle(InMemoryWorkStore())
    monkeypatch.setattr(work_port, "_port", CodingWorkLink(lifecycle))
    return lifecycle


async def test_a_trigger_task_opens_and_completes_a_coding_work(link) -> None:
    await work_port.notify_task_created(_task(agent_id="sa_1"))
    record = await link.store.by_ref("coding", "ct_link_1")
    assert (record.entry, record.kind, record.user_id, record.status) == ("trigger", "coding", "u1", "running")
    assert record.delivery == {"kind": "none"}
    await work_port.notify_task_completed(_task(agent_id="sa_1"))
    assert (await link.store.by_ref("coding", "ct_link_1")).status == "completed"


async def test_a_task_without_an_agent_is_an_api_entry(link) -> None:
    await work_port.notify_task_created(_task())
    assert (await link.store.by_ref("coding", "ct_link_1")).entry == "api"


async def test_a_broken_port_never_breaks_the_coding_path(monkeypatch) -> None:
    class Broken:
        async def coding_task_created(self, task):
            raise RuntimeError("down")

        async def coding_task_completed(self, task):
            raise RuntimeError("down")

    monkeypatch.setattr(work_port, "_port", Broken())
    await work_port.notify_task_created(_task())
    await work_port.notify_task_completed(_task())


async def test_no_port_is_a_no_op(monkeypatch) -> None:
    monkeypatch.setattr(work_port, "_port", None)
    await work_port.notify_task_created(_task())


def test_the_link_installs_only_on_the_native_runtime(monkeypatch) -> None:
    from neos.config.settings import settings
    from neos.workflow.runtime import coding_link

    monkeypatch.setattr(work_port, "_port", None)
    monkeypatch.setattr(settings.config.workflow, "runtime", "langgraph")
    assert coding_link.install_coding_link() is False
    assert work_port._port is None

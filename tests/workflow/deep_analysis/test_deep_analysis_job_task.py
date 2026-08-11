"""실행자 디스패처 테스트 — Celery 브로커도 Postgres도 필요 없다."""

import asyncio

import pytest

from neos.tasks import deep_analysis_job_task as task_module


pytestmark = pytest.mark.no_db


def test_celery_task_is_registered_with_long_time_limits():
    """celery_app.py의 전역 기본값(soft 300s / hard 360s)은 심층분석 run에
    턱없이 짧다 -- dig effort 하나의 wall_clock_cap만 600s다."""
    from neos.config.settings import settings

    config = settings.config.deep_analysis
    task = task_module.run_deep_analysis_job

    assert task.name == "neos.tasks.run_deep_analysis_job"
    assert task.soft_time_limit == config.job_soft_time_limit
    assert task.time_limit == config.job_time_limit


@pytest.mark.asyncio
async def test_submit_uses_celery_when_enabled(monkeypatch):
    captured = {}

    def apply_async(**kwargs):
        captured.update(kwargs)
        return type("AsyncResult", (), {"id": "celery-task-id"})()

    monkeypatch.setattr(
        task_module.run_deep_analysis_job, "apply_async", apply_async
    )
    monkeypatch.setattr(task_module, "_celery_enabled", lambda: True)

    executor = await task_module.submit_deep_analysis_job(
        "run00001", "질문", "dev"
    )

    assert executor == "celery"
    assert captured["queue"] == "analysis"
    assert captured["kwargs"] == {
        "run_id": "run00001",
        "question": "질문",
        "profile": "dev",
        "resume": False,
    }


@pytest.mark.asyncio
async def test_submit_falls_back_to_a_background_task_when_celery_is_off(
    monkeypatch,
):
    """추가 AC: CELERY_ENABLED=false(기본)에서도 심층분석이 동작해야 한다."""
    ran = asyncio.Event()
    seen = {}

    async def fake_execute(
        run_id,
        question,
        profile,
        resume,
        *,
        timeout_seconds=None,
    ):
        seen.update(
            run_id=run_id,
            question=question,
            profile=profile,
            resume=resume,
            timeout_seconds=timeout_seconds,
        )
        ran.set()

    monkeypatch.setattr(task_module, "_celery_enabled", lambda: False)
    monkeypatch.setattr(task_module, "_execute", fake_execute)

    executor = await task_module.submit_deep_analysis_job(
        "run00001", "질문", "default"
    )

    assert executor == "inline"
    await asyncio.wait_for(ran.wait(), timeout=2)
    assert seen == {
        "run_id": "run00001",
        "question": "질문",
        "profile": "default",
        "resume": False,
        "timeout_seconds": task_module._config.job_soft_time_limit,
    }


@pytest.mark.asyncio
async def test_background_task_is_strongly_referenced_until_it_finishes(
    monkeypatch,
):
    """asyncio.create_task의 반환값을 붙들지 않으면 GC가 실행 중 태스크를
    거둬갈 수 있다. 모듈 레벨 집합이 강한 참조를 유지해야 한다."""
    release = asyncio.Event()

    async def fake_execute(
        run_id,
        question,
        profile,
        resume,
        *,
        timeout_seconds=None,
    ):
        await release.wait()

    monkeypatch.setattr(task_module, "_celery_enabled", lambda: False)
    monkeypatch.setattr(task_module, "_execute", fake_execute)

    await task_module.submit_deep_analysis_job("run00001", "질문", "dev")

    assert len(task_module._BACKGROUND_TASKS) == 1
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(task_module._BACKGROUND_TASKS) == 0


@pytest.mark.asyncio
async def test_execute_does_not_persist_message_after_timeout(monkeypatch):
    from neos.workflow.deep_analysis import jobs

    persisted = False

    async def timed_out(*args, **kwargs):
        raise asyncio.TimeoutError

    async def persist(*args, **kwargs):
        nonlocal persisted
        persisted = True

    monkeypatch.setattr(jobs, "execute_run", timed_out)
    monkeypatch.setattr(task_module, "_persist_assistant_message", persist)

    with pytest.raises(asyncio.TimeoutError):
        await task_module._execute(
            "run00001",
            "질문",
            "dev",
            False,
            timeout_seconds=0.01,
        )

    assert persisted is False


@pytest.mark.asyncio
async def test_submit_passes_resume_through(monkeypatch):
    captured = {}

    def apply_async(**kwargs):
        captured.update(kwargs)
        return type("AsyncResult", (), {"id": "x"})()

    monkeypatch.setattr(
        task_module.run_deep_analysis_job, "apply_async", apply_async
    )
    monkeypatch.setattr(task_module, "_celery_enabled", lambda: True)

    await task_module.submit_deep_analysis_job("run00001", resume=True)

    assert captured["kwargs"]["resume"] is True


@pytest.mark.asyncio
async def test_celery_broker_failure_is_recorded_and_never_runs_inline(
    monkeypatch,
):
    recorded = []
    executed = False

    def broker_down(**kwargs):
        raise ConnectionError("redis://user:secret@broker")

    async def record(run_id):
        recorded.append(run_id)

    async def execute(*args, **kwargs):
        nonlocal executed
        executed = True

    monkeypatch.setattr(task_module, "_celery_enabled", lambda: True)
    monkeypatch.setattr(
        task_module.run_deep_analysis_job, "apply_async", broker_down
    )
    monkeypatch.setattr(
        task_module, "_record_dispatch_failure", record, raising=False
    )
    monkeypatch.setattr(task_module, "_execute", execute)

    with pytest.raises(task_module.DeepAnalysisDispatchError) as captured:
        await task_module.submit_deep_analysis_job(
            "run00001", "private question"
        )

    assert str(captured.value) == (
        "deep_analysis dispatch failed for run run00001"
    )
    assert recorded == ["run00001"]
    assert executed is False
    assert isinstance(captured.value.__cause__, ConnectionError)
    assert "secret" not in str(captured.value)


@pytest.mark.asyncio
async def test_failure_persistence_error_does_not_replace_broker_error(
    monkeypatch,
):
    broker_error = ConnectionError("broker unavailable")

    def broker_down(**kwargs):
        raise broker_error

    async def record_failure(run_id):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(task_module, "_celery_enabled", lambda: True)
    monkeypatch.setattr(
        task_module.run_deep_analysis_job, "apply_async", broker_down
    )
    monkeypatch.setattr(
        task_module,
        "_record_dispatch_failure",
        record_failure,
        raising=False,
    )

    with pytest.raises(task_module.DeepAnalysisDispatchError) as captured:
        await task_module.submit_deep_analysis_job("run00001")

    assert captured.value.__cause__ is broker_error


def test_task_is_exported_from_the_tasks_package():
    """Celery 워커는 neos.tasks를 임포트할 때 태스크를 등록한다."""
    import neos.tasks as tasks

    assert tasks.run_deep_analysis_job is task_module.run_deep_analysis_job
    assert "run_deep_analysis_job" in tasks.__all__


@pytest.mark.asyncio
async def test_execute_passes_degradations_to_the_message_persister(monkeypatch):
    """강등이 메시지까지 가지 않으면 새로고침 후 UI가 다시 침묵한다."""
    from neos.workflow.deep_analysis import jobs

    seen = {}

    async def run(*args, **kwargs):
        return {
            "run_id": "run00001",
            "report_markdown": "## 요약\n본문",
            "degradations": [{"kind": "report_assembly_degraded", "count": 3}],
        }

    async def persist(run_id, report_markdown, degradations):
        seen["run_id"] = run_id
        seen["degradations"] = degradations

    monkeypatch.setattr(jobs, "execute_run", run)
    monkeypatch.setattr(task_module, "_persist_assistant_message", persist)

    await task_module._execute("run00001", "질문", "dev", False)

    assert seen["run_id"] == "run00001"
    assert seen["degradations"] == [
        {"kind": "report_assembly_degraded", "count": 3}
    ]


@pytest.mark.asyncio
async def test_persisted_message_metadata_carries_the_degradations(monkeypatch):
    """FE 브리지가 읽는 키 이름을 고정한다 -- 이름이 어긋나면 카드가 침묵한다."""
    from contextlib import asynccontextmanager

    import neos.api.services.chat_service as chat_service_module
    import neos.database.connection as connection_module

    captured = {}

    class FakeChatService:
        @staticmethod
        async def add_message(**kwargs):
            captured.update(kwargs)

    class FakeRun:
        conversation_id = "conv-1"
        assistant_message_id = "msg-1"

    class FakeSession:
        async def get(self, model, key):
            return FakeRun()

    @asynccontextmanager
    async def fake_session_ctx():
        yield FakeSession()

    # `_persist_assistant_message` 는 함수 안에서 import 하므로 모듈 속성을
    # 갈아끼우면 그 import 가 Fake 를 집어온다.
    monkeypatch.setattr(chat_service_module, "ChatService", FakeChatService)
    monkeypatch.setattr(connection_module, "get_session_ctx", fake_session_ctx)

    await task_module._persist_assistant_message(
        "run00001",
        "## 요약\n본문",
        [{"kind": "judge_unreviewed:budget_exhausted", "count": 1}],
    )

    assert captured["metadata"]["deep_analysis_degradations"] == [
        {"kind": "judge_unreviewed:budget_exhausted", "count": 1}
    ]
    assert captured["metadata"]["deep_analysis_run_id"] == "run00001"

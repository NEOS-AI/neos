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


def test_submit_uses_celery_when_enabled(monkeypatch):
    captured = {}

    def apply_async(**kwargs):
        captured.update(kwargs)
        return type("AsyncResult", (), {"id": "celery-task-id"})()

    monkeypatch.setattr(
        task_module.run_deep_analysis_job, "apply_async", apply_async
    )
    monkeypatch.setattr(task_module, "_celery_enabled", lambda: True)

    executor = task_module.submit_deep_analysis_job("run00001", "질문", "dev")

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

    async def fake_execute(run_id, question, profile, resume):
        seen.update(
            run_id=run_id, question=question, profile=profile, resume=resume
        )
        ran.set()

    monkeypatch.setattr(task_module, "_celery_enabled", lambda: False)
    monkeypatch.setattr(task_module, "_execute", fake_execute)

    executor = task_module.submit_deep_analysis_job("run00001", "질문", "default")

    assert executor == "inline"
    await asyncio.wait_for(ran.wait(), timeout=2)
    assert seen == {
        "run_id": "run00001",
        "question": "질문",
        "profile": "default",
        "resume": False,
    }


@pytest.mark.asyncio
async def test_background_task_is_strongly_referenced_until_it_finishes(
    monkeypatch,
):
    """asyncio.create_task의 반환값을 붙들지 않으면 GC가 실행 중 태스크를
    거둬갈 수 있다. 모듈 레벨 집합이 강한 참조를 유지해야 한다."""
    release = asyncio.Event()

    async def fake_execute(run_id, question, profile, resume):
        await release.wait()

    monkeypatch.setattr(task_module, "_celery_enabled", lambda: False)
    monkeypatch.setattr(task_module, "_execute", fake_execute)

    task_module.submit_deep_analysis_job("run00001", "질문", "dev")

    assert len(task_module._BACKGROUND_TASKS) == 1
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(task_module._BACKGROUND_TASKS) == 0


def test_submit_passes_resume_through(monkeypatch):
    captured = {}

    def apply_async(**kwargs):
        captured.update(kwargs)
        return type("AsyncResult", (), {"id": "x"})()

    monkeypatch.setattr(
        task_module.run_deep_analysis_job, "apply_async", apply_async
    )
    monkeypatch.setattr(task_module, "_celery_enabled", lambda: True)

    task_module.submit_deep_analysis_job("run00001", resume=True)

    assert captured["kwargs"]["resume"] is True


def test_task_is_exported_from_the_tasks_package():
    """Celery 워커는 neos.tasks를 임포트할 때 태스크를 등록한다."""
    import neos.tasks as tasks

    assert tasks.run_deep_analysis_job is task_module.run_deep_analysis_job
    assert "run_deep_analysis_job" in tasks.__all__

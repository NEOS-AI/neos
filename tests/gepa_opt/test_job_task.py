"""Celery submit path for GEPA opt jobs. No DB, no HTTP, no inline engine."""

from __future__ import annotations

import inspect
import os
from pathlib import Path

# Development YAML turns the coding loop on, and Settings() refuses to load
# without a credential. This slice never calls that loop.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-gepa-opt-not-a-real-key")

import pytest

pytestmark = pytest.mark.no_db

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_learn_config_gepa_opt_defaults_false() -> None:
    from neos.config.schema import LearnConfig

    cfg = LearnConfig()
    assert cfg.gepa_opt is False


def test_legacy_exact_path_learn_gepa_opt() -> None:
    import neos.config.settings as settings_mod

    if hasattr(settings_mod, "LEGACY_EXACT_PATHS"):
        mapping = settings_mod.LEGACY_EXACT_PATHS
    else:
        mapping = None
        for name in dir(settings_mod):
            obj = getattr(settings_mod, name)
            if isinstance(obj, dict) and "LEARN_CODING_LESSONS" in obj:
                mapping = obj
                break
        assert mapping is not None, "no settings dict contains LEARN_CODING_LESSONS"
    assert mapping["LEARN_GEPA_OPT"] == "learn.gepa_opt"


def test_celery_app_source_includes_gepa_opt_queue() -> None:
    source = (_REPO_ROOT / "neos" / "workflow" / "celery_app.py").read_text(encoding="utf-8")
    assert "neos.tasks.gepa_opt_job_task" in source
    assert "neos.tasks.run_gepa_opt_job" in source
    assert "gepa_opt" in source
    # Route the named task onto the gepa_opt queue, and declare that queue.
    assert "Queue('gepa_opt'" in source or 'Queue("gepa_opt"' in source


def test_run_gepa_opt_job_retry_and_time_limits() -> None:
    from neos.tasks.gepa_opt_job_task import run_gepa_opt_job

    assert run_gepa_opt_job.max_retries == 2
    assert run_gepa_opt_job.soft_time_limit == 1800
    assert run_gepa_opt_job.time_limit == 2100


def _patch_flags(monkeypatch: pytest.MonkeyPatch, *, celery_enabled: bool, gepa_opt: bool) -> None:
    import neos.tasks.gepa_opt_job_task as job

    monkeypatch.setattr(job.settings.config.celery, "enabled", celery_enabled)
    monkeypatch.setattr(job.settings.config.learn, "gepa_opt", gepa_opt)


def _install_apply_async_spy(monkeypatch: pytest.MonkeyPatch) -> dict:
    import neos.tasks.gepa_opt_job_task as job

    captured: dict = {"calls": [], "inline": []}

    def fake_apply_async(*args, **kwargs):
        captured["calls"].append((args, kwargs))

        class _Result:
            id = "async-123"

        return _Result()

    def fake_run(*args, **kwargs):
        captured["inline"].append((args, kwargs))
        raise AssertionError("engine must not run inline")

    monkeypatch.setattr(job.run_gepa_opt_job, "apply_async", fake_apply_async)
    monkeypatch.setattr(job.run_gepa_opt_job, "run", fake_run)
    return captured


@pytest.mark.parametrize(
    ("celery_enabled", "gepa_opt"),
    [(False, True), (True, False), (False, False)],
)
def test_submit_refuses_when_either_flag_off(
    monkeypatch: pytest.MonkeyPatch,
    celery_enabled: bool,
    gepa_opt: bool,
) -> None:
    import neos.tasks.gepa_opt_job_task as job

    captured = _install_apply_async_spy(monkeypatch)
    _patch_flags(monkeypatch, celery_enabled=celery_enabled, gepa_opt=gepa_opt)

    result = job.submit_gepa_opt_job("run-1", "owner-ns")
    assert result == "refused"
    assert captured["calls"] == []
    assert captured["inline"] == []

    source = inspect.getsource(job.submit_gepa_opt_job)
    assert "asyncio.create_task" not in source
    assert "APIRouter" not in source


def test_submit_queues_when_both_flags_on(monkeypatch: pytest.MonkeyPatch) -> None:
    import neos.tasks.gepa_opt_job_task as job

    captured = _install_apply_async_spy(monkeypatch)
    _patch_flags(monkeypatch, celery_enabled=True, gepa_opt=True)

    result = job.submit_gepa_opt_job("run-1", "owner-ns")
    assert len(captured["calls"]) == 1
    _args, kwargs = captured["calls"][0]
    assert kwargs.get("queue") == "gepa_opt"
    assert kwargs.get("args") == ["run-1", "owner-ns"]
    assert captured["inline"] == []
    assert result in ("async-123", "queued")


def test_job_module_does_not_insert_learned_lessons() -> None:
    source = (_REPO_ROOT / "neos" / "tasks" / "gepa_opt_job_task.py").read_text(encoding="utf-8")
    assert "INSERT INTO learned_lessons" not in source

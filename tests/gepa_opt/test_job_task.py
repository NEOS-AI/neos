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


def test_empty_registry_fails_the_run_and_a_lost_claim_does_not() -> None:
    import asyncio

    import neos.tasks.gepa_opt_job_task as job
    from neos.gepa_opt.evaluators import clear_evaluators

    clear_evaluators()
    calls = {"fail": 0, "claim": 0}

    class _Store:
        def __init__(self, claimed: bool) -> None:
            self._claimed = claimed

        async def claim(self, *_args):
            calls["claim"] += 1
            return "claimed" if self._claimed else "lost"

        async def fail_run(self, _run_id, _owner, error_code):
            calls["fail"] += 1
            assert error_code == "no_evaluator"

    lost = asyncio.run(
        job.execute_gepa_opt_job(
            _Store(False),
            run_id="run-1",
            owner_namespace="owner:1",
            celery_task_id="task-1",
        )
    )
    assert lost == "lost"
    assert calls["fail"] == 0

    failed = asyncio.run(
        job.execute_gepa_opt_job(
            _Store(True),
            run_id="run-1",
            owner_namespace="owner:1",
            celery_task_id="task-1",
        )
    )
    assert failed == "no_evaluator"
    assert calls["fail"] == 1


def test_registered_evaluator_stages_an_overlay() -> None:
    import asyncio

    import neos.tasks.gepa_opt_job_task as job
    from neos.gepa_opt.evaluators import clear_evaluators, register_evaluator

    clear_evaluators()

    def score(_candidate, _example):
        return (1.0, {"ok": True})

    register_evaluator("coding_overlay", score)
    staged: list[dict] = []

    class _Store:
        async def claim(self, *_args):
            return True

        async def fail_run(self, *_args):
            raise AssertionError("a perfect seed should stage, not fail")

        async def load_bundle(self, _run_id, _owner):
            return {
                "seed": {"instr": "a"},
                "train": [{"id": "t"}],
                "val": [{"id": "v"}],
                "test": [],
                "engine_label": "gepa",
                "pareto_enabled": True,
                "max_evals": 3,
                "max_token_cost": 10,
                "component_cursor": 0,
                "seed_candidate_id": "seed-1",
                "surface": "coding_overlay",
            }

        async def stage_overlay(self, **kwargs):
            staged.append(kwargs)

        async def mark_succeeded(self, *_args):
            return None

    def reflector(*_args):
        raise AssertionError("perfect minibatch must not reflect")

    outcome = asyncio.run(
        job.execute_gepa_opt_job(
            _Store(),
            run_id="run-1",
            owner_namespace="owner:1",
            celery_task_id="task-1",
            reflector=reflector,
        )
    )
    assert outcome == "staged"
    assert staged[0]["candidate_id"] == "seed-1"
    assert staged[0]["owner_namespace"] == "owner:1"
    clear_evaluators()


def test_accepted_child_is_committed_before_it_is_staged() -> None:
    import asyncio
    from types import SimpleNamespace

    import neos.tasks.gepa_opt_job_task as job
    from neos.gepa_opt.evaluators import clear_evaluators, register_evaluator

    clear_evaluators()

    def score(candidate, _example):
        return (0.9 if candidate["instr"] == "b" else 0.2, {"note": "x"})

    register_evaluator("coding_overlay", score)
    staged: list[dict] = []
    committed: list[dict] = []

    class _Store:
        async def claim(self, *_args):
            return True

        async def fail_run(self, *_args):
            raise AssertionError("accepted child should stage")

        async def load_bundle(self, _run_id, _owner):
            return {
                "seed": {"instr": "a"},
                "train": [{"id": "t", "example_id": "ex-train", "split": "train"}],
                "val": [{"id": "v", "example_id": "ex-val", "split": "val"}],
                "test": [],
                "engine_label": "not-gepa",
                "pareto_enabled": False,
                "max_evals": 20,
                "max_token_cost": 100,
                "component_cursor": 0,
                "seed_candidate_id": "seed-1",
                "surface": "coding_overlay",
            }

        async def commit_iteration(self, **kwargs):
            committed.append(kwargs)
            return "child-1"

        async def stage_overlay(self, **kwargs):
            staged.append(kwargs)

        async def mark_succeeded(self, *_args):
            return None

    def reflector(name, _curr, _side):
        return SimpleNamespace(
            component_name=name,
            delta={"instr": "b"},
            usage=SimpleNamespace(input_tokens=1, output_tokens=1, finish_reason="stop"),
            text="```\nb\n```",
        )

    outcome = asyncio.run(
        job.execute_gepa_opt_job(
            _Store(),
            run_id="run-1",
            owner_namespace="owner:1",
            celery_task_id="task-1",
            reflector=reflector,
        )
    )
    assert outcome == "staged"
    assert staged[0]["candidate_id"] == "child-1"
    example_ids = {row["example_id"] for row in committed[0]["scores"]}
    assert "ex-val" in example_ids
    assert all(row["side_info"] for row in committed[0]["scores"])
    phases = {row["example_id"]: row["phase"] for row in committed[0]["scores"]}
    assert phases["ex-val"] == "full_val"
    clear_evaluators()


def test_soft_time_limit_retries_without_staging() -> None:
    import neos.tasks.gepa_opt_job_task as job

    class _Self:
        def retry(self, **kwargs):
            self.kwargs = kwargs
            raise RuntimeError("retried")

    task = _Self()
    with pytest.raises(RuntimeError, match="retried"):
        job._retry_after_soft_limit(task, job.SoftTimeLimitExceeded())
    assert task.kwargs["countdown"] == 0
    source = inspect.getsource(job.run_gepa_opt_job)
    assert "SoftTimeLimitExceeded" in source
    assert "_retry_after_soft_limit" in source
    assert "stage_overlay" not in source


def test_resume_does_not_rescore_the_seed_valset() -> None:
    import asyncio

    import neos.tasks.gepa_opt_job_task as job
    from neos.gepa_opt.evaluators import clear_evaluators, register_evaluator

    clear_evaluators()
    seen: list[str] = []

    def score(_candidate, example):
        seen.append(example["id"])
        return (1.0, {"ok": True})

    register_evaluator("coding_overlay", score)

    class _Store:
        async def claim(self, *_args):
            return "resume"

        async def fail_run(self, *_args):
            raise AssertionError("resume should not fail a perfect continuation")

        async def load_bundle(self, _run_id, _owner):
            return {
                "seed": {"instr": "a"},
                "train": [{"id": "t", "example_id": "ex-train", "split": "train"}],
                "val": [{"id": "v", "example_id": "ex-val", "split": "val"}],
                "test": [],
                "engine_label": "gepa",
                "pareto_enabled": True,
                "max_evals": 6,
                "max_token_cost": 10,
                "component_cursor": 0,
                "seed_candidate_id": "seed-1",
                "surface": "coding_overlay",
                "iteration": 1,
                "evals_used": 4,
                "reflector_tokens_used": 0,
                "candidates": [
                    {
                        "proposal_kind": "seed",
                        "components": {"instr": "a"},
                        "accepted": True,
                        "reject_reason": None,
                        "val_mean": 1.0,
                        "test_mean": None,
                        "val_subscores": [1.0],
                        "iteration": 0,
                    }
                ],
            }

        async def stage_overlay(self, **_kwargs):
            return None

        async def mark_succeeded(self, *_args):
            return None

    def reflector(*_args):
        raise AssertionError("perfect minibatch must not reflect")

    outcome = asyncio.run(
        job.execute_gepa_opt_job(
            _Store(),
            run_id="run-1",
            owner_namespace="owner:1",
            celery_task_id="task-1",
            reflector=reflector,
        )
    )
    assert outcome == "staged"
    assert "v" not in seen
    clear_evaluators()

import asyncio
from copy import deepcopy
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import subprocess
import sys
from types import SimpleNamespace

import pytest

import neos.workflow.deep_analysis.funnel_sample_runner as runner
from neos.workflow.deep_analysis.funnel_sample import QuestionCase
from neos.workflow.deep_analysis.funnel_sample_runner import (
    PreflightError,
    preflight,
    render_report,
    run_sample,
    sanitize_error,
    write_artifacts,
)


CASES = (
    QuestionCase("first", "fact", "First?"),
    QuestionCase("second", "technical", "Second?"),
    QuestionCase("third", "causal_policy", "Third?"),
)

RESULT = {
    "schema_version": "1",
    "question_set_version": "mixed-v1",
    "dev_runs": [
        {
            "case_id": "fact-aspartame",
            "category": "fact",
            "question": "Declared evaluation question",
            "profile": "dev",
            "status": "completed",
            "run_id": "dev-run",
            "elapsed_seconds": 1.25,
            "tokens_spent": 20,
            "order": 0,
            "signals": {
                "claim_funnel": {
                    "proposed": 4,
                    "graded": 3,
                    "deterministic_rejected": 2,
                    "verified": 1,
                    "rejected": 2,
                    "unverified": 0,
                    "evidence_missing_rate": 1 / 3,
                    "source_dead_rate": 0.0,
                    "quote_score_buckets": {
                        "exact": 1,
                        "above_threshold": 0,
                        "near_miss": 1,
                        "low": 1,
                        "unavailable": 0,
                    },
                },
                "report": {"body": "report body"},
                "model_response": "private response",
                "claims": ["private claim"],
                "evidence": ["private evidence"],
                "fetched_body": "private fetched body",
                "url": "https://private.example",
                "api_key": "sk-private",
            },
        }
    ],
    "selection": {
        "case_id": "fact-aspartame",
        "dominant_stage": "deterministic_rejection",
        "dev_order": 0,
    },
    "default_run": {
        "case_id": "fact-aspartame",
        "category": "fact",
        "question": "Declared evaluation question",
        "profile": "default",
        "status": "failed",
        "run_id": "default-run",
        "error": {
            "type": "RuntimeError",
            "stage": "collection",
            "message": "https://error.example sk-error private exception",
        },
    },
    "dev_funnel": {
        "proposed": 4,
        "graded": 3,
        "deterministic_rejected": 2,
        "verified": 1,
        "rejected": 2,
        "unverified": 0,
        "evidence_missing_rate": 1 / 3,
        "source_dead_rate": 0.0,
        "quote_score_buckets": {
            "exact": 1,
            "above_threshold": 0,
            "near_miss": 1,
            "low": 1,
            "unavailable": 0,
        },
    },
}


def test_importing_runner_registers_users_foreign_key_target():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import neos.workflow.deep_analysis.funnel_sample_runner; "
                "from neos.database.connection import Base; "
                "from neos.database.deep_analysis_models import DARun; "
                "foreign_key = next(iter(DARun.__table__.foreign_keys)); "
                "assert 'users' in Base.metadata.tables; "
                "assert foreign_key.column.table is Base.metadata.tables['users']"
            ),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_write_artifacts_creates_timestamped_contract(tmp_path):
    artifact_dir = write_artifacts(
        RESULT,
        tmp_path,
        now=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
    )
    assert artifact_dir.name == "20260719T120000Z"
    assert json.loads((artifact_dir / "manifest.json").read_text())[
        "schema_version"
    ] == "1"
    assert json.loads((artifact_dir / "funnel.json").read_text())[
        "selection"
    ]["case_id"] == "fact-aspartame"
    report = (artifact_dir / "report.md").read_text()
    assert "Dominant loss stage" in report
    assert "deterministic_rejection" in report
    serialized = "".join(path.read_text() for path in artifact_dir.iterdir())
    for forbidden in (
        "report body",
        "private response",
        "private claim",
        "private evidence",
        "private fetched body",
        "https://private.example",
        "sk-private",
        "https://error.example",
        "sk-error",
        "private exception",
    ):
        assert forbidden not in serialized


def test_write_artifacts_rejects_existing_directory(tmp_path):
    fixed = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    write_artifacts(RESULT, tmp_path, now=fixed)
    with pytest.raises(FileExistsError):
        write_artifacts(RESULT, tmp_path, now=fixed)


def test_render_report_states_overlap_and_policy_contract():
    report = render_report(RESULT)
    assert "stages overlap" in report
    assert "no policy was changed" in report


def test_artifacts_drop_adversarial_nested_funnel_and_error_metadata(tmp_path):
    result = deepcopy(RESULT)
    secret = "sk-adversarial-secret"
    url = "https://adversarial.example/private"
    report_text = "adversarial report body"
    unsafe_bucket = {
        "exact": url,
        "above_threshold": -2,
        "near_miss": float("inf"),
        "low": True,
        "unavailable": 5,
        "extra": {"url": url, "secret": secret, "report": report_text},
    }
    result["dev_funnel"]["quote_score_buckets"] = unsafe_bucket
    result["dev_runs"][0]["signals"]["claim_funnel"][
        "quote_score_buckets"
    ] = unsafe_bucket
    result["default_run"]["error"] = {
        "type": f"RuntimeError_{secret}",
        "stage": f"collection_{url}",
    }

    artifact_dir = write_artifacts(
        result,
        tmp_path,
        now=datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
    )
    serialized = {
        path.name: path.read_text() for path in artifact_dir.iterdir()
    }

    for content in serialized.values():
        assert secret not in content
        assert url not in content
        assert report_text not in content
        assert '"extra"' not in content
    assert '"type": "UnknownError"' in serialized["manifest.json"]
    assert '"stage": "execution"' in serialized["manifest.json"]
    assert "UnknownError at execution" in serialized["report.md"]
    funnel = json.loads(serialized["funnel.json"])
    assert funnel["dev_funnel"]["quote_score_buckets"] == {
        "unavailable": 5
    }


class HealthySession:
    async def execute(self, statement):
        assert str(statement) == "SELECT 1"


@asynccontextmanager
async def healthy_session_factory():
    yield HealthySession()


@pytest.mark.asyncio
async def test_preflight_requires_anthropic_tavily_and_database():
    fake_settings = SimpleNamespace(
        ANTHROPIC_API_KEY="anthropic", TAVILY_API_KEY="tavily"
    )
    await preflight(fake_settings, healthy_session_factory)


@pytest.mark.asyncio
async def test_preflight_lists_missing_names_without_values():
    fake_settings = SimpleNamespace(ANTHROPIC_API_KEY=None, TAVILY_API_KEY=None)
    with pytest.raises(
        PreflightError, match="ANTHROPIC_API_KEY, TAVILY_API_KEY"
    ):
        await preflight(fake_settings, healthy_session_factory)


def test_sanitize_error_exposes_only_type_and_fixed_stage():
    error = RuntimeError(
        "sk-live-secret https://private.example report model claim"
    )
    assert sanitize_error(error, ["sk-live-secret"]) == {
        "type": "RuntimeError",
        "stage": "execution",
    }


def _completed(case, profile, order=None):
    return {
        "case_id": case.case_id,
        "category": case.category,
        "question": case.question,
        "profile": profile,
        "status": "completed",
        "run_id": case.case_id + "-run",
        "elapsed_seconds": 1.0,
        "tokens_spent": 2,
        "signals": {
            "claim_funnel": {
                "proposed": 2,
                "graded": 1,
                "deterministic_rejected": 1,
            }
        },
        **({"order": order} if order is not None else {}),
    }


@pytest.mark.asyncio
async def test_run_sample_isolates_ordinary_failure_and_continues():
    calls = []

    async def fake_execute_case(case, profile):
        calls.append((case.case_id, profile))
        if case.case_id == "second":
            raise RuntimeError("provider leaked secret")
        return _completed(case, profile)

    result = await run_sample(
        cases=CASES,
        execute_case_fn=fake_execute_case,
        secrets=["secret"],
    )

    assert [item["status"] for item in result["dev_runs"]] == [
        "completed",
        "failed",
        "completed",
    ]
    assert result["dev_runs"][1]["error"] == {
        "type": "RuntimeError",
        "stage": "execution",
    }
    assert "signals" not in result["dev_runs"][1]
    assert calls == [
        ("first", "dev"),
        ("second", "dev"),
        ("third", "dev"),
        ("first", "default"),
    ]


@pytest.mark.asyncio
async def test_run_sample_propagates_cancellation():
    async def cancelled(case, profile):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_sample(
            cases=CASES, execute_case_fn=cancelled, secrets=[]
        )


@pytest.mark.asyncio
async def test_run_sample_skips_default_when_all_dev_runs_fail():
    calls = []

    async def failed(case, profile):
        calls.append((case.case_id, profile))
        raise RuntimeError("nope")

    result = await run_sample(
        cases=CASES, execute_case_fn=failed, secrets=[]
    )

    assert calls == [(case.case_id, "dev") for case in CASES]
    assert result["selection"] is None
    assert result["default_run"] is None


@pytest.mark.asyncio
async def test_run_sample_preserves_created_run_id_on_failure():
    class CreatedRunFailure(RuntimeError):
        run_id = "deadbeef"

    async def failed(case, profile):
        raise CreatedRunFailure("provider secret")

    result = await run_sample(
        cases=CASES[:1], execute_case_fn=failed, secrets=["secret"]
    )

    assert result["dev_runs"][0]["run_id"] == "deadbeef"
    assert set(result["dev_runs"][0]) == {
        "case_id",
        "category",
        "profile",
        "status",
        "order",
        "run_id",
        "error",
    }


class _CommittedSession:
    async def commit(self):
        pass


@asynccontextmanager
async def committed_session_factory():
    yield _CommittedSession()


@pytest.mark.asyncio
async def test_execution_failure_preserves_run_id_and_omits_sensitive_text(
    monkeypatch,
):
    async def fake_create_run(session, question, profile):
        return "execution-run"

    async def failed_execute(*args, **kwargs):
        raise RuntimeError(
            "sk-secret https://private.example report model claim"
        )

    monkeypatch.setattr(runner, "create_run", fake_create_run)
    result = await run_sample(
        cases=CASES[:1],
        session_factory=committed_session_factory,
        execute_fn=failed_execute,
        secrets=["sk-secret"],
    )

    failure = result["dev_runs"][0]
    assert failure["run_id"] == "execution-run"
    assert failure["error"] == {
        "type": "RuntimeError",
        "stage": "execution",
    }
    serialized = repr(failure)
    for forbidden in (
        "sk-secret",
        "https://private.example",
        "report",
        "model",
        "claim",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_creation_context_exit_failure_preserves_run_id(monkeypatch):
    @asynccontextmanager
    async def session_factory():
        yield _CommittedSession()
        raise RuntimeError("sensitive context exit detail")

    async def fake_create_run(session, question, profile):
        return "context-exit-run"

    async def unexpected_execute(*args, **kwargs):
        pytest.fail("execution must not begin after creation context exit fails")

    monkeypatch.setattr(runner, "create_run", fake_create_run)
    result = await run_sample(
        cases=CASES[:1],
        session_factory=session_factory,
        execute_fn=unexpected_execute,
        secrets=[],
    )

    failure = result["dev_runs"][0]
    assert failure["run_id"] == "context-exit-run"
    assert failure["error"] == {
        "type": "RuntimeError",
        "stage": "execution",
    }
    assert "sensitive context exit detail" not in repr(failure)


@pytest.mark.asyncio
async def test_initial_clock_failure_preserves_run_id(monkeypatch):
    async def fake_create_run(session, question, profile):
        return "clock-run"

    def failed_monotonic():
        raise RuntimeError("sensitive clock detail")

    async def unexpected_execute(*args, **kwargs):
        pytest.fail("execution must not begin after the initial clock fails")

    monkeypatch.setattr(runner, "create_run", fake_create_run)
    monkeypatch.setattr(
        runner, "time", SimpleNamespace(monotonic=failed_monotonic)
    )
    result = await run_sample(
        cases=CASES[:1],
        session_factory=committed_session_factory,
        execute_fn=unexpected_execute,
        secrets=[],
    )

    failure = result["dev_runs"][0]
    assert failure["run_id"] == "clock-run"
    assert failure["error"] == {
        "type": "RuntimeError",
        "stage": "execution",
    }
    assert "sensitive clock detail" not in repr(failure)


@pytest.mark.asyncio
async def test_collection_failure_preserves_run_id_and_omits_sensitive_text(
    monkeypatch,
):
    class CollectionSession(_CommittedSession):
        async def scalar(self, statement):
            raise LookupError(
                "sk-secret https://private.example report model claim"
            )

    calls = 0

    @asynccontextmanager
    async def session_factory():
        nonlocal calls
        calls += 1
        yield _CommittedSession() if calls == 1 else CollectionSession()

    async def fake_create_run(session, question, profile):
        return "collection-run"

    async def successful_execute(*args, **kwargs):
        pass

    monkeypatch.setattr(runner, "create_run", fake_create_run)
    result = await run_sample(
        cases=CASES[:1],
        session_factory=session_factory,
        execute_fn=successful_execute,
        secrets=["sk-secret"],
    )

    failure = result["dev_runs"][0]
    assert failure["run_id"] == "collection-run"
    assert failure["error"] == {
        "type": "LookupError",
        "stage": "collection",
    }
    serialized = repr(failure)
    for forbidden in (
        "sk-secret",
        "https://private.example",
        "report",
        "model",
        "claim",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_run_sample_accepts_production_execution_dependencies():
    result = await run_sample(
        cases=(),
        session_factory=healthy_session_factory,
        execute_fn=object(),
        timeout_seconds=12,
        secrets=[],
    )

    assert result["dev_runs"] == []

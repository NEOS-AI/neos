import asyncio
from copy import deepcopy
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import scripts.deep_analysis_funnel_sample as cli
import neos.workflow.deep_analysis.funnel_sample_runner as runner
from neos.workflow.deep_analysis.funnel_sample import QUESTION_CASES, QuestionCase
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


def _declared_questions():
    return [
        {
            "case_id": case.case_id,
            "category": case.category,
            "question": case.question,
        }
        for case in QUESTION_CASES
    ]


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
    manifest = json.loads((artifact_dir / "manifest.json").read_text())
    assert manifest["schema_version"] == "1"
    assert manifest["questions"] == {
        "schema_version": "1",
        "items": _declared_questions(),
    }
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


def test_write_artifacts_records_execution_receipt(tmp_path):
    artifact_dir = write_artifacts(
        RESULT,
        tmp_path,
        receipt={
            "pid": 4242,
            "started_at": "2026-07-27T00:00:00Z",
            "finished_at": "2026-07-27T00:10:00Z",
            "exit_status": 0,
            "tests_passed": True,
            "ruff_passed": True,
            "preflight_passed": True,
        },
        fingerprint={
            "manifest_version": 1,
            "git": {"commit": "abc123"},
            "runs": {"run0001": {"budget": {"global_token_cap": 20000}}},
        },
    )

    manifest = json.loads((artifact_dir / "manifest.json").read_text())

    assert manifest["execution_receipt"]["pid"] == 4242
    assert manifest["execution_receipt"]["exit_status"] == 0
    assert (
        manifest["config_fingerprint"]["runs"]["run0001"]["budget"][
            "global_token_cap"
        ]
        == 20000
    )


def test_write_artifacts_omits_provenance_when_not_supplied(tmp_path):
    artifact_dir = write_artifacts(RESULT, tmp_path)

    manifest = json.loads((artifact_dir / "manifest.json").read_text())

    assert manifest["execution_receipt"] is None
    assert manifest["config_fingerprint"] is None


def test_manifest_preserves_fixed_questions_when_all_runs_fail(tmp_path):
    result = deepcopy(RESULT)
    result["dev_runs"] = [
        {
            "case_id": case.case_id,
            "category": case.category,
            "profile": "dev",
            "status": "failed",
            "order": order,
            "error": {"type": "RuntimeError", "stage": "execution"},
        }
        for order, case in enumerate(QUESTION_CASES)
    ]
    result["selection"] = None
    result["default_run"] = None

    artifact_dir = write_artifacts(
        result,
        tmp_path,
        now=datetime(2026, 7, 19, 12, 1, tzinfo=timezone.utc),
    )

    manifest = json.loads((artifact_dir / "manifest.json").read_text())
    assert manifest["questions"] == {
        "schema_version": "1",
        "items": _declared_questions(),
    }


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
    unsafe_clamps = {
        "0": 1,
        "1": True,
        "2": -2,
        "3_plus": 3,
        "unknown": {"url": url, "secret": secret},
        "requested_confidence": 0.99,
    }
    result["dev_funnel"]["confidence_clamped_count"] = 4
    result["dev_funnel"]["confidence_clamped_by_source_count"] = unsafe_clamps
    run_funnel = result["dev_runs"][0]["signals"]["claim_funnel"]
    run_funnel["confidence_clamped_count"] = 4
    run_funnel["confidence_clamped_by_source_count"] = unsafe_clamps
    result["default_run"]["error"] = {
        "type": f"RuntimeError_{secret}",
        "stage": f"collection_{url}",
    }
    result["questions"] = {
        "schema_version": "1",
        "items": [
            *_declared_questions(),
            {
                "case_id": secret,
                "category": url,
                "question": report_text,
            },
        ],
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
    assert funnel["dev_funnel"]["confidence_clamped_count"] == 4
    assert funnel["dev_funnel"]["confidence_clamped_by_source_count"] == {
        "0": 1,
        "3_plus": 3,
    }
    assert "requested_confidence" not in serialized["funnel.json"]
    manifest = json.loads(serialized["manifest.json"])
    assert manifest["questions"]["items"] == _declared_questions()


def test_cli_exits_nonzero_without_writing_or_reporting_artifact_when_no_dev_run_completed(
    monkeypatch, capsys, tmp_path
):
    async def successful_preflight(*args):
        return None

    async def all_failed_sample(**kwargs):
        return {
            "schema_version": "1",
            "question_set_version": "mixed-v1",
            "questions": {
                "schema_version": "1",
                "items": _declared_questions(),
            },
            "dev_runs": [
                {"case_id": case.case_id, "status": "failed"}
                for case in QUESTION_CASES
            ],
            "selection": None,
            "default_run": None,
            "dev_funnel": {},
        }

    def unexpected_write(*args, **kwargs):
        pytest.fail("an unsuccessful sample must not write an artifact")

    monkeypatch.setattr(cli, "preflight", successful_preflight)
    monkeypatch.setattr(cli, "run_sample", all_failed_sample)
    monkeypatch.setattr(cli, "write_artifacts", unexpected_write)
    monkeypatch.setattr(
        sys,
        "argv",
        ["deep_analysis_funnel_sample", "--output-root", str(tmp_path)],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code != 0
    assert capsys.readouterr().out == ""
    assert list(tmp_path.iterdir()) == []


def test_cli_writes_execution_receipt_and_reraises_when_sample_run_fails(
    monkeypatch, tmp_path
):
    """The receipt must survive failure: a previous evaluation lost its exit
    status because nothing persisted it when the run itself blew up. This
    drives the script's real `_main`/`write_artifacts` — not a hand-built
    dict — so a future edit that removes the try/except fails this test."""

    async def successful_preflight(*args):
        return None

    async def failing_sample(**kwargs):
        raise RuntimeError("sample run exploded")

    monkeypatch.setattr(cli, "preflight", successful_preflight)
    monkeypatch.setattr(cli, "run_sample", failing_sample)
    monkeypatch.setattr(
        sys,
        "argv",
        ["deep_analysis_funnel_sample", "--output-root", str(tmp_path)],
    )

    with pytest.raises(RuntimeError, match="sample run exploded"):
        cli.main()

    artifact_dirs = list(tmp_path.iterdir())
    assert len(artifact_dirs) == 1
    manifest = json.loads((artifact_dirs[0] / "manifest.json").read_text())

    receipt = manifest["execution_receipt"]
    assert receipt is not None
    assert receipt["exit_status"] != 0
    assert receipt["started_at"]
    assert receipt["finished_at"]
    assert isinstance(receipt["pid"], int)

    assert manifest["config_fingerprint"] is not None
    assert manifest["config_fingerprint"]["runs"] == {}


def test_finalize_cassette_flushes_and_moves_into_artifact_dir(tmp_path):
    """`Cassette.save()` never runs implicitly -- if `_finalize_cassette`
    forgot to call it, the cassette would look captured while carrying
    nothing, which is worse than not recording at all."""
    cassette, cassette_tmp_dir = cli._new_recording_cassette()
    try:
        assert cassette.mode == "record"
        assert not cassette.path.exists()

        cassette._data["deadbeef"] = {"result": "cached"}
        artifact_dir = tmp_path / "artifact"
        artifact_dir.mkdir()

        cli._finalize_cassette(cassette, artifact_dir)

        assert not cassette.path.exists()
        persisted = json.loads((artifact_dir / "cassette.json").read_text())
        assert persisted == {"deadbeef": {"result": "cached"}}
    finally:
        shutil.rmtree(cassette_tmp_dir, ignore_errors=True)


async def _cached_value(value):
    return value


def test_main_threads_a_recording_cassette_through_build_orchestrator(
    monkeypatch, tmp_path
):
    """`execute_run` accepts `build_orchestrator_fn` and `build_orchestrator`
    accepts `cassette` -- this was previously believed to require editing
    `jobs.py`, which is wrong. The script should thread a cassette through
    with a `functools.partial`, and the recorded cassette must survive
    save + move into the artifact directory."""
    captured = {}

    async def successful_preflight(*args):
        return None

    async def fake_run_sample(**kwargs):
        execute_fn = kwargs["execute_fn"]
        captured["execute_fn"] = execute_fn
        build_fn = execute_fn.keywords["build_orchestrator_fn"]
        cassette = build_fn.keywords["cassette"]
        captured["cassette"] = cassette
        # Simulate the run recording at least one call during execution.
        await cassette.remember(
            "llm", {"prompt": "hi"}, lambda: _cached_value("cached")
        )
        return {
            "schema_version": "1",
            "question_set_version": "mixed-v1",
            "questions": {
                "schema_version": "1",
                "items": _declared_questions(),
            },
            "dev_runs": [_completed(QUESTION_CASES[0], "dev")],
            "selection": None,
            "default_run": None,
            "dev_funnel": {},
        }

    fake_run_id = QUESTION_CASES[0].case_id + "-run"
    fake_manifests = {
        fake_run_id: {
            "manifest_version": 1,
            "profile": "dev",
            "budget": {"global_token_cap": 140000},
        }
    }

    @asynccontextmanager
    async def fake_session_ctx():
        yield object()

    async def fake_manifests_for(session, run_ids):
        captured["manifests_for_run_ids"] = list(run_ids)
        return fake_manifests

    monkeypatch.setattr(cli, "preflight", successful_preflight)
    monkeypatch.setattr(cli, "run_sample", fake_run_sample)
    monkeypatch.setattr(cli, "get_session_ctx", fake_session_ctx)
    monkeypatch.setattr(cli, "manifests_for", fake_manifests_for)
    monkeypatch.setattr(
        sys,
        "argv",
        ["deep_analysis_funnel_sample", "--output-root", str(tmp_path)],
    )

    cli.main()

    assert captured["manifests_for_run_ids"] == [fake_run_id]

    build_fn = captured["execute_fn"].keywords["build_orchestrator_fn"]
    assert build_fn.func is cli.build_orchestrator
    assert captured["cassette"].mode == "record"

    artifact_dirs = list(tmp_path.iterdir())
    assert len(artifact_dirs) == 1
    cassette_path = artifact_dirs[0] / "cassette.json"
    assert cassette_path.exists()
    recorded = json.loads(cassette_path.read_text())
    assert recorded  # not empty -- the recorded call survived save + move

    # The seam this task introduces: what `manifests_for` returns must be
    # the thing that lands in the written manifest's config_fingerprint,
    # not merely be *called*. Without this, reverting the success path to
    # `_fingerprint({})` would leave the whole suite green.
    manifest = json.loads((artifact_dirs[0] / "manifest.json").read_text())
    assert manifest["config_fingerprint"]["runs"] == fake_manifests

    # The private temp directory is cleaned up, not left behind.
    assert not captured["cassette"].path.exists()
    assert not captured["cassette"].path.parent.exists()


def test_main_cleans_up_cassette_temp_dir_when_sample_raises(
    monkeypatch, tmp_path
):
    """Failure must not leak the private cassette temp directory, and the
    partially-recorded cassette should still be salvaged into the failure
    artifact rather than silently dropped."""
    captured = {}

    async def successful_preflight(*args):
        return None

    async def failing_sample(**kwargs):
        execute_fn = kwargs["execute_fn"]
        cassette = execute_fn.keywords["build_orchestrator_fn"].keywords[
            "cassette"
        ]
        captured["cassette"] = cassette
        await cassette.remember(
            "llm", {"prompt": "before crash"}, lambda: _cached_value("v")
        )
        raise RuntimeError("sample run exploded")

    monkeypatch.setattr(cli, "preflight", successful_preflight)
    monkeypatch.setattr(cli, "run_sample", failing_sample)
    monkeypatch.setattr(
        sys,
        "argv",
        ["deep_analysis_funnel_sample", "--output-root", str(tmp_path)],
    )

    with pytest.raises(RuntimeError, match="sample run exploded"):
        cli.main()

    artifact_dirs = list(tmp_path.iterdir())
    assert len(artifact_dirs) == 1
    cassette_path = artifact_dirs[0] / "cassette.json"
    assert cassette_path.exists()
    assert json.loads(cassette_path.read_text())

    assert not captured["cassette"].path.parent.exists()


def test_fingerprint_reports_ledger_manifests_without_credential_shaped_keys():
    """`_fingerprint` no longer recomputes config -- it just wraps whatever
    the ledger already handed it, alongside git identity, and never invents
    credential-shaped keys of its own."""
    manifests = {
        "run0001": {
            "profile": "dev",
            "budget": {"global_token_cap": 20000},
            "models": {"judge": {"model": "claude-sonnet-5"}},
        }
    }

    fingerprint = cli._fingerprint(manifests)

    assert fingerprint["manifest_version"] == cli.MANIFEST_VERSION
    assert fingerprint["runs"] == manifests
    assert "commit" in fingerprint["git"]

    serialized = json.dumps(fingerprint).lower()
    for forbidden in (
        "secret",
        "password",
        "credential",
        "api_key",
        "anthropic_api_key",
        "tavily_api_key",
    ):
        assert forbidden not in serialized


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
    assert result["questions"] == {
        "schema_version": "1",
        "items": [
            {
                "case_id": case.case_id,
                "category": case.category,
                "question": case.question,
            }
            for case in CASES
        ],
    }


@pytest.mark.asyncio
async def test_run_sample_preserves_all_declared_questions_with_mixed_failures():
    async def mixed(case, profile):
        if case == QUESTION_CASES[2]:
            raise RuntimeError("failed")
        return _completed(case, profile)

    result = await run_sample(
        cases=QUESTION_CASES, execute_case_fn=mixed, secrets=[]
    )

    assert result["questions"] == {
        "schema_version": "1",
        "items": _declared_questions(),
    }


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

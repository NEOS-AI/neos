import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from neos.workflow.deep_analysis.funnel_sample import QuestionCase
from neos.workflow.deep_analysis.funnel_sample_runner import (
    PreflightError,
    preflight,
    run_sample,
    sanitize_error,
)


CASES = (
    QuestionCase("first", "fact", "First?"),
    QuestionCase("second", "technical", "Second?"),
    QuestionCase("third", "causal_policy", "Third?"),
)


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


def test_sanitize_error_redacts_configured_secrets_and_truncates():
    error = RuntimeError("provider rejected sk-live-secret " + "x" * 500)
    assert sanitize_error(error, ["sk-live-secret"]) == {
        "type": "RuntimeError",
        "message": "provider rejected [REDACTED] " + "x" * 211,
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
        "message": "provider leaked [REDACTED]",
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

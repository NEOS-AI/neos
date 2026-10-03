"""Bounded execution and run-scoped collection for funnel samples."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any

from sqlalchemy import select, text

import neos.database.models  # noqa: F401 - register DARun's users FK target
from neos.config.settings import settings
from neos.database.connection import get_session_ctx
from neos.database.deep_analysis_models import DARun
from neos.workflow.deep_analysis.analytics import DeepAnalysisAnalyticsService
from neos.workflow.deep_analysis.funnel_sample import (
    QUESTION_CASES,
    QUESTION_SET_VERSION,
    QuestionCase,
    aggregate_funnels,
    select_representative,
    stage_metrics,
)
from neos.workflow.deep_analysis.jobs import execute_run
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.model_roles import (
    HARNESS_ROLES,
    resolve_harness_model,
)


class PreflightError(RuntimeError):
    """Raised when required production dependencies are unavailable."""


class _CreatedRunError(RuntimeError):
    """Preserve a committed run identifier and fixed failure stage."""

    def __init__(self, run_id: str, stage: str, cause: Exception) -> None:
        super().__init__(f"created run failed during {stage}")
        self.run_id = run_id
        self.stage = stage
        self.cause = cause


_RUN_METADATA_FIELDS = (
    "case_id",
    "category",
    "question",
    "profile",
    "status",
    "run_id",
    "elapsed_seconds",
    "tokens_spent",
    "order",
    "error",
)
_FUNNEL_FIELDS = (
    "proposed",
    "graded",
    "deterministic_passed",
    "deterministic_rejected",
    "agentic_attempted",
    "agentic_passed",
    "agentic_rejected",
    "agentic_skipped",
    "agentic_exhausted",
    "verified",
    "rejected",
    "unverified",
    "evidence_missing_rate",
    "source_dead_rate",
    "avg_evidence_count",
    "avg_source_count",
    "avg_excerpt_chars",
    "quote_score_buckets",
    "confidence_clamped_count",
    "confidence_clamped_by_source_count",
)
_QUOTE_BUCKETS = (
    "exact",
    "above_threshold",
    "near_miss",
    "low",
    "unavailable",
)
_CONFIDENCE_CLAMP_BUCKETS = ("0", "1", "2", "3_plus")
_ERROR_TYPE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_STAGES = {
    "proposal_to_grade",
    "deterministic_rejection",
    "agentic_loss",
    "final_unresolved",
}
_QUESTIONS_SCHEMA_VERSION = "1"


def _declared_questions(cases: Sequence[QuestionCase]) -> dict[str, Any]:
    return {
        "schema_version": _QUESTIONS_SCHEMA_VERSION,
        "items": [
            {
                "case_id": case.case_id,
                "category": case.category,
                "question": case.question,
            }
            for case in cases
        ],
    }


def _safe_run_metadata(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if run is None:
        return None
    metadata = {
        key: run[key]
        for key in _RUN_METADATA_FIELDS
        if key in run and key != "error"
    }
    error = run.get("error")
    if isinstance(error, dict):
        stage = error.get("stage", "execution")
        error_type = error.get("type")
        metadata["error"] = {
            "type": (
                error_type
                if isinstance(error_type, str)
                and _ERROR_TYPE_PATTERN.fullmatch(error_type)
                else "UnknownError"
            ),
            "stage": stage
            if stage in {"execution", "collection"}
            else "execution",
        }
    return metadata


def _safe_funnel(funnel: dict[str, Any]) -> dict[str, Any]:
    safe = {}
    for key in _FUNNEL_FIELDS:
        value = funnel.get(key)
        if key == "quote_score_buckets":
            if isinstance(value, dict):
                safe[key] = {
                    bucket: count
                    for bucket in _QUOTE_BUCKETS
                    if (count := value.get(bucket)) is not None
                    and _is_safe_number(count)
                }
        elif key == "confidence_clamped_by_source_count":
            if isinstance(value, dict):
                safe[key] = {
                    bucket: count
                    for bucket in _CONFIDENCE_CLAMP_BUCKETS
                    if (count := value.get(bucket)) is not None
                    and _is_safe_count(count)
                }
        elif _is_safe_number(value):
            safe[key] = value
    return safe


def _is_safe_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _is_safe_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _safe_selection(selection: Any) -> dict[str, Any] | None:
    if not isinstance(selection, dict):
        return None
    safe = {
        key: selection[key]
        for key in ("case_id", "dev_order")
        if key in selection
    }
    stage = selection.get("dominant_stage")
    safe["dominant_stage"] = stage if stage in _STAGES else "none"
    return safe


def _run_funnel(run: dict[str, Any]) -> dict[str, Any]:
    signals = run.get("signals")
    if not isinstance(signals, dict):
        return {}
    funnel = signals.get("claim_funnel")
    return _safe_funnel(funnel) if isinstance(funnel, dict) else {}


def render_report(result: dict[str, Any]) -> str:
    """Render a concise report from the artifact-safe evaluation fields."""
    raw_runs = [*result.get("dev_runs", [])]
    if result.get("default_run") is not None:
        raw_runs.append(result["default_run"])
    runs = [
        {**(_safe_run_metadata(run) or {}), "claim_funnel": _run_funnel(run)}
        for run in raw_runs
    ]
    rows = []
    for run in runs:
        funnel = run["claim_funnel"]
        rows.append(
            "| {case_id} | {profile} | {status} | {elapsed} | {tokens} | "
            "{proposed} | {graded} | {verified} | {rejected} | {unverified} |".format(
                case_id=run.get("case_id", "-"),
                profile=run.get("profile", "-"),
                status=run.get("status", "-"),
                elapsed=run.get("elapsed_seconds", "-"),
                tokens=run.get("tokens_spent", "-"),
                proposed=funnel.get("proposed", 0),
                graded=funnel.get("graded", 0),
                verified=funnel.get("verified", 0),
                rejected=funnel.get("rejected", 0),
                unverified=funnel.get("unverified", 0),
            )
        )

    aggregate = _safe_funnel(result.get("dev_funnel", {}))
    selection = _safe_selection(result.get("selection")) or {}
    stage = selection.get("dominant_stage", "none")
    metrics = stage_metrics(aggregate)
    stage_metric = metrics.get(stage, {"count": 0, "rate": 0.0})
    buckets = aggregate.get("quote_score_buckets", {})
    failures = [
        f"{run.get('case_id', '-')}/{run.get('profile', '-')}: "
        f"{run['error'].get('type', 'Exception')} at {run['error'].get('stage', 'execution')}"
        for run in runs
        if isinstance(run.get("error"), dict)
    ]
    failure_lines = "\n".join(f"- {failure}" for failure in failures) or "- None"
    default_funnel = runs[-1]["claim_funnel"] if result.get("default_run") else {}
    selected_dev = next(
        (
            run
            for run in runs[: len(result.get("dev_runs", []))]
            if run.get("case_id") == selection.get("case_id")
        ),
        {},
    )
    dev_funnel = selected_dev.get("claim_funnel", {})
    delta_fields = ("proposed", "graded", "verified", "rejected", "unverified")
    deltas = ", ".join(
        f"{field}={default_funnel.get(field, 0) - dev_funnel.get(field, 0)}"
        for field in delta_fields
    )
    return (
        "# Deep-analysis claim funnel sample\n\n"
        "| Case ID | Profile | Status | Elapsed seconds | Tokens | Proposed | Graded | Verified | Rejected | Unverified |\n"
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        + "\n".join(rows)
        + "\n\n"
        f"- Dominant loss stage: `{stage}` — {stage_metric['count']} "
        f"({stage_metric['rate']:.1%})\n"
        f"- Quote buckets: {json.dumps(buckets, sort_keys=True)}\n"
        f"- Evidence missing rate: {aggregate.get('evidence_missing_rate', 0):.1%}\n"
        f"- Source dead rate: {aggregate.get('source_dead_rate', 0):.1%}\n"
        f"- Default minus dev deltas: {deltas}\n\n"
        "## Failures\n\n"
        f"{failure_lines}\n\n"
        "The stages overlap, and no policy was changed.\n"
    )


def write_artifacts(
    result: dict[str, Any],
    output_root: Path,
    now: datetime | None = None,
    *,
    receipt: dict[str, Any] | None = None,
    fingerprint: dict[str, Any] | None = None,
) -> Path:
    """Write a new timestamped artifact directory without overwriting."""
    timestamp = now or datetime.now(timezone.utc)
    artifact_dir = output_root / timestamp.astimezone(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    artifact_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": result.get("schema_version"),
        "question_set_version": result.get("question_set_version"),
        "questions": _declared_questions(QUESTION_CASES),
        "dev_runs": [
            _safe_run_metadata(run) for run in result.get("dev_runs", [])
        ],
        "default_run": _safe_run_metadata(result.get("default_run")),
        "execution_receipt": receipt,
        "config_fingerprint": fingerprint,
    }
    funnel = {
        "dev_runs": [
            {
                "case_id": run.get("case_id"),
                "profile": run.get("profile"),
                "claim_funnel": _run_funnel(run),
            }
            for run in result.get("dev_runs", [])
        ],
        "selection": _safe_selection(result.get("selection")),
        "default_run": {
            "case_id": (result.get("default_run") or {}).get("case_id"),
            "profile": (result.get("default_run") or {}).get("profile"),
            "claim_funnel": _run_funnel(result.get("default_run") or {}),
        },
        "dev_funnel": _safe_funnel(result.get("dev_funnel", {})),
    }
    json_options = {
        "ensure_ascii": False,
        "indent": 2,
        "sort_keys": True,
        "default": str,
    }
    (artifact_dir / "manifest.json").write_text(
        json.dumps(manifest, **json_options) + "\n"
    )
    (artifact_dir / "funnel.json").write_text(
        json.dumps(funnel, **json_options) + "\n"
    )
    (artifact_dir / "report.md").write_text(render_report(result))
    return artifact_dir


#: 프로브가 요청하는 출력 상한. 작을수록 싸지만, adaptive thinking 모델이
#: 지나치게 작은 상한을 거절할 수 있어 넉넉히 잡는다. 거절되면 preflight 는
#: **실패**하고, 그 방향이 옳다 -- 거짓 경보는 되돌릴 수 있지만 거짓 통과는
#: 표본 하나를 태우고 §10.2 때문에 다시 뜰 기회가 없다.
PROBE_MAX_TOKENS = 64

_CREDENTIAL_NAMES = (
    "ANTHROPIC_API_KEY",
    "TAVILY_API_KEY",
    "OPENAI_API_KEY",
)

#: 라이브 표본이 요구하는 시크릿. 다른 호출자는 자기 것을 넘긴다 --
#: discard-recall 채점은 검색을 하지 않으므로 `TAVILY_API_KEY` 가 없어도
#: 돌아야 하고, 없는 것을 요구하면 사람이 검사를 끄는 법을 배운다.
SAMPLE_CREDENTIALS: tuple[str, ...] = ("ANTHROPIC_API_KEY", "TAVILY_API_KEY")


def harness_models() -> tuple[str, ...]:
    """하네스 역할 넷이 실제로 부르는 **고유** 모델 이름.

    역할 넷이 늘 모델 넷은 아니다 -- 배포에서 `dig` 와 `synth` 는 같은
    opus-5 다. 중복을 접는 것은 비용 때문이 아니라, 역할 수와 모델 수가
    다르다는 사실이 이 함수의 출력에서 보여야 하기 때문이다(E3 가 깨졌을
    때 넷이 하나로 수렴한다).
    """
    return tuple(
        sorted({resolve_harness_model(role).model for role in HARNESS_ROLES})
    )


def _redact(message: str, secrets: Iterable[str | None]) -> str:
    """예외 문구에서 알려진 시크릿 값을 지운다.

    프로바이더 예외는 요청을 통째로 물고 오기도 한다. P1 #8 이 같은 종류의
    누출을 한 번 치렀다 -- `exc_info=True` 하나가 접속 문자열을 로그로
    흘렸고, 그것을 잡은 것은 저장소의 기존 테스트였다.
    """
    for secret in secrets:
        if secret:
            message = message.replace(secret, "<redacted>")
    return message


async def _probe_model(model: str) -> None:
    """모델 하나에 가장 작은 호출을 보낸다. 응답이 오면 살아 있는 것이다.

    키가 **있는지**가 아니라 **먹히는지**를 본다. D88 이 그 차이에 걸렸다 --
    `OPENAI_API_KEY` 는 존재했고 401 이었고 preflight 는 통과했으며, 판정자가
    못 도는 것은 편향보다 나쁘다(못 돈 판정자는 통과처럼 보인다, §8.1.1).

    카탈로그에 새로 등재한 모델의 **서빙 가능 여부**도 여기서 걸린다. E3 가
    `claude-opus-4-8` 을 넣었을 때 검증되지 않은 채 남은 것이 그것이다.

    런 밖에서 돈다. `active_token_budget()` 이 없으므로 `reserve()` 를 거치지
    않고, 그래서 어느 런의 floor 산식도 건드리지 않는다 -- 이 호출의 토큰은
    표본 회계 밖에 있고 그것이 의도다.
    """
    from neos.workflow.deep_analysis.llm import call_llm

    await call_llm(
        model,
        "ping",
        max_tokens=PROBE_MAX_TOKENS,
        stage="preflight",
        # 모델 단위 프로브다 -- 역할마다 다를 수 있는 사고량은 여기서 묻지 않는다.
        effort=None,
    )


async def _probe_jev_judge(jev_config) -> None:
    """L6 판정자(D99)에 가장 작은 판정 하나를 보낸다 -- D94 를 Jev 에도.

    `build_claim_judge` 를 그대로 쓴다. 런이 만들 판정자와 같은 것을 찔러야
    "프로브는 통과했는데 런의 판정자는 다르다"가 생기지 않는다.
    """
    from neos.jev.assembly import build_claim_judge

    judge = build_claim_judge(jev_config)
    await judge.judge("preflight", [])


async def preflight(
    settings_obj,
    session_factory,
    *,
    probe: Callable[[str], Awaitable[None]] = _probe_model,
    models: Sequence[str] | None = None,
    credentials: Sequence[str] | None = None,
    jev_probe: Callable[[Any], Awaitable[None]] = _probe_jev_judge,
) -> None:
    """LLM 토큰을 태우기 전에 의존성이 **실제로 작동하는지** 확인한다.

    셋을 본다: 시크릿의 존재, DB 도달, 그리고 부를 모든 모델이 응답한다는
    것. 셋째가 2026-08-30 에 더해졌다 -- 그날 preflight 는 통과했는데 세
    역할 전부가 401 이었다.

    `models` 와 `credentials` 가 열려 있는 것은 **호출자가 둘이기 때문이다**
    (PREFLIGHT2). discard-recall 채점(`scripts/deep_analysis_discard_recall.py`)
    은 판정자 하나만 부르고 검색을 하지 않으므로 다른 집합을 넘긴다. 그 두
    번째 호출자는 이 함수가 D94 로 고쳐진 뒤에도 **자기 사본을 들고 존재만
    검사하고 있었다** -- 사본이 남아 있으면 고침은 한 곳에만 도착한다.
    """
    required = (
        SAMPLE_CREDENTIALS if credentials is None else tuple(credentials)
    )
    if not required:
        # 빈 모델 집합과 같은 이유로 실패다: 요구할 것이 없다는 것은 검사가
        # 성립하지 않는다는 뜻이지 통과가 아니다.
        raise PreflightError(
            "no credential to check -- preflight would pass vacuously"
        )
    missing = [
        name for name in required if not getattr(settings_obj, name, None)
    ]
    if missing:
        raise PreflightError(
            "missing required credentials: " + ", ".join(missing)
        )
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))

    targets = tuple(harness_models() if models is None else models)
    if not targets:
        # 잴 것이 없는 것은 통과가 아니다. 빈 집합은 역할 해석이 깨졌다는
        # 뜻이고, 그것을 통과로 읽으면 이 검사가 없애려는 침묵이 그대로
        # 돌아온다 -- 검사가 있다고 믿는 만큼 더 나쁘다.
        raise PreflightError(
            "no harness model to probe -- role resolution produced none"
        )

    secrets = [getattr(settings_obj, name, None) for name in _CREDENTIAL_NAMES]
    failures: list[str] = []
    for model in targets:
        # 첫 실패에서 멈추지 않는다. 프로브는 표본 전에 도는 값싼 호출이고,
        # 하나씩 알려주면 사람이 그 왕복을 모델 수만큼 반복한다.
        try:
            await probe(model)
        except Exception as exc:  # noqa: BLE001 - 사유를 가리지 않고 전부 보고
            detail = _redact(str(exc), secrets) or type(exc).__name__
            failures.append(f"{model} ({type(exc).__name__}: {detail})")

    # L6 (D99): 판정자가 Jev 면 그것도 실제로 대답해야 한다. 꺼져 있으면 부르지 않는다.
    jev_config = getattr(getattr(settings_obj, "config", None), "jev", None)
    if jev_config is not None and jev_config.enabled and jev_config.judge_enabled:
        try:
            await jev_probe(jev_config)
        except Exception as exc:  # noqa: BLE001 - 사유를 가리지 않고 전부 보고
            detail = _redact(str(exc), secrets) or type(exc).__name__
            failures.append(f"jev judge {jev_config.model} ({type(exc).__name__}: {detail})")

    if failures:
        raise PreflightError(
            "credentials are present but these models did not answer: "
            + "; ".join(failures)
        )


def sanitize_error(
    exc: Exception, secrets: Iterable[str | None]
) -> dict[str, str]:
    del secrets
    source = exc.cause if isinstance(exc, _CreatedRunError) else exc
    stage = getattr(exc, "stage", "execution")
    if stage not in {"execution", "collection"}:
        stage = "execution"
    return {"type": type(source).__name__, "stage": stage}


async def execute_case(
    case: QuestionCase,
    profile: str,
    *,
    session_factory=get_session_ctx,
    execute_fn=execute_run,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Execute one committed run and collect only run-scoped observations."""
    run_id: str | None = None
    stage = "execution"
    try:
        async with session_factory() as session:
            run_id = await create_run(
                session, case.question, profile
            )
            await session.commit()

        started = time.monotonic()
        await execute_fn(
            session_factory,
            run_id,
            case.question,
            profile,
            timeout_seconds=(
                settings.config.deep_analysis.job_time_limit
                if timeout_seconds is None
                else timeout_seconds
            ),
        )
        elapsed = time.monotonic() - started

        stage = "collection"
        async with session_factory() as session:
            status = await session.scalar(
                select(DARun.status).where(DARun.id == run_id)
            )
            signals = await DeepAnalysisAnalyticsService(session).signals(
                run_id=run_id
            )
            tokens_spent = await Ledger(session, run_id).total_spent()

        return {
            "case_id": case.case_id,
            "category": case.category,
            "question": case.question,
            "profile": profile,
            "status": status,
            "run_id": run_id,
            "elapsed_seconds": elapsed,
            "tokens_spent": tokens_spent,
            "signals": signals,
        }
    except Exception as exc:
        if run_id is None:
            raise
        raise _CreatedRunError(run_id, stage, exc) from exc


async def run_sample(
    *,
    cases: Sequence[QuestionCase] = QUESTION_CASES,
    execute_case_fn: Callable[
        [QuestionCase, str], Awaitable[dict[str, Any]]
    ] | None = None,
    session_factory=get_session_ctx,
    execute_fn=execute_run,
    timeout_seconds: float | None = None,
    secrets: Iterable[str | None] | None = None,
) -> dict[str, Any]:
    """Run dev cases sequentially and rerun one representative at default."""
    if execute_case_fn is None:

        async def execute_case_fn(
            case: QuestionCase, profile: str
        ) -> dict[str, Any]:
            return await execute_case(
                case,
                profile,
                session_factory=session_factory,
                execute_fn=execute_fn,
                timeout_seconds=timeout_seconds,
            )

    configured_secrets = (
        [settings.ANTHROPIC_API_KEY, settings.TAVILY_API_KEY]
        if secrets is None
        else list(secrets)
    )
    dev_runs: list[dict[str, Any]] = []
    for order, case in enumerate(cases):
        try:
            observation = await execute_case_fn(case, "dev")
            dev_runs.append({**observation, "order": order})
        except Exception as exc:
            failed = {
                "case_id": case.case_id,
                "category": case.category,
                "profile": "dev",
                "status": "failed",
                "order": order,
            }
            run_id = getattr(exc, "run_id", None)
            if run_id:
                failed["run_id"] = run_id
            failed["error"] = sanitize_error(exc, configured_secrets)
            dev_runs.append(failed)

    selected = select_representative(dev_runs)
    default_run = None
    selection = None
    if selected is not None:
        selected_case = next(
            case for case in cases if case.case_id == selected["case_id"]
        )
        selection = {
            "case_id": selected["case_id"],
            "dominant_stage": selected["dominant_stage"],
            "dev_order": selected["order"],
        }
        try:
            default_run = await execute_case_fn(selected_case, "default")
        except Exception as exc:
            default_run = {
                "case_id": selected_case.case_id,
                "category": selected_case.category,
                "profile": "default",
                "status": "failed",
                **(
                    {"run_id": exc.run_id}
                    if getattr(exc, "run_id", None)
                    else {}
                ),
                "error": sanitize_error(exc, configured_secrets),
            }

    completed_funnels = [
        item["signals"]["claim_funnel"]
        for item in dev_runs
        if item["status"] == "completed"
    ]
    return {
        "schema_version": "1",
        "question_set_version": QUESTION_SET_VERSION,
        "questions": _declared_questions(cases),
        "dev_runs": dev_runs,
        "selection": selection,
        "default_run": default_run,
        "dev_funnel": aggregate_funnels(completed_funnels),
    }

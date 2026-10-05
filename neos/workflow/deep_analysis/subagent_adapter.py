"""Opt-in DA host for SubagentRuntime. Orchestrator is the only writer."""

from __future__ import annotations

import inspect
import json
from typing import Any, Mapping

from neos.coding.model.base import ToolDefinition
from neos.subagent.types import (
    ModelPin,
    ParentBriefing,
    ParentKind,
    SandboxMode,
    StepKind,
    StepOutcome,
    SubagentTicket,
)

from .assignment import render_repair_lines
from .harness_bridge import da_provider_for_model
from .model_roles import resolve_harness_model
from .models import Assignment, WorkerResult

SUBAGENT_STEP = "subagent_step"
_ALLOWED_TOOLS = frozenset({"search", "fetch"})
_PROVIDERS = frozenset({"anthropic", "openai", "gemini", "ollama"})
_HARNESS_ROLES = frozenset({"scout", "dig", "synth"})
_MAX_TOOL_BODY = 32 * 1024

_SEARCH = ToolDefinition(
    name="search",
    description="Search the web. Returns titled URL hits.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "k": {"type": "integer"},
        },
        "required": ["query"],
    },
)
_FETCH = ToolDefinition(
    name="fetch",
    description="Fetch a URL and return its text body.",
    input_schema={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
)


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _clip(value: object) -> object:
    if isinstance(value, str) and len(value) > _MAX_TOOL_BODY:
        return value[:_MAX_TOOL_BODY]
    return value


class DAToolPort:
    """search/fetch only. No sandbox, edit, write, execute, or approval."""

    def __init__(self, search_fn, fetch_fn) -> None:
        self._search_fn = search_fn
        self._fetch_fn = fetch_fn

    def definitions(self) -> tuple[ToolDefinition, ...]:
        tools: list[ToolDefinition] = []
        if self._search_fn is not None:
            tools.append(_SEARCH)
        if self._fetch_fn is not None:
            tools.append(_FETCH)
        return tuple(tools)

    async def execute(
        self, name: str, input: Mapping[str, object]
    ) -> Mapping[str, Any]:
        if name not in _ALLOWED_TOOLS:
            return {"error": "tool_not_allowed"}
        payload = dict(input) if isinstance(input, Mapping) else {}
        try:
            if name == "search":
                return await self._search(payload)
            return await self._fetch(payload)
        except Exception as exc:
            return {"error": str(exc)}

    async def _search(self, payload: Mapping[str, object]) -> Mapping[str, Any]:
        if self._search_fn is None:
            return {"error": "tool_not_allowed"}
        query = str(payload.get("query") or "")
        raw_k = payload.get("k", 5)
        try:
            limit = int(raw_k) if raw_k is not None else 5
        except (TypeError, ValueError):
            limit = 5
        results = await _maybe_await(self._search_fn(query, k=limit))
        return {"results": results}

    async def _fetch(self, payload: Mapping[str, object]) -> Mapping[str, Any]:
        if self._fetch_fn is None:
            return {"error": "tool_not_allowed"}
        url = str(payload.get("url") or "")
        blob = await _maybe_await(self._fetch_fn(url))
        if isinstance(blob, Mapping):
            return {
                key: _clip(value)
                for key, value in blob.items()
                if key
                in {"source_url", "url", "http_status", "content_hash", "raw_text"}
            }
        return {
            "source_url": getattr(blob, "source_url", url),
            "http_status": getattr(blob, "http_status", 0),
            "content_hash": getattr(blob, "content_hash", ""),
            "raw_text": _clip(getattr(blob, "raw_text", "")),
        }


def _model_pin(assignment: Assignment) -> ModelPin:
    role = (
        assignment.effort.value
        if assignment.effort.value in _HARNESS_ROLES
        else "scout"
    )
    resolved = resolve_harness_model(role)
    provider = da_provider_for_model(resolved.model)
    if provider not in _PROVIDERS:
        provider = resolved.provider if resolved.provider in _PROVIDERS else "anthropic"
    return ModelPin(provider=provider, model=resolved.model)


def compose_model_pin() -> ModelPin:
    """J4 (D105). compose 스펙의 역할은 `synth` 다(계약 §2) -- `_model_pin` 과 같은 해석을 탄다."""
    resolved = resolve_harness_model("synth")
    provider = da_provider_for_model(resolved.model)
    if provider not in _PROVIDERS:
        provider = resolved.provider if resolved.provider in _PROVIDERS else "anthropic"
    return ModelPin(provider=provider, model=resolved.model)


def _build_ticket(
    assignment: Assignment,
    *,
    spec: str,
    parent_id: str,
    run_id: str | None = None,
    expected_checkpoint_id: str | None = None,
    briefing: ParentBriefing | None = None,
) -> SubagentTicket:
    """스펙만 다르고 나머지는 같다 -- 티켓을 두 벌 적으면 둘이 갈라진다."""
    goal = (assignment.question_text or assignment.brief or "").strip()
    return SubagentTicket(
        parent_kind=ParentKind.DEEP_ANALYSIS,
        parent_id=parent_id,
        parent_run_id=parent_id,
        parent_tool_call_id=assignment.question_id,
        spec=spec,
        briefing=briefing or ParentBriefing(goal=goal),
        model=_model_pin(assignment),
        sandbox_mode=SandboxMode.NONE,
        run_id=run_id,
        expected_checkpoint_id=expected_checkpoint_id,
    )


def build_explore_ticket(
    assignment: Assignment,
    *,
    parent_id: str,
    run_id: str | None = None,
    expected_checkpoint_id: str | None = None,
) -> SubagentTicket:
    return _build_ticket(
        assignment,
        spec="explore",
        parent_id=parent_id,
        run_id=run_id,
        expected_checkpoint_id=expected_checkpoint_id,
    )


#: briefing 의 `why` 머리말. 계산 클레임의 `premises` 는 원장 claim_id 여야
#: 하고(계약 §5 규칙 2), 자식이 그 ID 를 알 길은 여기뿐이다.
VERIFIED_HEADER = (
    "이 질문에서 이미 verified 된 인용 클레임이다. 다시 조사하지 마라. "
    "계산 클레임의 premises 에는 아래 줄 맨 앞의 ID 를 그대로 쓴다."
)
#: briefing 의 `scope` 머리말. 줄 모양은 `worker_brief` 의 repairs 와 같다.
REPAIRS_HEADER = "이전 제출에서 거절된 클레임이다. 먼저 수선하라 (claim_id | code | detail | 처방 | salvage)."


def research_briefing(
    assignment: Assignment,
    *,
    verified: tuple[tuple[str, str], ...] = (),
    dead_ends: tuple[str, ...] = (),
) -> ParentBriefing:
    """조사 자식의 briefing (J1.5).

    전에는 `goal = question_text or brief` 하나였다 -- brief 가 싣던 확정된
    발견·막다른 길·수선 지시가 **전부 버려졌다.** 재조사는 같은 길을 되풀이했고,
    무엇보다 자식은 verified 클레임의 ID 를 볼 수 없어 **유효한 계산 클레임을
    하나도 쓸 수 없었다**(premises 가 가리킬 것이 없다).

    `worker_brief` 를 통째로 넘기지 않는 이유: 그 프롬프트는 "JSON 외 출력
    금지" 로 끝나는 옛 워커의 출력 계약을 싣고 있고, 조사 자식의 출력 계약은
    `submit.v1` 이다(계약 §3.4). 필요한 재료만 옮긴다.

    `verified` 는 (claim_id, text) 이고 **quote 클레임만** 온다 -- 계산 위에
    계산을 쌓지 못하게 하는 규칙 2 를, 고르는 자리에서부터 지킨다.
    """
    goal = (assignment.question_text or assignment.brief or "").strip()
    why = (
        VERIFIED_HEADER
        + "\n"
        + "\n".join(f"{claim_id} | {text}" for claim_id, text in verified)
        if verified
        else ""
    )
    repairs = list(assignment.repairs or [])
    scope = (
        REPAIRS_HEADER + "\n" + render_repair_lines(repairs) if repairs else ""
    )
    return ParentBriefing(
        goal=goal,
        why=why,
        already_tried=tuple(dead_ends),
        scope=scope,
    )


def build_research_ticket(
    assignment: Assignment,
    *,
    parent_id: str,
    run_id: str | None = None,
    expected_checkpoint_id: str | None = None,
    briefing: ParentBriefing | None = None,
) -> SubagentTicket:
    """트랙 J. `research` 스펙이 도구 목록을 정한다 (계약 §2).

    `sandbox_mode` 가 explore 와 같은 `NONE` 인 것은 우연이 아니다 -- 조사
    자식의 샌드박스는 서브에이전트 런타임이 아니라 오케스트레이터가
    `research-offline-v1` 로 띄운다.

    `briefing` 은 `research_briefing` 이 짓는다. 비우면 goal 만 있는 옛
    모양이다 -- explore 티켓은 여전히 그 모양이다(S9: 그 경로의 바이트는
    움직이지 않는다).
    """
    return _build_ticket(
        assignment,
        spec="research",
        parent_id=parent_id,
        run_id=run_id,
        expected_checkpoint_id=expected_checkpoint_id,
        briefing=briefing,
    )


def _coerce_event(item) -> tuple[str, str | None, Mapping[str, Any]]:
    if isinstance(item, Mapping):
        payload = item.get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        return str(item.get("kind") or ""), item.get("qid"), payload
    kind, qid, payload = item
    if isinstance(payload, str):
        payload = json.loads(payload)
    return str(kind), qid, payload


async def latest_subagent_pointers(
    ledger, question_id: str
) -> tuple[str | None, str | None]:
    events = getattr(ledger, "events", None)
    if isinstance(events, list):
        for item in reversed(events):
            kind, qid, payload = _coerce_event(item)
            if kind != SUBAGENT_STEP or qid != question_id:
                continue
            if not isinstance(payload, Mapping):
                continue
            run_id = payload.get("run_id")
            checkpoint_id = payload.get("checkpoint_id")
            return (
                str(run_id) if run_id else None,
                str(checkpoint_id) if checkpoint_id else None,
            )
        return None, None

    db = getattr(ledger, "db", None)
    run_id = getattr(ledger, "run_id", None)
    if db is None or not run_id:
        return None, None

    from sqlalchemy import select

    from neos.database.deep_analysis_models import DAEvent

    raw = await db.scalar(
        select(DAEvent.payload)
        .where(
            DAEvent.run_id == run_id,
            DAEvent.kind == SUBAGENT_STEP,
            DAEvent.qid == question_id,
        )
        .order_by(DAEvent.seq.desc())
        .limit(1)
    )
    if not raw:
        return None, None
    payload = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(payload, Mapping):
        return None, None
    child_run = payload.get("run_id")
    checkpoint_id = payload.get("checkpoint_id")
    return (
        str(child_run) if child_run else None,
        str(checkpoint_id) if checkpoint_id else None,
    )


async def log_subagent_step(
    ledger,
    question_id: str,
    *,
    run_id: str,
    checkpoint_id: str | None,
    step_kind: str,
    status: str,
) -> None:
    await ledger.log(
        SUBAGENT_STEP,
        question_id,
        {
            "run_id": run_id,
            "checkpoint_id": checkpoint_id,
            "step_kind": step_kind,
            "status": status,
        },
    )


def _empty_result(
    assignment: Assignment,
    *,
    status: str,
    fail_reason: str = "",
    brief: str = "",
    tokens_spent: int = 0,
    outcome: StepOutcome | None = None,
) -> WorkerResult:
    return WorkerResult(
        question_id=assignment.question_id,
        status=status,
        claims=[],
        unverified_brief=brief,
        fail_reason=fail_reason,
        tokens_spent=tokens_spent,
        subagent_run_id=outcome.run_id if outcome is not None else "",
        subagent_checkpoint_id=(
            outcome.checkpoint_id or "" if outcome is not None else ""
        ),
        subagent_step_kind=outcome.kind.value if outcome is not None else "",
    )


def build_da_subagent_runtime(*, search_fn, fetch_fn, session_factory, model=None):
    """Production host. Caller supplies a session factory."""
    return _build_runtime(
        DAToolPort(search_fn, fetch_fn),
        session_factory=session_factory,
        model=model,
    )


def build_research_runtime(port, *, session_factory, model=None):
    """트랙 J. 포트만 다르고 나머지는 `build_da_subagent_runtime` 과 같다.

    **질문마다 새로 짓는다.** 포트가 질문마다 다르기 때문에 공유할 수 없고,
    `SubagentRuntime.__init__` 이 순수 대입이라 질문마다 지어도 싸다.
    """
    return _build_runtime(port, session_factory=session_factory, model=model)


def build_compose_runtime(port, *, session_factory, model=None):
    """J4 (D105). research 런타임과 같은 조립이되 모델이 `synth` 역할이다."""
    if model is None:
        from neos.utils.llm_factory import create_coding_model

        from .harness_bridge import da_provider_for_model as _provider_for
        from .model_roles import resolve_harness_model as _resolve

        resolved = _resolve("synth")
        model = create_coding_model(provider=_provider_for(resolved.model))
    return _build_runtime(port, session_factory=session_factory, model=model)


def _build_runtime(port, *, session_factory, model=None):
    """런타임 조립은 한 곳이다 -- 두 벌이면 한쪽만 고쳐지는 날이 온다."""

    from neos.observability.metrics import get_metrics_collector
    from neos.subagent.catalog import SpecRegistry
    from neos.subagent.metrics import MetricsEventSink
    from neos.subagent.ports import SystemClock
    from neos.subagent.postgres import PostgresSubagentStore
    from neos.subagent.runtime import SubagentRuntime
    from neos.subagent.stepper import ChildStepper
    from neos.utils.llm_factory import create_coding_model

    from .harness_bridge import da_provider_for_model
    from .model_roles import resolve_harness_model

    if model is None:
        resolved = resolve_harness_model("dig")
        model = create_coding_model(provider=da_provider_for_model(resolved.model))
    return SubagentRuntime(
        store=PostgresSubagentStore(session_factory),
        catalog=SpecRegistry(),
        stepper=ChildStepper(model=model, tools=port),
        events=MetricsEventSink(_NullSink(), get_metrics_collector()),
        clock=SystemClock(),
    )


class _NullSink:
    async def emit(self, event_type: str, payload) -> None:
        del event_type, payload


async def investigate_via_subagent(
    *,
    runtime,
    assignment: Assignment,
    parent_id: str,
    run_id: str | None = None,
    expected_checkpoint_id: str | None = None,
) -> WorkerResult:
    """One `advance` per call. Does not read or write the ledger."""

    goal = (assignment.question_text or assignment.brief or "").strip()
    if not goal:
        return _empty_result(
            assignment, status="failed", fail_reason="subagent_briefing_empty"
        )

    ticket = build_explore_ticket(
        assignment,
        parent_id=parent_id,
        run_id=run_id,
        expected_checkpoint_id=expected_checkpoint_id,
    )
    try:
        outcome = await runtime.advance(ticket)
    except Exception as exc:  # noqa: BLE001 — same fence as _run_legacy_worker
        return _empty_result(
            assignment,
            status="failed",
            fail_reason=str(exc) or type(exc).__name__,
        )
    if outcome.kind is StepKind.CONTINUING:
        return _empty_result(
            assignment,
            status="partial",
            tokens_spent=outcome.tokens_delta,
            outcome=outcome,
        )

    try:
        folded = await runtime.fold(outcome.run_id)
    except Exception as exc:  # noqa: BLE001
        return _empty_result(
            assignment,
            status="failed",
            fail_reason=str(exc) or type(exc).__name__,
            tokens_spent=outcome.tokens_delta,
            outcome=outcome,
        )
    if outcome.kind is StepKind.COMPLETED:
        return WorkerResult(
            question_id=assignment.question_id,
            status="completed",
            claims=[],
            unverified_brief=folded.summary,
            tokens_spent=outcome.tokens_delta,
            model=ticket.model.model,
            subagent_run_id=outcome.run_id,
            subagent_checkpoint_id=outcome.checkpoint_id or "",
            subagent_step_kind=outcome.kind.value,
        )
    return _empty_result(
        assignment,
        status="failed",
        fail_reason=outcome.error_code or outcome.kind.value,
        brief=folded.summary,
        tokens_spent=outcome.tokens_delta,
        outcome=outcome,
    )

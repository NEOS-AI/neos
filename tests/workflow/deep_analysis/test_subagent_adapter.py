from __future__ import annotations

from pathlib import Path

import pytest

from neos.coding.model.base import ModelCompleted, ModelUsage, TextDelta, ToolCallCompleted
from neos.config.settings import settings
from neos.subagent.catalog import SpecRegistry
from neos.subagent.memory import InMemorySubagentStore
from neos.subagent.ports import SystemClock
from neos.subagent.runtime import SubagentRuntime
from neos.subagent.stepper import ChildStepper
from neos.subagent.types import (
    FoldedResult,
    ParentKind,
    SandboxMode,
    StepKind,
    StepOutcome,
    SubagentStatus,
)
from neos.workflow.deep_analysis.models import Assignment, Effort, WorkerResult
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.coding.model.errors import CodingModelError
from neos.workflow.deep_analysis.subagent_adapter import (
    DAToolPort,
    investigate_via_subagent,
    log_subagent_step,
)


pytestmark = pytest.mark.no_db

_ADAPTER = Path("neos/workflow/deep_analysis/subagent_adapter.py")
_ORCH = Path("neos/workflow/deep_analysis/orchestrator.py")
_FORBIDDEN = (
    "DurableCodingLoop",
    "LoopDependencies",
    "ChannelGateway",
    "neos.coding.loop",
    "neos.coding.sandbox",
    "neos.coding.repositories",
)


class ScriptedCodingModel:
    def __init__(self, script) -> None:
        self.script = [tuple(turn) for turn in script]
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        if not self.script:
            raise RuntimeError("model_script_exhausted")
        for event in self.script.pop(0):
            yield event


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event_type: str, payload) -> None:
        self.events.append((event_type, dict(payload)))


class RecordingLedger:
    def __init__(self, run_id: str = "run00001") -> None:
        self.run_id = run_id
        self.events: list[tuple[str, str | None, dict]] = []

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, dict(payload)))


class RecordingWorker:
    def __init__(self) -> None:
        self.investigate_calls = 0
        self.tokens_spent = 0
        self.model = "claude-sonnet-5"

    async def investigate(self, brief, effort, qid, repairs=None, question_text=""):
        self.investigate_calls += 1
        return WorkerResult(question_id=qid, status="completed", claims=[])

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


class RecordingRuntime:
    def __init__(self, outcomes, *, fold=None) -> None:
        self._outcomes = list(outcomes)
        self.tickets = []
        self.advance_calls = 0
        self.fold_calls: list[str] = []
        self._fold = fold

    async def advance(self, ticket):
        self.advance_calls += 1
        self.tickets.append(ticket)
        return self._outcomes.pop(0)

    async def fold(self, run_id: str):
        self.fold_calls.append(run_id)
        if self._fold is not None:
            return self._fold
        return FoldedResult(
            run_id=run_id,
            status=SubagentStatus.COMPLETED,
            summary="unverified explore brief",
            truncated=False,
        )


def _assignment(**overrides) -> Assignment:
    payload = {
        "question_id": "qid00001",
        "brief": "Investigate the claim",
        "effort": Effort.SCOUT,
        "question_text": "What is the claim?",
    }
    payload.update(overrides)
    return Assignment(**payload)


def _outcome(**overrides) -> StepOutcome:
    payload = {
        "kind": StepKind.CONTINUING,
        "run_id": "sa_child",
        "checkpoint_id": "sc_1",
        "status": SubagentStatus.RUNNING,
        "turn_count": 1,
        "tool_count": 0,
    }
    payload.update(overrides)
    return StepOutcome(**payload)


def _orch(*, runtime=None, worker=None, ledger=None):
    worker = worker or RecordingWorker()
    return Orchestrator(
        session=None,
        run_id="run00001",
        worker_factory=lambda: worker,
        grader=None,
        ledger=ledger or RecordingLedger(),
        decompose_fn=lambda t: [],
        subagent_runtime=runtime,
    )


def _enable_flag(monkeypatch) -> None:
    monkeypatch.setattr(settings.config.deep_analysis, "subagent_enabled", True)


def _text(text: str = "report"):
    return (TextDelta(text), ModelCompleted("end_turn", ModelUsage(3, 2)))


def _tool(name: str = "search", **input):
    return (
        TextDelta("looking"),
        ToolCallCompleted("call_1", name, input or {"query": "moe"}),
        ModelCompleted("tool_use", ModelUsage(4, 1)),
    )


def _live_runtime(script, *, store=None, search=None, fetch=None):
    store = store or InMemorySubagentStore()

    async def _search(query, k=5):
        if search is not None:
            return await search(query, k)
        return [{"url": "https://example.com", "title": query, "snippet": "hit"}]

    async def _fetch(url):
        if fetch is not None:
            return await fetch(url)
        return {
            "source_url": url,
            "http_status": 200,
            "content_hash": "abc",
            "raw_text": "body",
        }

    tools = DAToolPort(_search, _fetch)
    model = ScriptedCodingModel(script)
    runtime = SubagentRuntime(
        store=store,
        catalog=SpecRegistry(),
        stepper=ChildStepper(model=model, tools=tools),
        events=RecordingSink(),
        clock=SystemClock(),
    )
    return runtime, store, tools, model


@pytest.mark.asyncio
async def test_flag_off_uses_worker_and_never_advances() -> None:
    worker = RecordingWorker()
    runtime = RecordingRuntime([_outcome()])
    orch = _orch(runtime=runtime, worker=worker)

    result = await orch._run_worker(_assignment())

    assert result.status == "completed"
    assert worker.investigate_calls == 1
    assert runtime.advance_calls == 0
    assert runtime.fold_calls == []


@pytest.mark.asyncio
async def test_flag_on_advances_once_per_run_worker(monkeypatch) -> None:
    _enable_flag(monkeypatch)
    worker = RecordingWorker()
    runtime = RecordingRuntime([_outcome()])
    orch = _orch(runtime=runtime, worker=worker)

    result = await orch._run_worker(_assignment())

    assert runtime.advance_calls == 1
    assert worker.investigate_calls == 0
    assert result.status == "partial"
    assert result.unverified_brief == ""
    assert result.subagent_run_id == "sa_child"
    assert result.subagent_step_kind == "continuing"


def test_adapter_and_worker_path_have_no_inner_max_turns_loop() -> None:
    adapter = _ADAPTER.read_text()
    orchestrator = _ORCH.read_text()
    assert adapter.count(".advance(") == 1
    assert "run_until_done" not in adapter
    assert "while True" not in adapter
    assert "range(max_turns)" not in adapter
    worker_fn = orchestrator.split("async def _run_worker", 1)[1].split(
        "async def _decompose", 1
    )[0]
    assert "range(max_turns)" not in worker_fn
    assert "run_until_done" not in worker_fn
    assert "while True" not in worker_fn


@pytest.mark.asyncio
async def test_continuing_partial_then_same_question_resumes_sa(monkeypatch) -> None:
    _enable_flag(monkeypatch)
    store = InMemorySubagentStore()
    runtime, store, _tools, _model = _live_runtime(
        [_tool("search", query="moe"), _text("moe is a routing method")],
        store=store,
    )
    ledger = RecordingLedger()
    orch = _orch(runtime=runtime, ledger=ledger)
    assignment = _assignment()

    first = await orch._run_worker(assignment)
    await log_subagent_step(
        ledger,
        assignment.question_id,
        run_id=first.subagent_run_id,
        checkpoint_id=first.subagent_checkpoint_id or None,
        step_kind=first.subagent_step_kind,
        status=first.status,
    )
    second = await orch._run_worker(
        assignment,
        child_run_id=first.subagent_run_id,
        child_checkpoint_id=first.subagent_checkpoint_id or None,
    )

    assert first.status == "partial"
    assert first.unverified_brief == ""
    assert first.subagent_run_id.startswith("sa_")
    assert first.tokens_spent > 0
    assert second.subagent_run_id == first.subagent_run_id
    assert len(store._by_parent) == 1
    parent_key = next(iter(store._by_parent))
    assert parent_key == (
        ParentKind.DEEP_ANALYSIS.value,
        ledger.run_id,
        assignment.question_id,
    )


@pytest.mark.asyncio
async def test_terminal_fold_sets_unverified_brief_without_claims(
    monkeypatch,
) -> None:
    _enable_flag(monkeypatch)
    runtime, _store, _tools, _model = _live_runtime(
        [_text("short unverified findings")]
    )
    orch = _orch(runtime=runtime)

    result = await orch._run_worker(_assignment())

    assert result.status == "completed"
    assert result.unverified_brief == "short unverified findings"
    assert result.claims == []


@pytest.mark.asyncio
async def test_flag_on_without_runtime_fails_closed(monkeypatch) -> None:
    _enable_flag(monkeypatch)
    worker = RecordingWorker()
    orch = _orch(runtime=None, worker=worker)

    result = await orch._run_worker(_assignment())

    assert result.status == "failed"
    assert result.fail_reason == "subagent_runtime_missing"
    assert worker.investigate_calls == 0


@pytest.mark.asyncio
async def test_tool_port_only_exposes_search_and_fetch() -> None:
    calls: list[tuple[str, object]] = []

    async def search_fn(query, k=5):
        calls.append(("search", (query, k)))
        return [{"url": "https://a.example", "title": "A", "snippet": query}]

    async def fetch_fn(url):
        calls.append(("fetch", url))
        return {
            "source_url": url,
            "http_status": 200,
            "content_hash": "h",
            "raw_text": "body",
        }

    port = DAToolPort(search_fn, fetch_fn)
    names = {
        item if isinstance(item, str) else getattr(item, "name")
        for item in port.definitions()
    }
    assert names == {"search", "fetch"}

    searched = await port.execute("search", {"query": "moe", "k": 3})
    fetched = await port.execute("fetch", {"url": "https://a.example"})
    refused = await port.execute("execute", {"cmd": "rm -rf /"})
    spawn = await port.execute("spawn_agent.v1", {"prompt": "no"})
    edit = await port.execute("edit_file.v1", {"path": "x"})

    assert searched["results"][0]["url"] == "https://a.example"
    assert fetched["source_url"] == "https://a.example"
    assert refused["error"] == "tool_not_allowed"
    assert spawn["error"] == "tool_not_allowed"
    assert edit["error"] == "tool_not_allowed"
    assert calls == [("search", ("moe", 3)), ("fetch", "https://a.example")]


def test_adapter_source_stays_inside_the_import_law() -> None:
    text = _ADAPTER.read_text()
    for name in _FORBIDDEN:
        assert name not in text, name


@pytest.mark.asyncio
async def test_explore_ticket_is_da_none_sandbox(monkeypatch) -> None:
    _enable_flag(monkeypatch)
    runtime = RecordingRuntime(
        [
            _outcome(
                kind=StepKind.COMPLETED,
                status=SubagentStatus.COMPLETED,
            )
        ]
    )
    orch = _orch(runtime=runtime)

    await orch._run_worker(_assignment())

    ticket = runtime.tickets[0]
    assert ticket.parent_kind is ParentKind.DEEP_ANALYSIS
    assert ticket.parent_id == "run00001"
    assert ticket.parent_run_id == "run00001"
    assert ticket.parent_tool_call_id == "qid00001"
    assert ticket.spec == "explore"
    assert ticket.sandbox_mode is SandboxMode.NONE
    assert ticket.briefing.goal == "What is the claim?"
    assert runtime.fold_calls == ["sa_child"]


@pytest.mark.asyncio
async def test_advance_exception_becomes_failed_worker_result(monkeypatch) -> None:
    _enable_flag(monkeypatch)

    class BoomRuntime:
        async def advance(self, ticket):
            raise CodingModelError("model_rate_limited", retryable=True)

    worker = RecordingWorker()
    orch = _orch(runtime=BoomRuntime(), worker=worker)

    result = await orch._run_worker(_assignment())

    assert result.status == "failed"
    assert "model_rate_limited" in result.fail_reason
    assert worker.investigate_calls == 0


@pytest.mark.asyncio
async def test_investigate_does_not_read_or_write_ledger() -> None:
    runtime = RecordingRuntime([_outcome()])

    result = await investigate_via_subagent(
        runtime=runtime,
        assignment=_assignment(),
        parent_id="run00001",
    )

    assert result.status == "partial"
    assert result.subagent_run_id == "sa_child"
    body = _ADAPTER.read_text().split("async def investigate_via_subagent", 1)[1]
    assert "ledger.log" not in body
    assert "latest_subagent_pointers" not in body

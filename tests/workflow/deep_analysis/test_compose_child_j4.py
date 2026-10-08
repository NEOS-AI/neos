"""트랙 J4 -- compose 자식이 최종 초안을 쓴다 (DECISIONS D105).

지키는 것:
- 플래그가 꺼져 있으면 `Synthesizer.assemble` 그대로이고 compose 이벤트가 하나도 없다
- 켜져 있으면 초안이 compose 자식에게서 오고, **옛 조립기로 슬쩍 떨어지지 않는다**
- compose 자식은 리듀스 트리가 아니라 **모든 질문의** verified 클레임을 파일로 받는다 --
  리덕션이 떨어뜨린 노드 자신의 클레임도 거기 있다(D104 가 찾은 원인)
- `check_claims.v1` 은 고아 인용과 인용 비율을 보이고 아무것도 기록하지 않는다
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from neos.config.settings import settings
from neos.subagent.types import ModelPin, StepKind
from neos.workflow.deep_analysis import compose_worker
from neos.workflow.deep_analysis.compose_worker import (
    BRIEF_PATH,
    COMPOSE_HEADER,
    INDEX_PATH,
    REPORT_PATH,
    ComposeFailed,
    check_report,
    claim_files,
    run_compose_worker,
)
from neos.workflow.deep_analysis.models import NodeSummary
from neos.workflow.deep_analysis.research_session import CommandLimits
from tests.workflow.deep_analysis.test_orchestrator_m4 import (
    FakeLedger,
    FakeSynth,
    FlakyRenderer,
    OkGrader,
    _write,
    _writer,
)

pytestmark = pytest.mark.no_db


# -- 원장 · 샌드박스 가짜 ---------------------------------------------------------


@dataclass
class _Q:
    id: str
    text: str


@dataclass
class _Claim:
    id: str
    text: str
    kind: str = "quote"


class ClaimLedger(FakeLedger):
    """질문 셋: 루트 · 자식 · 손자. 손자와 자식 **자신의** 클레임은 리듀스 요약에 없다."""

    run_id = "run00001"

    def __init__(self):
        super().__init__()
        self._questions = [_Q("root0001", "루트 질문"), _Q("child001", "자식"), _Q("grand001", "손자")]
        self._claims = {
            "root0001": [],
            "child001": [(_Claim("c1aaaaaa", "자식 자신의 클레임"), [SimpleNamespace(excerpt="발췌1")])],
            "grand001": [(_Claim("g1bbbbbb", "손자의 클레임"), [SimpleNamespace(excerpt="발췌2")])],
        }

    async def questions(self):
        return list(self._questions)

    async def verified_claims(self, qid):
        return list(self._claims.get(qid, []))

    async def root_question(self):
        return self._questions[0]


class MemorySession:
    def __init__(self):
        self.files: dict[str, bytes] = {}

    async def write_file(self, path, content, *, parents=True):
        self.files[path.lstrip("/")] = content
        return len(content)

    async def read_file(self, path, **_kw):
        key = path.lstrip("/")
        if key not in self.files:
            raise FileNotFoundError(key)
        return self.files[key]


class MemoryProvider:
    def __init__(self):
        self.session = MemorySession()
        self.destroyed: list[str] = []

    async def create(self, *, owner_id, limits, **_kw):
        return SimpleNamespace(sandbox_id=f"sb-{owner_id}")

    async def open_session(self, sandbox_id):
        return self.session

    async def destroy(self, sandbox_id):
        self.destroyed.append(sandbox_id)


class ScriptedRuntime:
    """한 걸음에 리포트를 쓰고 검사하고 제출한다. 무엇을 봤는지 남긴다."""

    def __init__(self, port, *, report: str | None, submit: bool = True, continuing: int = 0):
        self.port = port
        self.report = report
        self.submit = submit
        self.continuing = continuing
        self.check = None
        self.tickets = []

    async def advance(self, ticket):
        self.tickets.append(ticket)
        if len(self.tickets) <= self.continuing:
            return SimpleNamespace(kind=StepKind.CONTINUING, run_id="child-1", checkpoint_id=f"cp{len(self.tickets)}", tokens_delta=5)
        if self.report is not None:
            await self.port._session.write_file(REPORT_PATH, self.report.encode())
            self.check = await self.port.execute("check_claims.v1", {"report_path": REPORT_PATH})
        if self.submit:
            await self.port.execute("submit.v1", {"status": "completed", "claims": [], "report_path": REPORT_PATH})
        return SimpleNamespace(kind=StepKind.COMPLETED, run_id="child-1", checkpoint_id="cpX", tokens_delta=7)


_PIN = ModelPin(provider="anthropic", model="claude-opus-5-5")


async def _run(ledger, provider, runtime_box, *, attempt=0, **runtime_kw):
    def factory(port):
        runtime_box.append(ScriptedRuntime(port, **runtime_kw))
        return runtime_box[-1]

    return await run_compose_worker(
        ledger=ledger,
        provider=provider,
        root_id="root0001",
        root_text="루트 질문",
        root_summary="루트 요약",
        child_blocks=["- [child001] 질문: 자식\n  답: 요약에는 클레임이 빠졌다"],
        caveats=[],
        revision_hints=[],
        runtime_factory=factory,
        model=_PIN,
        parent_id="run00001",
        attempt=attempt,
        limits=None,
        command_limits=CommandLimits(timeout_sec=5, output_bytes=4096),
        max_turns=1,  # 걸음 상한 2·1+1 = 3
    )


# -- 워커 --------------------------------------------------------------------------


async def test_every_question_s_verified_claims_become_files_not_only_the_reduced_tree():
    files = await claim_files(ClaimLedger())
    assert [f.question_id for f in files] == ["child001", "grand001"]  # 클레임 없는 루트는 파일이 없다
    assert "[C:c1aaaaaa] 자식 자신의 클레임" in files[0].render()
    assert "<evidence>발췌2</evidence>" in files[1].render()


async def test_the_child_sees_the_brief_the_index_and_the_claim_files_and_the_report_comes_back():
    provider, box = MemoryProvider(), []
    text, summary = await _run(
        ClaimLedger(), provider, box, report="본문 [C:c1aaaaaa] 그리고 [C:g1bbbbbb]\n\n## 출처"
    )
    files = provider.session.files
    assert files[BRIEF_PATH].decode().startswith(COMPOSE_HEADER)
    assert "요약에는 클레임이 빠졌다" in files[BRIEF_PATH].decode()  # final_compose 렌더가 실렸다
    assert {INDEX_PATH, "claims/child001.md", "claims/grand001.md"} <= set(files)
    assert "[C:g1bbbbbb]" in text
    assert summary["cited_verified"] == 2 and summary["available_verified"] == 2
    assert summary["orphan_claims"] == 0
    assert provider.destroyed == ["sb-root0001"]  # 샌드박스는 닫힌다
    ticket = box[0].tickets[0]
    assert ticket.spec == "compose" and ticket.model == _PIN


async def test_check_claims_names_orphans_and_the_cited_ratio():
    provider, box = MemoryProvider(), []
    await _run(ClaimLedger(), provider, box, report="[C:c1aaaaaa] [C:deadbeef]")
    check = box[0].check
    assert check["orphan_claim_ids"] == ["deadbeef"]
    assert check["cited_verified"] == 1 and check["available_verified"] == 2
    assert check["uncited_claim_ids"] == ["g1bbbbbb"]


def test_check_report_is_pure():
    assert check_report("no markers", set())["cited_ratio"] is None


@pytest.mark.parametrize(
    "kw,reason",
    [
        ({"report": "x", "submit": False}, "submit_not_called"),
        ({"report": None, "submit": True}, "report_not_found"),
        ({"report": "   ", "submit": True}, "report_empty"),
        ({"report": "x", "continuing": 5}, "compose_step_cap"),
    ],
)
async def test_failures_are_named_not_swallowed(kw, reason):
    provider = MemoryProvider()
    with pytest.raises(ComposeFailed) as info:
        await _run(ClaimLedger(), provider, [], **kw)
    assert info.value.reason == reason
    assert provider.destroyed == ["sb-root0001"]


async def test_a_continuing_child_is_advanced_with_its_checkpoint():
    provider, box = MemoryProvider(), []
    await _run(ClaimLedger(), provider, box, report="[C:c1aaaaaa]", continuing=1)
    tickets = box[0].tickets
    assert tickets[0].run_id is None
    assert (tickets[1].run_id, tickets[1].expected_checkpoint_id) == ("child-1", "cp1")


# -- 오케스트레이터 ----------------------------------------------------------------


def _summaries():
    return {"root0001": NodeSummary("root0001", "루트 요약", [], 0.9, [])}


async def test_with_the_flag_off_assemble_writes_the_draft_and_no_compose_event(monkeypatch):
    monkeypatch.setattr(settings.config.deep_analysis, "compose_child_enabled", False)
    ledger, synth = ClaimLedger(), FakeSynth(_summaries())
    report = await _write(_writer(ledger, synth, FlakyRenderer(0), grader=OkGrader()))
    assert "DRAFT-1" in report and synth.assemble_calls == 1
    assert not [e for e in ledger.events if e[0].startswith("code_worker")]


async def test_with_the_flag_on_the_compose_child_writes_the_draft(monkeypatch):
    monkeypatch.setattr(settings.config.deep_analysis, "compose_child_enabled", True)
    seen = {}

    async def fake(**kwargs):
        seen.update(kwargs)
        return "COMPOSED [C:c1aaaaaa]\n\n## 출처", {"steps": 1, "cited_verified": 1}

    monkeypatch.setattr(compose_worker, "run_compose_worker", fake)
    ledger, synth = ClaimLedger(), FakeSynth(_summaries())
    writer = _writer(ledger, synth, FlakyRenderer(0), grader=OkGrader(),
                     sandbox_provider=MemoryProvider(), compose_runtime_factory=lambda port: None)

    report = await _write(writer)

    assert "COMPOSED" in report and synth.assemble_calls == 0
    kinds = [(k, p.get("spec")) for (k, _q, p) in ledger.events if k.startswith("code_worker")]
    assert kinds == [("code_worker_started", "compose"), ("code_worker_submitted", "compose")]
    assert seen["root_id"] == "root0001" and seen["root_summary"] == "루트 요약"


async def test_a_failing_compose_child_falls_back_to_assemble_once_and_says_so(monkeypatch):
    """조용한 degrade 금지 -- 매 시도가 원장에 이유를 남기고, 시도 **안에서는** 옛 조립기가 불리지 않는다.

    모든 시도가 실패하면 루프 **밖에서** 옛 조립기를 한 번 부르고 원장·부록에 그 사실을 적는다(D114) --
    #29 의 default 런은 부록 한 줄만 받았다(D113).
    """
    monkeypatch.setattr(settings.config.deep_analysis, "compose_child_enabled", True)

    async def fail(**_kw):
        raise ComposeFailed("submit_not_called")

    monkeypatch.setattr(compose_worker, "run_compose_worker", fail)
    ledger, synth = ClaimLedger(), FakeSynth(_summaries())
    writer = _writer(ledger, synth, FlakyRenderer(0), grader=OkGrader(),
                     sandbox_provider=MemoryProvider(), compose_runtime_factory=lambda port: None)

    report = await _write(writer)

    reasons = [p["reason"] for (k, _q, p) in ledger.events if k == "code_worker_unsubmitted"]
    attempts = settings.config.deep_analysis.report_retry_cap + 1
    assert reasons == ["submit_not_called"] * attempts
    assert synth.assemble_calls == 1
    degraded = [p for (k, _q, p) in ledger.events if k == "report_assembly_degraded"]
    assert degraded[0] == {"reason": "compose_all_attempts_failed", "attempts": attempts}
    # 가짜 조립기의 초안은 고아를 인용한다 -- 그 사유가 compose 사유를 덮지 않고 덧붙는다.
    assert [p["reason"] for p in degraded[1:]] == ["orphan_citations_delivered"]
    assert "DRAFT-1" in report and "옛 조립기의 초안을 실었다" in report and "존재하지 않는" in report
    graded = [p for (k, _q, p) in ledger.events if k == "report_graded"]
    assert graded == []  # 대체 초안은 채점되지 않는다


async def test_a_compose_draft_that_was_rejected_is_delivered_not_the_fallback(monkeypatch):
    """대체는 compose 가 초안을 **하나도** 못 냈을 때만이다 -- 반려된 compose 초안이 있으면 그것이 나간다."""
    from tests.workflow.deep_analysis.test_orchestrator_m4 import FailGrader as RejectGrader

    monkeypatch.setattr(settings.config.deep_analysis, "compose_child_enabled", True)

    async def compose(**_kw):
        return "COMPOSED [C:c1aaaaaa]\n\n## 출처", {"steps": 1}

    monkeypatch.setattr(compose_worker, "run_compose_worker", compose)
    ledger, synth = ClaimLedger(), FakeSynth(_summaries())
    writer = _writer(ledger, synth, FlakyRenderer(0), grader=RejectGrader(),
                     sandbox_provider=MemoryProvider(), compose_runtime_factory=lambda port: None)

    report = await _write(writer)

    assert synth.assemble_calls == 0 and "COMPOSED" in report
    assert not [p for (k, _q, p) in ledger.events if k == "report_assembly_degraded"]


async def test_a_missing_sandbox_is_reported_by_name(monkeypatch):
    monkeypatch.setattr(settings.config.deep_analysis, "compose_child_enabled", True)
    ledger, synth = ClaimLedger(), FakeSynth(_summaries())
    await _write(_writer(ledger, synth, FlakyRenderer(0), grader=OkGrader()))
    reasons = {p["reason"] for (k, _q, p) in ledger.events if k == "code_worker_unsubmitted"}
    assert reasons == {"sandbox_provider_missing"} and synth.assemble_calls == 1  # 루프 밖 대체 한 번(D114)


# -- D106: 라이브에서 드러난 셋 ----------------------------------------------------


def test_compose_steps_come_from_the_step_law_and_turns_fit_the_ticket():
    from neos.subagent.types import MAX_TICKET_TURNS
    from neos.workflow.deep_analysis.compose_worker import compose_max_steps

    assert compose_max_steps(12) == 25  # 2·12 + 1 -- 옛 17 이면 12 턴 전에 걸음 상한이 걸린다
    field = type(settings.config.deep_analysis).model_fields["compose_max_turns"]
    assert field.default == 12
    le = next(m.le for m in field.metadata if getattr(m, "le", None) is not None)
    assert le == MAX_TICKET_TURNS  # 설정이 티켓이 받지 못할 값을 허락하지 않는다


async def test_the_compose_ticket_carries_the_derived_turns():
    provider, box = MemoryProvider(), []
    await _run(ClaimLedger(), provider, box, report="[C:c1aaaaaa]")
    assert box[0].tickets[0].max_turns == 1


async def test_a_failed_child_is_named_by_its_error_not_as_a_missing_submit():
    class FailingRuntime:
        def __init__(self, port):
            self.port = port

        async def advance(self, ticket):
            return SimpleNamespace(kind=StepKind.FAILED, error_code="model_provider_failed", tokens_delta=0)

    with pytest.raises(ComposeFailed) as info:
        await run_compose_worker(
            ledger=ClaimLedger(), provider=MemoryProvider(), root_id="root0001", root_text="q",
            root_summary="", child_blocks=[], caveats=[], revision_hints=[],
            runtime_factory=FailingRuntime, model=_PIN, parent_id="run00001", attempt=0, limits=None,
            command_limits=CommandLimits(timeout_sec=5, output_bytes=4096), max_turns=8,
        )
    assert info.value.reason == "child_failed:model_provider_failed"


def test_da_children_get_their_own_prompt_and_explore_keeps_its_own():
    from neos.coding.prompts.official import AUTONOMOUS_EXECUTION, SCOPE_OF_CHANGES
    from neos.subagent.prompts import build_explore_system_prompt
    from neos.subagent.stepper import _CODING_PROMPTS

    compose = _CODING_PROMPTS["compose"]()
    assert "submit.v1" in compose and "report.md" in compose
    assert AUTONOMOUS_EXECUTION in compose and SCOPE_OF_CHANGES in compose  # 공식 문구 그대로
    assert "Do not edit, execute" not in compose
    assert _CODING_PROMPTS["research"]() != compose
    assert _CODING_PROMPTS["explore"]() == build_explore_system_prompt()


# -- D109: 재시도가 끝난 첫 자식을 받았다 --------------------------------------------


class StoreBackedRuntime:
    """실제 `InMemorySubagentStore` 의 정체성 규칙을 따른다 -- 같은 키의 끝난 실행은 다시 돌지 않는다."""

    def __init__(self, port, store):
        self.port = port
        self.store = store

    async def advance(self, ticket):
        from neos.subagent.types import SubagentStatus

        record = await self.store.resolve_or_create(ticket)
        if record.status is not SubagentStatus.PENDING:
            # 런타임은 끝난 실행을 그 결과 그대로 돌려준다 -- 자식은 이 포트에 아무것도 하지 않는다.
            return SimpleNamespace(kind=StepKind.COMPLETED, run_id=record.run_id, tokens_delta=0)
        await self.port._session.write_file(REPORT_PATH, b"[C:c1aaaaaa]")
        await self.port.execute("submit.v1", {"status": "completed", "claims": [], "report_path": REPORT_PATH})
        await self.store.cancel(record.run_id, "test_terminal")  # 끝난 실행으로 만든다
        return SimpleNamespace(kind=StepKind.COMPLETED, run_id=record.run_id, tokens_delta=1)


async def test_each_attempt_gets_a_fresh_child_not_the_finished_one():
    """#27: 시도 1 이 시도 0 의 끝난 자식을 받아 6/6 `submit_not_called` 였다(D109)."""
    from neos.subagent.memory import InMemorySubagentStore

    store = InMemorySubagentStore()
    for attempt in (0, 1):
        _text, summary = await run_compose_worker(
            ledger=ClaimLedger(), provider=MemoryProvider(), root_id="root0001", root_text="q",
            root_summary="", child_blocks=[], caveats=[], revision_hints=["E_REPORT_UNCITED"],
            runtime_factory=lambda port: StoreBackedRuntime(port, store), model=_PIN,
            parent_id="run00001", attempt=attempt, limits=None,
            command_limits=CommandLimits(timeout_sec=5, output_bytes=4096), max_turns=1,
        )
        assert summary["cited_verified"] == 1
    assert len(await store.list_for_parent_run("run00001")) == 2


async def test_the_orchestrator_hands_each_attempt_its_number(monkeypatch):
    monkeypatch.setattr(settings.config.deep_analysis, "compose_child_enabled", True)
    seen = []

    async def fail(**kwargs):
        seen.append(kwargs["attempt"])
        raise ComposeFailed("submit_not_called")

    monkeypatch.setattr(compose_worker, "run_compose_worker", fail)
    writer = _writer(ClaimLedger(), FakeSynth(_summaries()), FlakyRenderer(0), grader=OkGrader(),
                     sandbox_provider=MemoryProvider(), compose_runtime_factory=lambda port: None)
    await _write(writer)
    assert seen == list(range(settings.config.deep_analysis.report_retry_cap + 1))


# -- D114: compose 자식이 게이트의 미인용 축을 본다 -----------------------------------


_MIXED = (
    "## 요약\n"
    "EU AI Act 는 2024년 8월 1일 발효되었다 [C:c1aaaaaa]. "
    "GPAI 의무는 2025년 8월 2일부터 적용된다. "
    "Commission 은 2026년 지침을 냈다 [C:g1bbbbbb].\n"
    "근거가 부족한 부분이 있다.\n\n"
    "## 한계와 미확인 사항\n- 2027년 일정은 확인하지 못했다.\n"
)


async def test_check_claims_shows_the_gate_s_own_uncited_measurement():
    """미리보기 = 게이트. 렌더러는 `[C:id]` 를 같은 자리의 `[n]` 으로 바꾸므로(`citation.py`), 그렇게 바꾼 텍스트에
    게이트가 내는 진단과 `check_claims.v1` 이 compose 원문에서 내는 값이 같아야 한다."""
    from neos.workflow.deep_analysis.graders.report import ReportGrader

    rendered = _MIXED.replace("[C:c1aaaaaa]", "[1]").replace("[C:g1bbbbbb]", "[2]")
    verdict = await ReportGrader(ClaimLedger(), judge_model="x").grade_deterministic(rendered, "root0001")
    preview = check_report(_MIXED, {"c1aaaaaa", "g1bbbbbb"})

    for key in ("uncited_ratio", "uncited_assertions", "uncited_count", "uncited_threshold"):
        assert preview[key] == verdict.diagnostics[key], key
    assert preview["uncited_count"] == 1  # 한계 절의 문장은 게이트처럼 세지 않는다
    assert preview["uncited_sentences"] == ["GPAI 의무는 2025년 8월 2일부터 적용된다."]
    assert preview["uncited_gate_ok"] is (verdict.code != "E_REPORT_UNCITED")


def test_the_brief_names_the_gate_s_axis():
    assert "uncited_ratio" in COMPOSE_HEADER and "한계와 미확인 사항" in COMPOSE_HEADER

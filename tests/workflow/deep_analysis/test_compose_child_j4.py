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
    _orch,
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


async def _run(ledger, provider, runtime_box, **runtime_kw):
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
        limits=None,
        command_limits=CommandLimits(timeout_sec=5, output_bytes=4096),
        max_steps=3,
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
    report = await _orch(ledger, synth, FlakyRenderer(0), grader=OkGrader())._finalize("root0001")
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
    orch = _orch(ledger, synth, FlakyRenderer(0), grader=OkGrader())
    orch.sandbox_provider = MemoryProvider()
    orch.compose_runtime_factory = lambda port: None

    report = await orch._finalize("root0001")

    assert "COMPOSED" in report and synth.assemble_calls == 0
    kinds = [(k, p.get("spec")) for (k, _q, p) in ledger.events if k.startswith("code_worker")]
    assert kinds == [("code_worker_started", "compose"), ("code_worker_submitted", "compose")]
    assert seen["root_id"] == "root0001" and seen["root_summary"] == "루트 요약"


async def test_a_failing_compose_child_never_falls_back_to_assemble(monkeypatch):
    """조용한 degrade 금지 -- 매 시도가 원장에 이유를 남기고, 옛 조립기는 한 번도 불리지 않는다."""
    monkeypatch.setattr(settings.config.deep_analysis, "compose_child_enabled", True)

    async def fail(**_kw):
        raise ComposeFailed("submit_not_called")

    monkeypatch.setattr(compose_worker, "run_compose_worker", fail)
    ledger, synth = ClaimLedger(), FakeSynth(_summaries())
    orch = _orch(ledger, synth, FlakyRenderer(0), grader=OkGrader())
    orch.sandbox_provider = MemoryProvider()
    orch.compose_runtime_factory = lambda port: None

    await orch._finalize("root0001")

    assert synth.assemble_calls == 0
    reasons = [p["reason"] for (k, _q, p) in ledger.events if k == "code_worker_unsubmitted"]
    attempts = settings.config.deep_analysis.report_retry_cap + 1
    assert reasons == ["submit_not_called"] * attempts


async def test_a_missing_sandbox_is_reported_by_name(monkeypatch):
    monkeypatch.setattr(settings.config.deep_analysis, "compose_child_enabled", True)
    ledger, synth = ClaimLedger(), FakeSynth(_summaries())
    await _orch(ledger, synth, FlakyRenderer(0), grader=OkGrader())._finalize("root0001")
    reasons = {p["reason"] for (k, _q, p) in ledger.events if k == "code_worker_unsubmitted"}
    assert reasons == {"sandbox_provider_missing"} and synth.assemble_calls == 0


# -- D106: 라이브에서 드러난 셋 ----------------------------------------------------


def test_compose_turns_come_from_the_step_law():
    from neos.workflow.deep_analysis.compose_worker import compose_max_turns

    assert compose_max_turns(17) == 8  # 2·8 + 1
    assert compose_max_turns(1) == 1 and compose_max_turns(99) == 8  # 티켓 상한


async def test_the_compose_ticket_carries_the_derived_turns():
    provider, box = MemoryProvider(), []
    await _run(ClaimLedger(), provider, box, report="[C:c1aaaaaa]")
    assert box[0].tickets[0].max_turns == 1  # max_steps=3 → (3-1)//2


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
            runtime_factory=FailingRuntime, model=_PIN, parent_id="run00001", limits=None,
            command_limits=CommandLimits(timeout_sec=5, output_bytes=4096), max_steps=17,
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

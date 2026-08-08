from types import SimpleNamespace

import pytest

from neos.workflow.deep_analysis.models import NodeSummary, ProposedClaim, Verdict
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.token_budget import TokenBudgetExhausted


pytestmark = pytest.mark.no_db


class ExhaustedLedger:
    def __init__(self):
        self.events = []

    async def token_budget_state(self):
        return 10, {"orphan": 10}

    async def recover(self):
        return 0

    async def root_question(self):
        return SimpleNamespace(id="root", parent_id=None)

    async def total_spent(self):
        return 0

    async def open_questions(self):
        raise AssertionError("an exhausted shared budget must stop selection")

    async def children(self, _question_id):
        return []

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, payload))

    async def has_event(self, kind):
        return any(event[0] == kind for event in self.events)

    async def complete_run(self, report_path=None):
        return None

    async def fail_run(self):
        raise AssertionError("run unexpectedly failed")


class Synthesizer:
    async def reduce_tree(self, root_id):
        return {root_id: NodeSummary(root_id, "answer", [], 1.0, [])}

    async def assemble(
        self, root_summary, child_summaries, caveats, revision_hints=None
    ):
        return "report"


class CitationRenderer:
    async def render(self, draft):
        return draft


class Grader:
    async def grade(self, claim):
        return Verdict(
            ok=True,
            diagnostics={
                "deterministic": "passed",
                "deterministic_code": "",
            },
        )


@pytest.mark.asyncio
async def test_recovered_orphan_exhaustion_stops_and_emits_once():
    ledger = ExhaustedLedger()
    emitted = []

    async def event_sink(kind, payload):
        emitted.append((kind, payload))

    def forbidden_worker():
        raise AssertionError("worker must not be created")

    def build():
        return Orchestrator(
            object(),
            "run",
            worker_factory=forbidden_worker,
            grader=Grader(),
            ledger=ledger,
            synthesizer=Synthesizer(),
            citation_renderer=CitationRenderer(),
            event_sink=event_sink,
            global_token_cap=20,
        )

    first = await build().run("root")
    second = await build().run("root")

    assert first["report_markdown"].startswith("report")
    assert second["report_markdown"].startswith("report")
    exhausted_events = [e for e in ledger.events if e[0] == "token_budget_exhausted"]
    assert len(exhausted_events) == 1
    assert [kind for kind, _payload in emitted].count("token_budget_exhausted") == 1
    assert exhausted_events[0][2] == {
        "cap_tokens": 20,
        "consumed_tokens": 10,
        "reserved_tokens": 10,
    }


class FloorLedger:
    """Never exhausted (tokens remain), but the floor consumes all of them --
    the case `should_stop` is meant to catch (budgeter.py:121)."""

    def __init__(self):
        self.events = []

    async def token_budget_state(self):
        return 0, {}

    async def recover(self):
        return 0

    async def root_question(self):
        return SimpleNamespace(id="root", parent_id=None)

    async def total_spent(self):
        raise AssertionError("a floor stop must short-circuit before this read")

    async def open_questions(self):
        raise AssertionError("a floor stop must short-circuit before this read")

    async def children(self, _question_id):
        return []

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, payload))

    async def has_event(self, kind):
        return any(event[0] == kind for event in self.events)

    async def complete_run(self, report_path=None):
        return None

    async def fail_run(self):
        raise AssertionError("run unexpectedly failed")


@pytest.mark.asyncio
async def test_investigation_stopped_at_floor_is_recorded_once():
    """FIX 2: stopping at the floor must leave a trace distinguishable from
    `token_budget_exhausted`.

    There are 53 recorded `token_budget_exhausted` events; once the floor
    exists, `should_stop` halts while `remaining_tokens == floor_tokens > 0`
    (budgeter.py:121), so `token_budget.exhausted` is False and
    `_mark_token_budget_exhausted` never fires (orchestrator.py:934). Without
    a replacement, those events trend to zero for a reason unrelated to any
    real improvement, and a run that stopped clean at the floor becomes
    indistinguishable from one that simply ran out of open questions.
    """
    ledger = FloorLedger()
    emitted = []

    async def event_sink(kind, payload):
        emitted.append((kind, payload))

    def forbidden_worker():
        raise AssertionError("worker must not be created")

    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=forbidden_worker,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        event_sink=event_sink,
        global_token_cap=20,
        finalization_floor_tokens=20,
    )

    result = await orchestrator.run("root")

    assert result["report_markdown"].startswith("report")
    floor_events = [
        e for e in ledger.events if e[0] == "investigation_stopped_at_floor"
    ]
    assert len(floor_events) == 1
    assert floor_events[0][2] == {
        "cap_tokens": 20,
        "consumed_tokens": 0,
        "reserved_tokens": 0,
        "floor_tokens": 20,
        "report_floor_tokens": 0,
    }
    assert not any(e[0] == "token_budget_exhausted" for e in ledger.events)
    assert (
        [kind for kind, _payload in emitted].count(
            "investigation_stopped_at_floor"
        )
        == 1
    )


@pytest.mark.asyncio
async def test_optional_agentic_exhaustion_keeps_deterministic_verdict():
    class ExhaustedAgentic:
        async def grade(self, claim, value_est):
            raise TokenBudgetExhausted("cap")

    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        agentic_grader=ExhaustedAgentic(),
        ledger=ExhaustedLedger(),
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=20,
    )

    verdict = await orchestrator._grade(ProposedClaim("fact", 0.8), 0.9)

    assert verdict.ok is True
    assert verdict.diagnostics["deterministic"] == "passed"
    assert verdict.diagnostics["agentic"] == "exhausted"
    assert verdict.diagnostics["agentic_label"] is None


@pytest.mark.asyncio
async def test_no_agentic_grader_preserves_deterministic_diagnostics():
    deterministic = Verdict(
        ok=True,
        diagnostics={
            "deterministic": "passed",
            "deterministic_code": "",
        },
    )

    class SharedGrader:
        async def grade(self, claim):
            return deterministic

    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=SharedGrader(),
        ledger=ExhaustedLedger(),
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=20,
    )

    verdict = await orchestrator._grade(ProposedClaim("fact", 0.8), 0.9)

    assert verdict.diagnostics == {
        "deterministic": "passed",
        "deterministic_code": "",
        "agentic": "not_configured",
        "agentic_label": None,
    }
    assert deterministic.diagnostics == {
        "deterministic": "passed",
        "deterministic_code": "",
    }


@pytest.mark.asyncio
async def test_the_exception_path_does_not_call_the_stop_a_cap_exhaustion():
    """G9: 예외 경로가 사유를 독자 판정하던 것이 6건 중 4건을 오분류했다.

    `reserve` 는 캡 소진과 floor 정지 양쪽에 같은 `TokenBudgetExhausted` 를
    던진다(token_budget.py). 예외 타입은 사유를 말해주지 않으므로 예산의
    상태를 봐야 한다.
    """
    ledger = FloorLedger()
    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=100,
        finalization_floor_tokens=100,
    )
    await orchestrator._install_token_budget()

    # floor 가 캡 전체다 -> 조사 예산 0, 그러나 캡은 소진되지 않았다.
    assert orchestrator.token_budget.exhausted is False

    await orchestrator._mark_stop_reason()

    kinds = [event[0] for event in ledger.events]
    assert "investigation_stopped_at_floor" in kinds
    assert "token_budget_exhausted" not in kinds


@pytest.mark.asyncio
async def test_a_genuinely_exhausted_cap_is_still_reported_as_exhausted():
    """floor 정지와 캡 소진을 뭉개면 반대 방향의 거짓이 된다."""
    ledger = FloorLedger()
    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=100,
    )
    await orchestrator._install_token_budget()
    # 캡 전체를 소비한 것으로 만든다.
    orchestrator.token_budget._consumed_tokens = 100
    assert orchestrator.token_budget.exhausted is True

    await orchestrator._mark_stop_reason()

    kinds = [event[0] for event in ledger.events]
    assert "token_budget_exhausted" in kinds
    assert "investigation_stopped_at_floor" not in kinds


@pytest.mark.asyncio
async def test_a_normal_stop_records_no_budget_event():
    """열린 질문이 없어 멈춘 run은 예산 사건이 아니다.

    세 번째 분기를 두지 않는 것이 의도다 -- 정상 종료에 예산 이벤트를
    남기면 원장이 다시 거짓말을 시작한다.
    """
    ledger = FloorLedger()
    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=1_000_000,
    )
    await orchestrator._install_token_budget()

    await orchestrator._mark_stop_reason()

    kinds = [event[0] for event in ledger.events]
    assert "token_budget_exhausted" not in kinds
    assert "investigation_stopped_at_floor" not in kinds


@pytest.mark.asyncio
async def test_calling_the_stop_reason_twice_records_it_once():
    """예외 경로와 정상 경로가 연달아 부를 수 있다 -- 중복 적재는 안 된다."""
    ledger = FloorLedger()
    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=100,
        finalization_floor_tokens=100,
    )
    await orchestrator._install_token_budget()

    await orchestrator._mark_stop_reason()
    await orchestrator._mark_stop_reason()

    floor_events = [
        e for e in ledger.events if e[0] == "investigation_stopped_at_floor"
    ]
    assert len(floor_events) == 1


@pytest.mark.asyncio
async def test_a_refusal_with_headroom_left_records_its_own_stop():
    """G10: `reserve` 는 tier 에 여유가 있어도 프롬프트가 안 들어가면 거절한다.

    두 상태 분기 모두 그 정지를 잡지 못해 원장에 아무것도 남지 않았다.
    W1 의 라이브 표본은 "정확히 1회"라 그 침묵이 영구 기록이 된다.
    """
    ledger = FloorLedger()
    emitted = []

    async def event_sink(kind, payload):
        emitted.append((kind, payload))

    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        event_sink=event_sink,
        global_token_cap=100_000,
    )
    await orchestrator._install_token_budget()
    # 두 상태 분기가 모두 거짓인 조건 -- 여기가 지금 침묵하는 자리다.
    assert orchestrator.token_budget.exhausted is False
    assert (
        orchestrator.token_budget.available_for_investigation
        >= orchestrator.token_budget.min_viable_output_tokens
    )

    await orchestrator._mark_stop_reason(
        TokenBudgetExhausted(
            cause="input_bound",
            stage="worker_analysis",
            model="claude-sonnet-5",
            input_bound=17_723,
            ceiling=12_000,
        )
    )

    kinds = [event[0] for event in ledger.events]
    stops = [
        e for e in ledger.events
        if e[0] == "investigation_stopped_at_input_bound"
    ]
    assert len(stops) == 1
    assert stops[0][2] == {
        "cap_tokens": 100_000,
        "consumed_tokens": 0,
        "reserved_tokens": 0,
        "stage": "worker_analysis",
        "model": "claude-sonnet-5",
        "input_bound": 17_723,
        "ceiling": 12_000,
    }
    assert "token_budget_exhausted" not in kinds
    assert "investigation_stopped_at_floor" not in kinds
    assert (
        [kind for kind, _payload in emitted].count(
            "investigation_stopped_at_input_bound"
        )
        == 1
    )


@pytest.mark.asyncio
async def test_the_budget_state_outranks_the_refusal_cause():
    """상태 분기를 먼저 두는 것이 설계다.

    예산이 실제로 없으면, 마지막 거절이 우연히 큰 프롬프트였다는 사실은
    정지 사유가 아니다. G9 의 판정이 그대로 이겨야 한다.
    """
    ledger = FloorLedger()
    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=100,
    )
    await orchestrator._install_token_budget()
    orchestrator.token_budget._consumed_tokens = 100

    await orchestrator._mark_stop_reason(
        TokenBudgetExhausted(cause="input_bound", stage="report_assembly")
    )

    kinds = [event[0] for event in ledger.events]
    assert "token_budget_exhausted" in kinds
    assert "investigation_stopped_at_input_bound" not in kinds


@pytest.mark.asyncio
async def test_recording_an_input_bound_stop_twice_records_it_once():
    """예외 경로가 부르고 무조건 호출이 뒤따른다 -- 중복 적재는 안 된다."""
    ledger = FloorLedger()
    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=100_000,
    )
    await orchestrator._install_token_budget()
    exc = TokenBudgetExhausted(cause="input_bound", stage="worker_analysis")

    await orchestrator._mark_stop_reason(exc)
    await orchestrator._mark_stop_reason(exc)
    await orchestrator._mark_stop_reason()

    stops = [
        e for e in ledger.events
        if e[0] == "investigation_stopped_at_input_bound"
    ]
    assert len(stops) == 1

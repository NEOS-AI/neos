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

    async def assemble(self, root_summary, child_summaries, caveats):
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

    assert first["report_markdown"] == "report"
    assert second["report_markdown"] == "report"
    exhausted_events = [e for e in ledger.events if e[0] == "token_budget_exhausted"]
    assert len(exhausted_events) == 1
    assert [kind for kind, _payload in emitted].count("token_budget_exhausted") == 1
    assert exhausted_events[0][2] == {
        "cap_tokens": 20,
        "consumed_tokens": 10,
        "reserved_tokens": 10,
    }


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

from types import SimpleNamespace

import pytest

from neos.workflow.deep_analysis.models import NodeSummary, Verdict
from neos.workflow.deep_analysis.orchestrator import Orchestrator


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
        return Verdict(ok=True)


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

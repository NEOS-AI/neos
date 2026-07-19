from dataclasses import dataclass

import pytest

from neos.workflow.deep_analysis.llm import LLMResponse
from neos.workflow.deep_analysis.synthesizer import Synthesizer
from neos.workflow.deep_analysis.models import NodeSummary
from neos.workflow.deep_analysis.token_budget import TokenBudgetExhausted


pytestmark = pytest.mark.no_db


@dataclass
class Question:
    id: str
    text: str
    parent_id: str | None
    status: str = "resolved"


@dataclass
class Claim:
    id: str
    text: str
    confidence: float


@dataclass
class Evidence:
    excerpt: str
    raw_ref: str


class FakeLedger:
    def __init__(self):
        self.events = []
        self.root = Question("root0001", "Root question", None)
        self.child = Question("child001", "Child question", "root0001")

    async def root_question(self):
        return self.root

    async def children(self, question_id):
        return [self.child] if question_id == self.root.id else []

    async def verified_claims(self, question_id):
        if question_id != self.child.id:
            return []
        return [
            (
                Claim("c1a1c1a1", "Verified fact", 0.6),
                [Evidence("verbatim excerpt", "secret-raw-ref")],
            )
        ]

    async def unverified_and_deadends(self, question_id):
        return []

    async def questions(self):
        return [self.root, self.child]

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, payload))


class FakeLLMCall:
    def __init__(self):
        self.prompt = ""

    async def __call__(self, model, prompt, **kwargs):
        self.prompt = prompt
        return LLMResponse(
            text=(
                "## 요약\nVerified fact [C:c1a1c1a1]\n\n"
                "## 본문\nVerified fact [C:c1a1c1a1]\n\n"
                "## 한계와 미확인 사항\n없음\n\n## 출처"
            ),
            input_tokens=10,
            output_tokens=10,
            model=model,
        )


@pytest.mark.asyncio
async def test_single_layer_reduce_uses_only_verified_claim_excerpts():
    ledger = FakeLedger()
    llm_call = FakeLLMCall()

    draft = await Synthesizer(ledger, llm_call=llm_call).reduce(
        "root0001"
    )

    assert "[C:c1a1c1a1]" in draft
    assert "verbatim excerpt" in llm_call.prompt
    assert "secret-raw-ref" not in llm_call.prompt
    assert ledger.events[-1][0] == "synth_pass"


@pytest.mark.asyncio
async def test_reduce_includes_root_claims_when_decomposition_is_empty():
    class RootOnlyLedger(FakeLedger):
        async def children(self, question_id):
            return []

        async def verified_claims(self, question_id):
            if question_id != self.root.id:
                return []
            return [
                (
                    Claim("d2b2d2b2", "Root verified fact", 0.6),
                    [Evidence("root excerpt", "root-raw-ref")],
                )
            ]

    ledger = RootOnlyLedger()
    llm_call = FakeLLMCall()

    await Synthesizer(ledger, llm_call=llm_call).reduce("root0001")

    assert "[C:d2b2d2b2]" in llm_call.prompt
    assert "root excerpt" in llm_call.prompt


async def _exhausted(*args, **kwargs):
    raise TokenBudgetExhausted("cap")


@pytest.mark.asyncio
async def test_reduce_node_uses_child_summary_when_budget_exhausts():
    ledger = FakeLedger()
    synth = Synthesizer(ledger, json_call=_exhausted)
    child = NodeSummary("child001", "verified child answer", [], 0.8, [])

    summary = await synth.reduce_node(ledger.root, [child])

    assert summary.answer == "verified child answer"
    assert summary.caveats == ["token_budget_exhausted"]


@pytest.mark.asyncio
async def test_assemble_renders_required_sections_when_budget_exhausts():
    synth = Synthesizer(FakeLedger(), llm_call=_exhausted)
    root = NodeSummary("root0001", "verified root answer", [], 0.8, [])

    report = await synth.assemble(root, [], ["미확인 항목"])

    assert "## 요약" in report
    assert "## 본문" in report
    assert "## 한계와 미확인 사항" in report
    assert "## 출처" in report
    assert "전체 심층분석 토큰 상한" in report

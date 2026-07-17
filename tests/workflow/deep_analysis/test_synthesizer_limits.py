from dataclasses import dataclass, field

import pytest

from neos.workflow.deep_analysis.llm import LLMResponse
from neos.workflow.deep_analysis.synthesizer import Synthesizer


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
        self.abandoned_child = Question(
            "abnd0001", "Abandoned child question", "root0001", status="abandoned"
        )
        self._unverified: dict[str, list[str]] = {
            self.root.id: [],
            self.child.id: [],
            self.abandoned_child.id: [],
        }

    async def root_question(self):
        return self.root

    async def children(self, question_id):
        if question_id != self.root.id:
            return []
        return [self.child, self.abandoned_child]

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
        return self._unverified.get(question_id, [])

    async def questions(self):
        return [self.root, self.child, self.abandoned_child]

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
async def test_unverified_claims_and_abandoned_questions_surface_in_caveats():
    ledger = FakeLedger()
    ledger._unverified[ledger.child.id] = ["shaky claim text"]
    llm_call = FakeLLMCall()

    await Synthesizer(ledger, llm_call=llm_call).reduce("root0001")

    assert "미확인: shaky claim text" in llm_call.prompt
    assert "미조사: Abandoned child question" in llm_call.prompt


@pytest.mark.asyncio
async def test_caveats_default_when_no_unverified_or_abandoned():
    ledger = FakeLedger()
    ledger.abandoned_child.status = "resolved"
    llm_call = FakeLLMCall()

    await Synthesizer(ledger, llm_call=llm_call).reduce("root0001")

    assert "미확인:" not in llm_call.prompt
    assert "미조사:" not in llm_call.prompt
    assert "(없음)" in llm_call.prompt

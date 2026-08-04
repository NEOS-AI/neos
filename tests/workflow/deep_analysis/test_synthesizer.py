from dataclasses import dataclass

import pytest

from neos.config.settings import settings
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
        self.models = []

    async def __call__(self, model, prompt, **kwargs):
        self.prompt = prompt
        self.models.append(model)
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


@pytest.mark.parametrize(
    ("feature_model", "expected_model"),
    [
        (None, "claude-opus-5"),
        ("claude-synth-manual", "claude-synth-manual"),
    ],
)
@pytest.mark.asyncio
async def test_synthesizer_resolves_model_at_provider_boundary(
    monkeypatch, feature_model, expected_model
) -> None:
    monkeypatch.setattr(
        settings.config.deep_analysis.models,
        "synth",
        feature_model,
    )
    llm_call = FakeLLMCall()

    await Synthesizer(FakeLedger(), llm_call=llm_call).reduce("root0001")

    assert llm_call.models == [expected_model]


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


@pytest.mark.asyncio
async def test_synthesizer_uses_the_injected_ceiling():
    """dev는 cap을 15배 줄이면서 합성 상한은 물려받았다.

    상한을 주입받지 못하면 20000 예산에 4000짜리 호출을 세 번 넣게 된다.
    """
    seen = []

    async def recording_llm_call(model, prompt, **kw):
        seen.append(kw["max_tokens"])
        return LLMResponse(
            text="보고서", input_tokens=1, output_tokens=1, model=model
        )

    synth = Synthesizer(
        FakeLedger(),
        llm_call=recording_llm_call,
        synthesis_max_tokens=1200,
    )

    await synth.assemble(None, [], [])

    assert seen == [1200]


@pytest.mark.asyncio
async def test_synthesizer_falls_back_to_the_global_ceiling():
    seen = []

    async def recording_llm_call(model, prompt, **kw):
        seen.append(kw["max_tokens"])
        return LLMResponse(
            text="보고서", input_tokens=1, output_tokens=1, model=model
        )

    synth = Synthesizer(FakeLedger(), llm_call=recording_llm_call)

    await synth.assemble(None, [], [])

    assert seen == [settings.config.deep_analysis.synthesis_max_tokens]


@pytest.mark.asyncio
async def test_reduce_uses_the_injected_ceiling():
    """§7: 세 호출부(assemble/reduce/reduce_node) 모두 주입된 상한을 써야 한다.

    `assemble`만 검증되어 있었다 -- `reduce`가 여전히 전역 설정을 직접 읽는
    회귀는 dev 프로파일에서 20000 예산에 4000짜리 호출을 넣는 바로 그 결함을
    되살린다.
    """
    seen = []

    async def recording_llm_call(model, prompt, **kw):
        seen.append(kw["max_tokens"])
        return LLMResponse(
            text="보고서", input_tokens=1, output_tokens=1, model=model
        )

    synth = Synthesizer(
        FakeLedger(),
        llm_call=recording_llm_call,
        synthesis_max_tokens=1200,
    )

    await synth.reduce("root0001")

    assert seen == [1200]


@pytest.mark.asyncio
async def test_template_fallback_is_recorded():
    """예산 고갈로 템플릿으로 떨어지는 것이 성공처럼 보이면 안 된다.

    이 침묵 때문에 synth_pass=0을 알아채는 데 세션 하나가 걸렸다.
    """

    async def exhausted_llm_call(model, prompt, **kw):
        raise TokenBudgetExhausted("cap")

    ledger = FakeLedger()
    synth = Synthesizer(ledger, llm_call=exhausted_llm_call)

    report = await synth.assemble(None, [], [])

    assert report  # 빈손 종료는 없다 (§6.8)
    kinds = [kind for (kind, _qid, _payload) in ledger.events]
    assert "report_assembly_degraded" in kinds

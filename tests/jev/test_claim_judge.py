"""Choice 판정 경로 -- 로드맵 §12.5 L4.

실호출은 없다(§12.2 ①). 응답은 `test_scorer.py` 와 같은 이유로 **진짜 SDK
타입**(`SystemOneResponse.model_validate`)으로 만든다.
"""

from __future__ import annotations

import pytest
from typesafe_sdk import SystemOneResponse

from neos.jev.claim_judge import NO_EVIDENCE, TypeSafeClaimJudge, render_evidence_block
from neos.jev.rubric import load_rubric
from neos.workflow.deep_analysis.graders import agentic
from neos.workflow.deep_analysis.models import ProposedClaim, ProposedEvidence
from neos.workflow.deep_analysis.prompt_loader import render

pytestmark = pytest.mark.no_db

PROBS = {"SUPPORTS": 0.7, "PARTIAL": 0.2, "UNRELATED": 0.05, "CONTRADICTS": 0.05}


def response(choice: str = "SUPPORTS", model: str = "jev-1.13.0") -> SystemOneResponse:
    return SystemOneResponse.model_validate(
        {
            "model": model,
            "usage": {"input_tokens": 11, "output_tokens": 2},
            "answers": {
                "label": {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.7,
                    "probabilities": PROBS,
                }
            },
        }
    )


class StubClient:
    def __init__(self, reply: SystemOneResponse) -> None:
        self._reply = reply
        self.seen: list[dict[str, object]] = []

    async def system_one(self, state, questions, **kwargs):
        self.seen.append({"state": state, "questions": questions, **kwargs})
        return self._reply


def judge(client: StubClient) -> TypeSafeClaimJudge:
    return TypeSafeClaimJudge(
        client=client,
        model="jev-1.13.0",
        rubric=load_rubric("claim_judgement"),
        question="label",
        timeout_sec=5.0,
    )


def test_the_rubric_loads_as_a_single_choice_question() -> None:
    rubric = load_rubric("claim_judgement")
    assert list(rubric.questions) == ["label"]
    assert rubric.questions["label"]["type"] == "choice"
    assert len(rubric.digest) == 64


def test_the_labels_are_exactly_the_agentic_graders_verdicts() -> None:
    """라벨이 어긋나면 행렬이 정사각형이 아니고 대각선이 '같은 판정'이 아니다."""
    criteria = load_rubric("claim_judgement").questions["label"]["criteria"]
    assert set(criteria) == set(agentic._MAP)


async def test_the_evidence_block_is_byte_identical_to_what_the_judge_saw(monkeypatch) -> None:
    """`render_evidence_block` 은 사본이다. 판정자에게 **실제로 간** 프롬프트로 고정한다."""
    captured: dict[str, str] = {}

    class Usage:
        input_tokens = 1
        output_tokens = 1

    async def fake_call_json(model, prompt, **kwargs):
        captured["prompt"] = prompt
        return {"label": "SUPPORTS", "rationale": "r"}, Usage()

    monkeypatch.setattr(agentic, "call_json", fake_call_json)
    grader = agentic.AgenticGrader(
        judge_model="j", threshold=0.0, sample_rate=1.0, max_output_tokens=10
    )
    excerpts = ["cost drops 40%", "second <b>excerpt</b>"]
    claim = ProposedClaim(
        text="MoE lowers cost",
        confidence=0.9,
        evidence=[ProposedEvidence("http://x", e, "hh") for e in excerpts],
    )
    await grader.grade(claim, value_est=1.0)
    assert captured["prompt"] == render(
        "judge", claim_text=claim.text, evidence_block=render_evidence_block(excerpts)
    )

    await grader.grade(ProposedClaim(text="bare", confidence=0.9), value_est=1.0)
    assert captured["prompt"] == render(
        "judge", claim_text="bare", evidence_block=render_evidence_block([])
    )
    assert render_evidence_block([]) == NO_EVIDENCE


async def test_jev_sees_only_the_claim_and_the_evidence_block() -> None:
    client = StubClient(response())
    await judge(client).judge("MoE lowers cost", ["cost drops 40%"])
    state = client.seen[0]["state"]
    assert set(state) == {"uid", "claim", "evidence"}
    assert state["claim"] == "MoE lowers cost"
    assert state["evidence"] == "<evidence>cost drops 40%</evidence>"


async def test_the_answer_carries_choice_probabilities_digest_and_resolved_model() -> None:
    client = StubClient(response("PARTIAL", model="jev-1.13.0-20260901"))
    result = await judge(client).judge("c", ["e"])
    assert result.choice == "PARTIAL"
    assert result.probabilities == PROBS
    assert result.confidence == 0.7
    assert result.model == "jev-1.13.0-20260901"
    assert result.rubric_digest == load_rubric("claim_judgement").digest
    assert client.seen[0]["model"] == "jev-1.13.0"


async def test_each_call_carries_a_fresh_uid() -> None:
    client = StubClient(response())
    subject = judge(client)
    await subject.judge("c", ["e"])
    await subject.judge("c", ["e"])
    uids = [call["state"]["uid"] for call in client.seen]
    assert uids[0] != uids[1]
    assert all(uid.startswith(load_rubric("claim_judgement").digest) for uid in uids)


def test_a_noul_rubric_is_refused() -> None:
    with pytest.raises(ValueError):
        TypeSafeClaimJudge(
            client=StubClient(response()),
            model="jev-1.13.0",
            rubric=load_rubric("tool_risk"),
            question="destructive",
            timeout_sec=5.0,
        )


def test_the_claim_judge_is_not_in_role_routing() -> None:
    """§9: Jev 는 역할 라우팅 사슬(`everyday`/`powerful`)에 들어가지 않는다."""
    from pathlib import Path

    routing_sources = [
        Path("neos/config/models.yaml"),
        Path("neos/config/model_routing.py"),
        Path("neos/config/model_identity.py"),
        Path("neos/utils/llm_factory.py"),
    ]
    for source in routing_sources:
        assert source.exists(), f"라우팅 소스가 옮겨졌다 -- 이 가드를 따라 옮겨라: {source}"
        assert "jev" not in source.read_text(encoding="utf-8").lower(), source

"""M4 Task 1: node-level reduce -> NodeSummary (bounded per-node context)."""

import json
import pytest
from types import SimpleNamespace
from neos.workflow.deep_analysis.synthesizer import Synthesizer
from neos.workflow.deep_analysis.models import NodeSummary

pytestmark = pytest.mark.no_db


class CapturingJSON:
    """call_json 대체: 프롬프트를 캡처하고 스크립트된 NodeSummary dict 반환."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.prompts = []

    async def __call__(self, model, prompt, **kw):
        self.prompts.append(prompt)
        data = self.payloads.pop(0)
        return data, SimpleNamespace(input_tokens=len(prompt) // 4, output_tokens=10)


class FakeLedger:
    def __init__(self, verified):
        self._verified = verified  # {qid: [(claim, [ev])]}
        self.logged = []

    async def verified_claims(self, qid):
        return self._verified.get(qid, [])

    async def log(self, *a, **k):
        self.logged.append((a, k))


def _claim(cid, text):
    return SimpleNamespace(id=cid, text=text, confidence=0.7)


def _ev(excerpt):
    return SimpleNamespace(excerpt=excerpt, source_url="http://x")


async def test_reduce_node_uses_only_own_claims_and_child_answers():
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    child = NodeSummary(
        question_id="c1",
        answer="child ans [C:cccccccc]",
        key_claim_ids=["cccccccc"],
        confidence=0.7,
        caveats=[],
        conflicts=[],
    )
    led = FakeLedger({"n1": [(_claim("aaaaaaaa", "own claim"), [_ev("own excerpt")])]})
    cj = CapturingJSON(
        [
            {
                "question_id": "n1",
                "answer": "ans [C:aaaaaaaa]",
                "key_claim_ids": ["aaaaaaaa"],
                "confidence": 0.8,
                "caveats": [],
                "conflicts": [],
            }
        ]
    )
    synth = Synthesizer(led, json_call=cj)
    summary = await synth.reduce_node(q, [child])
    assert isinstance(summary, NodeSummary) and summary.question_id == "n1"
    p = cj.prompts[0]
    assert "own excerpt" in p  # 자기 클레임 excerpt 포함
    assert "child ans" in p  # 자식 answer 포함
    # 자식의 원시 클레임 텍스트는 넣지 않는다(요약 answer만) — child에는 raw 클레임이 없음
    assert summary.answer == "ans [C:aaaaaaaa]"
    assert summary.confidence == 0.8
    assert summary.key_claim_ids == ["aaaaaaaa"]


async def test_reduce_node_logs_node_summary_event_with_prompt_size():
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    led = FakeLedger({"n1": [(_claim("aaaaaaaa", "own claim"), [_ev("own excerpt")])]})
    cj = CapturingJSON(
        [
            {
                "question_id": "n1",
                "answer": "ans [C:aaaaaaaa]",
                "key_claim_ids": ["aaaaaaaa"],
                "confidence": 0.8,
                "caveats": [],
                "conflicts": [],
            }
        ]
    )
    synth = Synthesizer(led, json_call=cj)
    await synth.reduce_node(q, [])
    assert len(led.logged) == 1
    args, kwargs = led.logged[0]
    assert args[0] == "node_summary"
    assert args[1] == "n1"
    payload = args[2]
    assert "input_tokens" in payload
    assert "prompt_chars" in payload


async def test_reduce_node_split_question_uses_only_child_summaries():
    """자기 클레임이 없는 split 질문: child_summaries만으로 answer."""
    q = SimpleNamespace(id="n2", text="split Q", status="open", value_est=0.5)
    child = NodeSummary(
        question_id="c1",
        answer="child ans only",
        key_claim_ids=[],
        confidence=0.6,
        caveats=[],
        conflicts=[],
    )
    led = FakeLedger({})  # no verified claims for n2
    cj = CapturingJSON(
        [
            {
                "question_id": "n2",
                "answer": "combined [C:cccccccc]",
                "key_claim_ids": [],
                "confidence": 0.6,
                "caveats": [],
                "conflicts": [],
            }
        ]
    )
    synth = Synthesizer(led, json_call=cj)
    summary = await synth.reduce_node(q, [child])
    p = cj.prompts[0]
    assert "child ans only" in p
    assert "(없음)" in p  # own verified_claims block is empty
    assert summary.answer == "combined [C:cccccccc]"


async def test_reduce_node_parse_failure_falls_back_without_crashing():
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    child1 = NodeSummary(
        question_id="c1", answer="answer one", key_claim_ids=[], confidence=0.5,
        caveats=[], conflicts=[],
    )
    child2 = NodeSummary(
        question_id="c2", answer="answer two", key_claim_ids=[], confidence=0.5,
        caveats=[], conflicts=[],
    )

    class RaisingJSON:
        async def __call__(self, model, prompt, **kw):
            raise ValueError("boom: unparseable JSON")

    led = FakeLedger({"n1": [(_claim("aaaaaaaa", "own claim"), [_ev("own excerpt")])]})
    synth = Synthesizer(led, json_call=RaisingJSON())
    summary = await synth.reduce_node(q, [child1, child2])
    assert isinstance(summary, NodeSummary)
    assert summary.confidence == 0.0
    assert "node_summary_unparseable" in summary.caveats
    assert "answer one" in summary.answer
    assert "answer two" in summary.answer


async def test_reduce_node_parses_conflicts():
    q = SimpleNamespace(id="n1", text="Q", status="open", value_est=0.8)
    led = FakeLedger({"n1": [(_claim("aaaaaaaa", "own claim"), [_ev("own excerpt")])]})
    cj = CapturingJSON(
        [
            {
                "question_id": "n1",
                "answer": "ans [C:aaaaaaaa]",
                "key_claim_ids": ["aaaaaaaa"],
                "confidence": 0.5,
                "caveats": [],
                "conflicts": [
                    {"claim_a": "aaaaaaaa", "claim_b": "bbbbbbbb", "nature": "수치 불일치"}
                ],
            }
        ]
    )
    synth = Synthesizer(led, json_call=cj)
    summary = await synth.reduce_node(q, [])
    assert len(summary.conflicts) == 1
    assert summary.conflicts[0].claim_a == "aaaaaaaa"
    assert summary.conflicts[0].nature == "수치 불일치"

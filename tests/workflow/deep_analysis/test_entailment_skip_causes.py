"""C4: 함의 필터가 건너뛰어졌을 때 **왜** 그랬는지가 원인별로 남는다.

옛 동작은 다섯 원인을 전부 `entailment_skipped=True` 로 접었고, 오케스트레이터는
그것을 상수 `"entailment_unavailable"` 로 적었다. 그래서 C1(discard recall) 재측정이
discard 0건을 봐도 "버릴 게 없었다 / 필터가 안 돌았다"까지만 갈렸고, 후자의
다섯 갈래는 구별되지 않았다.

C3 도 여기서 함께 확인한다 -- 다섯 중 넷은 **실패한 호출**이고, 그 호출이 쓴
토큰은 예전엔 워커의 집계에서 그대로 사라졌다.
"""

import pytest

from neos.workflow.deep_analysis.models import (
    ENTAILMENT_BUDGET_EXHAUSTED,
    ENTAILMENT_PROVIDER_FAILED,
    ENTAILMENT_SCHEMA_INVALID,
    ENTAILMENT_SKIP_CAUSES,
    ENTAILMENT_TRUNCATED,
    ENTAILMENT_UNPARSEABLE,
    ProposedClaim,
    ProposedEvidence,
)
from neos.workflow.deep_analysis.token_budget import (
    TokenBudget,
    TokenBudgetExhausted,
    token_budget_scope,
)
from neos.workflow.deep_analysis.worker import Worker


pytestmark = pytest.mark.no_db

_USAGE_PER_CALL = 15  # FakeEntailmentLLM: input 10 + output 5


class FakeEntailmentLLM:
    """한 번 부를 때마다 다음 대본을 낸다. 대본이 떨어지면 마지막을 반복한다."""

    def __init__(self, texts, stop_reasons=None, raises=None):
        self._texts = list(texts)
        self._stop_reasons = list(stop_reasons or [])
        self._raises = raises
        self.messages = self
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        text = (
            self._texts.pop(0) if len(self._texts) > 1 else self._texts[0]
        )
        stop_reason = (
            self._stop_reasons.pop(0) if self._stop_reasons else "end_turn"
        )

        class Usage:
            input_tokens = 10
            output_tokens = 5

        class Block:
            type = "text"
            text_value = text

            def __init__(self):
                self.text = Block.text_value

        class Response:
            content = [Block()]
            usage = Usage()
            model = kwargs["model"]

        Response.stop_reason = stop_reason
        return Response()


def _claims():
    evidence = [
        ProposedEvidence(
            source_url="https://example.com/source",
            excerpt="Directly supported text.",
            raw_ref="0123456789abcdef",
        )
    ]
    return [ProposedClaim("keep me", 0.6, evidence)]


async def _refine_with(client):
    async def search(query, k):  # pragma: no cover - never reached
        return []

    worker = Worker(search, llm_client=client)
    worker._model = "claude-haiku-4-5-20251001"
    claims = _claims()
    refined = await worker._refine_claims(claims)
    return worker, refined


@pytest.mark.asyncio
async def test_provider_failure_names_itself_and_still_bills_nothing():
    """공급자가 죽으면 usage 가 없다 -- §A5 는 추정을 금지한다."""
    worker, refined = await _refine_with(
        FakeEntailmentLLM(["unused"], raises=RuntimeError("provider is down"))
    )

    assert worker._entailment_skipped == ENTAILMENT_PROVIDER_FAILED
    # 필터는 게이트가 아니다 -- 클레임은 그대로 통과한다.
    assert [claim.text for claim in refined] == ["keep me"]
    assert worker.tokens_spent == 0


@pytest.mark.asyncio
async def test_truncated_entailment_is_distinct_from_unparseable():
    """잘린 응답과 형식이 틀린 응답은 고칠 곳이 다르다."""
    worker, _ = await _refine_with(
        FakeEntailmentLLM(
            ["{cut off mid-", "{cut off again"],
            stop_reasons=["max_tokens", "max_tokens"],
        )
    )

    assert worker._entailment_skipped == ENTAILMENT_TRUNCATED
    # 잘림 확장은 `retries` 와 별개 축이라 entailment 의 retries=0 에서도 한 번 더 시도한다.
    assert worker.tokens_spent == 2 * _USAGE_PER_CALL


@pytest.mark.asyncio
async def test_unparseable_entailment_charges_its_one_attempt():
    worker, _ = await _refine_with(FakeEntailmentLLM(["not json at all"]))

    assert worker._entailment_skipped == ENTAILMENT_UNPARSEABLE
    # entailment 는 retries=0 이다: 같은 배치를 두 번 사지 않는다.
    assert worker.tokens_spent == _USAGE_PER_CALL


@pytest.mark.asyncio
async def test_schema_invalid_is_the_one_cause_that_is_not_a_failed_call():
    """모델은 답했고 토큰도 정상 경로로 세어졌다 -- 모양만 틀렸다."""
    worker, _ = await _refine_with(
        FakeEntailmentLLM(['{"unexpected": "shape"}'])
    )

    assert worker._entailment_skipped == ENTAILMENT_SCHEMA_INVALID
    assert worker.tokens_spent == _USAGE_PER_CALL


@pytest.mark.asyncio
async def test_budget_refusal_names_itself_and_propagates():
    """예산 고갈만 다시 던진다 -- `investigate()` 가 flush_partial 로 받는다."""
    client = FakeEntailmentLLM(['{"results": []}'])
    budget = TokenBudget(1)

    worker = Worker(lambda *a, **k: None, llm_client=client)
    worker._model = "claude-haiku-4-5-20251001"

    with token_budget_scope(budget):
        with pytest.raises(TokenBudgetExhausted):
            await worker._refine_claims(_claims())

    assert worker._entailment_skipped == ENTAILMENT_BUDGET_EXHAUSTED
    assert client.calls == 0


def test_every_cause_is_declared_in_the_shared_vocabulary():
    """어휘가 흩어지면 소비자가 모르는 사유를 조용히 무시한다."""
    assert ENTAILMENT_SKIP_CAUSES == {
        ENTAILMENT_BUDGET_EXHAUSTED,
        ENTAILMENT_PROVIDER_FAILED,
        ENTAILMENT_TRUNCATED,
        ENTAILMENT_UNPARSEABLE,
        ENTAILMENT_SCHEMA_INVALID,
    }
    assert len(ENTAILMENT_SKIP_CAUSES) == 5


@pytest.mark.asyncio
async def test_successful_entailment_leaves_no_skip_reason():
    worker, refined = await _refine_with(
        FakeEntailmentLLM(['{"results": [{"index": 0, "action": "keep"}]}'])
    )

    assert worker._entailment_skipped is None
    assert [claim.text for claim in refined] == ["keep me"]

"""SDK 어댑터 -- 확률을 구해 오는 유일한 자리(로드맵 §12.5 L1).

**응답을 진짜 SDK 타입으로 만든다.** 손으로 만든 스텁 객체로 통과시키면 우리가
믿는 응답 모양과 SDK 의 실제 모양이 갈라져도 초록이다 -- K4b 가 정확히 그
자리에서 넘어졌다. 그래서 여기서는 `SystemOneResponse.model_validate` 로
검증된 객체만 쓴다.

실호출은 없다. 스위트에 실호출이 도는 테스트는 없다(§12.2 ①).
"""

from __future__ import annotations

import pytest
from typesafe_sdk import SystemOneResponse

from neos.jev.rubric import load_rubric
from neos.jev.scorer import TypeSafeToolRiskScorer

pytestmark = pytest.mark.no_db


def response(probability: float, model: str = "jev-1.13.0") -> SystemOneResponse:
    return SystemOneResponse.model_validate(
        {
            "model": model,
            "usage": {"input_tokens": 11, "output_tokens": 2},
            "answers": {"destructive": {"type": "noul", "noul": probability}},
        }
    )


class StubClient:
    def __init__(self, reply: SystemOneResponse) -> None:
        self._reply = reply
        self.seen: list[dict[str, object]] = []

    async def system_one(self, state, questions, **kwargs):
        self.seen.append({"state": state, "questions": questions, **kwargs})
        return self._reply


def scorer(client: StubClient) -> TypeSafeToolRiskScorer:
    return TypeSafeToolRiskScorer(
        client=client,
        model="jev-1.13.0",
        rubric=load_rubric("tool_risk"),
        question="destructive",
        timeout_sec=5.0,
    )


async def test_the_noul_probability_comes_back() -> None:
    result = await scorer(StubClient(response(0.93))).score_tool_risk({"tool": "execute.v1"})
    assert result.probability == 0.93


async def test_the_model_reported_by_the_api_wins_over_the_requested_one() -> None:
    """S13 은 **해소된** 모델 id 를 요구한다. 보낸 값이 아니라 답한 값이다."""
    client = StubClient(response(0.1, model="jev-1.13.0-20260901"))
    result = await scorer(client).score_tool_risk({"tool": "read_file"})
    assert result.model == "jev-1.13.0-20260901"


async def test_the_rubric_digest_travels_with_the_probability() -> None:
    result = await scorer(StubClient(response(0.1))).score_tool_risk({"tool": "read_file"})
    assert result.rubric_digest == load_rubric("tool_risk").digest


async def test_the_pinned_model_is_sent_not_the_sdk_default() -> None:
    """SDK 기본값은 `jev-latest` 다. 아무것도 보내지 않으면 별칭으로 돈다."""
    client = StubClient(response(0.1))
    await scorer(client).score_tool_risk({"tool": "read_file"})
    assert client.seen[0]["model"] == "jev-1.13.0"


async def test_each_call_carries_a_fresh_uid() -> None:
    """쿡북 프로토콜 -- 같은 uid 로 물으면 캐시가 일관성을 대신 만들어 준다."""
    client = StubClient(response(0.1))
    subject = scorer(client)
    await subject.score_tool_risk({"tool": "read_file"})
    await subject.score_tool_risk({"tool": "read_file"})
    uids = [call["state"]["uid"] for call in client.seen]
    assert uids[0] != uids[1]
    assert all(uid.startswith(load_rubric("tool_risk").digest) for uid in uids)


async def test_the_judged_state_survives_into_the_request() -> None:
    client = StubClient(response(0.1))
    await scorer(client).score_tool_risk({"tool": "execute.v1", "input": {"argv": ["rm"]}})
    assert client.seen[0]["state"]["tool"] == "execute.v1"


async def test_a_missing_answer_is_an_error_not_a_zero() -> None:
    """답이 없는데 0.0 으로 읽으면 "안전하다"로 읽힌다 -- 가장 나쁜 기본값이다."""
    empty = SystemOneResponse.model_validate(
        {"model": "jev-1.13.0", "usage": {}, "answers": {}}
    )
    with pytest.raises(KeyError):
        await scorer(StubClient(empty)).score_tool_risk({"tool": "read_file"})

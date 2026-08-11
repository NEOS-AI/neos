"""산문 호출도 잘리면 한 번 더 크게 시도한다 (W3-d).

`call_json` 은 A2 이후 잘림 확장 재시도를 갖는다. `call_llm` 은 잘림을
**기록만** 했고, `report_assembly` 가 `call_llm` 을 직접 쓰는 유일한 단계라
유일하게 회복하지 못했다.

2026-08-08 표본 #2 실측: 조립 18회가 **전부** 상한(dev 1200 / default 4000)에서
잘렸고 `truncation_handled` 는 `report_assembly` 에 한 건도 없었다. 프롬프트가
요구하는 마지막 절(`## 한계와 미확인 사항`)이 매번 살아남지 못했고, 인용
기준을 넘긴 유일한 시도(`dd8dc763` #2, ratio 0.1538 < 0.20)가 바로 그
`E_REPORT_NO_LIMITS` 로 반려됐다.
"""

import pytest

from neos.workflow.deep_analysis.llm import LLMResponse, call_text


pytestmark = pytest.mark.no_db


class _Calls:
    """`call_llm` 대역 -- 요청된 상한을 기록하고 정해둔 응답을 낸다."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.limits = []

    async def __call__(self, model, prompt, *, max_tokens, **kwargs):
        self.limits.append(max_tokens)
        return self.responses.pop(0)


def _resp(text, stop_reason, granted):
    return LLMResponse(
        text=text,
        input_tokens=10,
        output_tokens=granted,
        model="m",
        stop_reason=stop_reason,
        granted_max_output_tokens=granted,
    )


@pytest.mark.asyncio
async def test_an_untruncated_call_is_returned_as_is(monkeypatch):
    calls = _Calls([_resp("완결된 본문", "end_turn", 500)])
    monkeypatch.setattr("neos.workflow.deep_analysis.llm.call_llm", calls)

    response = await call_text("m", "p", max_tokens=1200, stage="report_assembly")

    assert response.text == "완결된 본문"
    assert calls.limits == [1200]


@pytest.mark.asyncio
async def test_a_truncated_call_is_retried_at_a_larger_ceiling(monkeypatch):
    calls = _Calls([
        _resp("잘린 본", "max_tokens", 1200),
        _resp("완결된 본문 ## 한계와 미확인 사항", "end_turn", 1800),
    ])
    monkeypatch.setattr("neos.workflow.deep_analysis.llm.call_llm", calls)

    response = await call_text("m", "p", max_tokens=1200, stage="report_assembly")

    assert "한계와 미확인 사항" in response.text
    assert len(calls.limits) == 2
    assert calls.limits[1] > calls.limits[0]


@pytest.mark.asyncio
async def test_a_budget_clamped_call_is_not_retried(monkeypatch):
    """예산이 이미 상한을 깎았다면 재시도는 더 적은 방을 받는다.

    `call_json` 이 같은 이유로 같은 판단을 한다 -- 정산이 `remaining` 을
    이미 줄였으므로 두 번째 시도가 더 작아진다.
    """
    calls = _Calls([_resp("잘린 본", "max_tokens", 800)])
    monkeypatch.setattr("neos.workflow.deep_analysis.llm.call_llm", calls)

    response = await call_text("m", "p", max_tokens=1200, stage="report_assembly")

    assert response.text == "잘린 본"
    assert calls.limits == [1200]


@pytest.mark.asyncio
async def test_a_still_truncated_retry_never_raises(monkeypatch):
    """잘린 리포트도 리포트다 -- §6.8 빈손 금지.

    `call_json` 은 여기서 `TruncatedResponseError` 를 던지지만, 산문 호출에는
    파싱 단계가 없고 던지면 run 전체가 죽는다.
    """
    calls = _Calls([
        _resp("짧게 잘림", "max_tokens", 1200),
        _resp("더 길게 잘렸지만 내용이 더 많다", "max_tokens", 1800),
    ])
    monkeypatch.setattr("neos.workflow.deep_analysis.llm.call_llm", calls)

    response = await call_text("m", "p", max_tokens=1200, stage="report_assembly")

    assert response.text == "더 길게 잘렸지만 내용이 더 많다"


@pytest.mark.asyncio
async def test_a_retry_that_produced_less_keeps_the_longer_original(monkeypatch):
    """둘 다 잘렸다면 내용이 더 많은 쪽이 낫다."""
    calls = _Calls([
        _resp("원래 응답이 훨씬 길고 내용이 많다", "max_tokens", 1200),
        _resp("짧음", "max_tokens", 1800),
    ])
    monkeypatch.setattr("neos.workflow.deep_analysis.llm.call_llm", calls)

    response = await call_text("m", "p", max_tokens=1200, stage="report_assembly")

    assert response.text == "원래 응답이 훨씬 길고 내용이 많다"

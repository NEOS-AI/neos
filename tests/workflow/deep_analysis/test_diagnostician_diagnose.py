import json
from pathlib import Path

import pytest
import yaml

from scripts.deep_analysis_diagnostician import diagnose, render_prompt

pytestmark = pytest.mark.no_db

LABELS = yaml.safe_load(
    Path("scripts/diagnostician_backtest/labels.yaml").read_text()
)["labels"]


class _FakeClient:
    """OpenAI 모양의 가짜 클라이언트. 응답을 미리 정해두고, LLM을 부르지 않는다.

    `model="fake"`는 `claude`로 시작하지 않고 카탈로그에도 없으므로
    `neos/workflow/deep_analysis/llm.py`의 `_is_anthropic_model`이 OpenAI
    분기로 보낸다 -- 그래서 이 가짜는 `client.messages.create`가 아니라
    `client.chat.completions.create`를 흉내낸다. 실제 계약은 그 파일의
    `_call_provider`를 읽고 맞췄다(브리프의 스텁은 `__init__`만 있었다).
    """

    def __init__(self, text: str):
        self.text = text
        self.chat = self
        self.completions = self
        self.prompts: list[str] = []

    async def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])

        class Message:
            content = self.text

        class Choice:
            message = Message()

        class Usage:
            prompt_tokens = 10
            completion_tokens = 5

        class Response:
            choices = [Choice()]
            usage = Usage()
            model = kwargs["model"]

        return Response()


class _FakeAnthropicClient:
    """anthropic 분기 전용 가짜. `stop_reason`을 실어 잘림 경로를 재현한다.

    OpenAI 분기(`_call_provider`)는 `stop_reason`을 항상 `"end_turn"`으로
    고정해서 돌려주므로, `_FakeClient`로는 잘림(`max_tokens`)을 만들 수
    없다. `TruncatedResponseError` 처리를 실제로 확인하려면 이 분기를 태워야
    한다.
    """

    def __init__(self, texts, stop_reasons):
        self._texts = list(texts)
        self._stop_reasons = list(stop_reasons)
        self.messages = self
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1

        class Usage:
            input_tokens = 10
            output_tokens = 5

        class Block:
            type = "text"
            text = self._texts.pop(0)

        class Response:
            content = [Block()]
            usage = Usage()
            model = kwargs["model"]
            stop_reason = self._stop_reasons.pop(0)

        return Response()


class _FailingClient:
    """전송 계층이 죽은 가짜. `_call_live_provider`가 임의 예외를
    `LLMProviderError`로 감싼다(llm.py) -- 파싱 실패와는 원인이 다른 실패다.
    """

    def __init__(self):
        self.chat = self
        self.completions = self
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        raise RuntimeError("connection reset")


def test_prompt_carries_the_label_set_and_the_summary():
    prompt = render_prompt({"events": {"claim_verified": 3}}, LABELS)
    assert "assembly_clamp" in prompt
    assert "claim_verified" in prompt


def test_the_prompt_never_carries_the_answer_key():
    """작성자가 정답을 안다는 사실이 프롬프트로 새는 경로를 코드가 막는다."""
    key_text = Path("scripts/diagnostician_backtest/answer_key.yaml").read_text()
    key = yaml.safe_load(key_text)["samples"]
    prompt = render_prompt({"events": {}}, LABELS)
    for sample_id, entry in key.items():
        assert entry["quote"] not in prompt
        assert entry["artifact"] not in prompt
        assert entry["decision"] not in prompt


@pytest.mark.asyncio
async def test_labels_outside_the_closed_set_are_rejected():
    payload = json.dumps({"candidates": [
        {"label": "vibes", "evidence": ["r1:1"], "reason": "느낌"}
    ]})
    result = await diagnose({"events": {}}, LABELS, model="fake",
                            client=_FakeClient(payload))
    assert result["candidates"] == []
    assert result["failure"] == "off_label"


@pytest.mark.asyncio
async def test_more_than_three_candidates_are_truncated_to_three():
    payload = json.dumps({"candidates": [
        {"label": label, "evidence": ["r1:1"], "reason": "x"}
        for label in LABELS[:5]
    ]})
    result = await diagnose({"events": {}}, LABELS, model="fake",
                            client=_FakeClient(payload))
    assert len(result["candidates"]) == 3


@pytest.mark.asyncio
async def test_unparseable_response_is_reported_not_swallowed():
    result = await diagnose({"events": {}}, LABELS, model="fake",
                            client=_FakeClient("이건 JSON이 아니다"))
    assert result["candidates"] == []
    assert result["failure"] == "unparseable"


@pytest.mark.asyncio
async def test_truncated_response_is_reported_as_truncated_not_unparseable():
    """`TruncatedResponseError`는 `JSONParseError`의 하위클래스다(llm.py).

    `except JSONParseError`를 `except TruncatedResponseError`보다 먼저 두면
    서브클래스이므로 잘림도 조용히 "unparseable"로 잡힌다 -- 순서가 정답을
    가른다. 이 테스트가 그 순서를 고정한다.
    """
    client = _FakeAnthropicClient(
        ['{"partial": tru', '{"still cu'],
        stop_reasons=["max_tokens", "max_tokens"],
    )
    result = await diagnose({"events": {}}, LABELS,
                            model="claude-haiku-4-5-20251001", client=client)
    assert result["candidates"] == []
    assert result["failure"] == "truncated"


@pytest.mark.asyncio
async def test_provider_error_costs_only_this_repetition():
    """전송 계층 실패는 "truncated"로 뭉개지지도, 백테스트를 죽이지도 않는다.

    한 백테스트 실행은 표본 18개를 부른다 -- 한 번의 반짝 실패로 전체를
    던지면 이미 끝난 표본들의 결과까지 날아간다. `diagnose`는 대신 이
    반복 하나만 `failure="provider_error"`로 기록하고 돌아온다.
    """
    result = await diagnose({"events": {}}, LABELS, model="fake",
                            client=_FailingClient())
    assert result["candidates"] == []
    assert result["failure"] == "provider_error"

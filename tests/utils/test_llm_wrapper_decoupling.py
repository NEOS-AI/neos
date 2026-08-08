"""콜렉터의 어댑터가 LangChain 타입에 묶여 있지 않다 (D1a, D-8 b안).

`TrackedLLM` 은 LangChain LLM 을 감싸지만 그 **타입을 알 필요는 없다.**
`_extract_*` 가 `isinstance(BaseMessage/LLMResult)` 로 분기하는 한, 코딩 루프의
`CanonicalMessage` 와 deep_analysis 의 `LLMResponse` 는 계측될 수 없다 --
로드맵 §11.1 이 지목한 장애물 ①이다. 그리고 D4(네이티브 SDK 전환)가 LangChain
타입을 걷어내는 순간 계측이 통째로 깨진다.

여기서 고정하는 것은 두 가지다: (1) 모듈이 langchain 을 import 하지 않는다,
(2) LangChain 모양이든 아니든 같은 `LLMCallRecord` 필드가 나온다.
"""

from pathlib import Path

import pytest

from neos.utils.llm_wrapper import TrackedLLM


pytestmark = pytest.mark.no_db


def _tracked() -> TrackedLLM:
    return TrackedLLM(llm=object(), session_id="s", user_id="u")


def test_the_wrapper_module_does_not_import_langchain():
    """D1a 의 완료 기준. D4 의 선행 조건이기도 하다."""
    source = Path("neos/utils/llm_wrapper.py").read_text()

    assert "langchain" not in source


# --- LangChain 모양을 흉내내는 최소 더블 (langchain 을 import 하지 않는다) ---


class _LangChainishMessage:
    """`BaseMessage` 의 오리 -- `.type` 과 `.content` 를 가진다."""

    def __init__(self, type_: str, content: str) -> None:
        self.type = type_
        self.content = content


class _LangChainishResult:
    """`LLMResult` 의 오리 -- `.llm_output` 과 `.generations` 를 가진다."""

    class _Gen:
        def __init__(self, text: str) -> None:
            self.text = text

    def __init__(self, text: str, usage: dict | None = None) -> None:
        self.llm_output = {"token_usage": usage} if usage else None
        self.generations = [[self._Gen(text)]]


class _Canonicalish:
    """코딩 루프 쪽 모양 -- `.content` 만 있고 `.type` 이 없다."""

    def __init__(self, content: str) -> None:
        self.content = content


def test_a_string_prompt_becomes_one_user_message():
    assert _tracked()._extract_messages("안녕") == [
        {"role": "user", "content": "안녕"}
    ]


def test_a_langchain_shaped_message_keeps_its_role():
    messages = [_LangChainishMessage("human", "질문")]

    assert _tracked()._extract_messages(messages) == [
        {"role": "human", "content": "질문"}
    ]


def test_a_plain_dict_message_passes_through():
    messages = [{"role": "system", "content": "지시"}]

    assert _tracked()._extract_messages(messages) == messages


def test_a_message_without_a_role_defaults_to_user():
    """코딩 루프의 `CanonicalMessage` 처럼 `.type` 이 없는 모양."""
    messages = [_Canonicalish("본문")]

    assert _tracked()._extract_messages(messages) == [
        {"role": "user", "content": "본문"}
    ]


def test_usage_comes_out_of_a_langchain_shaped_result():
    result = _LangChainishResult(
        "답",
        usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    )

    assert _tracked()._extract_usage(result) == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }


def test_text_comes_out_of_a_langchain_shaped_result():
    assert _tracked()._extract_output_text(_LangChainishResult("답")) == "답"


def test_text_comes_out_of_a_content_bearing_response():
    assert _tracked()._extract_output_text(_Canonicalish("답")) == "답"


def test_a_result_without_usage_reports_none_rather_than_zeros():
    """0 을 지어내면 §6 ④(API usage 만 쓴다)를 어기는 자체 추정이 된다."""
    assert _tracked()._extract_usage(_LangChainishResult("답")) is None

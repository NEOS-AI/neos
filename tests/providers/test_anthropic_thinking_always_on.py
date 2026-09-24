"""thinking 을 끌 수 없는 모델에 `{type: "disabled"}` 를 보내지 않는다.

claude-opus-5-5 와 claude-fable-5-1 은 disabled 를 모든 effort 에서 400 으로
거절한다. 검색 에이전트의 `DISABLE_THINKING_FOR_SEARCH`(기본 켜짐)가 이
모델로 라우팅되면 매 요청이 실패한다.
"""

import pytest

from neos.config.model_config import get_model_spec
from neos.providers.anthropic import normalize_anthropic_request

pytestmark = pytest.mark.no_db

ALWAYS_ON = ("claude-opus-5-5", "claude-fable-5-1")


@pytest.mark.parametrize("model", ALWAYS_ON)
def test_catalog_declares_the_always_on_models(model: str) -> None:
    spec = get_model_spec(model)
    assert spec is not None and spec.thinking_always_on


def test_always_on_is_not_declared_by_default() -> None:
    # 끌 수 있는 adaptive 모델까지 번역하면 그 모델의 "빠른 응답" 이 사라진다.
    spec = get_model_spec("claude-sonnet-5")
    assert spec is not None and not spec.thinking_always_on


@pytest.mark.parametrize("model", ALWAYS_ON)
def test_thinking_off_never_sends_disabled(model: str) -> None:
    params = normalize_anthropic_request(
        model, {"model": model, "temperature": 0.1}, thinking_enabled=False
    )
    assert params.get("thinking") != {"type": "disabled"}
    assert "temperature" not in params


def test_thinking_off_still_disables_on_a_model_that_allows_it() -> None:
    params = normalize_anthropic_request(
        "claude-sonnet-5", {"model": "claude-sonnet-5"}, thinking_enabled=False
    )
    assert params["thinking"] == {"type": "disabled"}

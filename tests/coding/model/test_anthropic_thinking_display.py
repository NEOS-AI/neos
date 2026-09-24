"""K4b -- adaptive thinking 의 `display` 가 요청에 실리는 자리.

2026-09-24 실측(`artifacts/fable-k1b/`): Fable 5.1 에 `display` 를 보내지 않으면
thinking 본문이 **빈다** -- 서버 기본은 `omitted` 이고 SDK 독스트링의
`summarized` 는 틀렸다. 그래서 K4a 상태 줄이 이 모델에서 늘 비어 있었다.
"""

from __future__ import annotations

import pytest

from neos.coding.model.anthropic import THINKING_UPDATES_BETA, _to_anthropic_request
from neos.coding.model.base import CanonicalMessage, ModelLimits, ModelRequest, TextContent
from neos.config.model_config import ModelSpec, thinking_display_for

pytestmark = pytest.mark.no_db


def _payload(model: str) -> dict[str, object]:
    return _to_anthropic_request(
        ModelRequest(
            system="s",
            messages=(CanonicalMessage(role="user", content=(TextContent(text="hi"),)),),
            tools=(),
            model=model,
            limits=ModelLimits(max_output_tokens=4096, timeout_sec=120.0),
            task_id="t",
            run_id="r",
            turn_id="turn",
        )
    )


def test_fable_asks_for_progress_updates() -> None:
    payload = _payload("claude-fable-5-1")
    assert payload["thinking"] == {"type": "adaptive", "display": "updates"}
    assert THINKING_UPDATES_BETA in payload["extra_headers"]["anthropic-beta"].split(",")


@pytest.mark.parametrize("model", ["claude-opus-5", "claude-sonnet-5", "claude-opus-4-8"])
def test_other_models_send_no_thinking_key(model: str) -> None:
    """선언하지 않은 모델의 요청은 예전과 바이트가 같다 -- 키도 베타도 없다."""
    payload = _payload(model)
    assert "thinking" not in payload
    assert "extra_headers" not in payload


def test_only_fable_declares_a_display() -> None:
    assert thinking_display_for("claude-fable-5-1") == "updates"
    assert thinking_display_for("claude-opus-5") is None
    assert thinking_display_for("claude-from-the-future") is None


def test_display_is_refused_on_a_non_adaptive_model() -> None:
    with pytest.raises(ValueError, match="adaptive"):
        ModelSpec(provider="anthropic", thinking="budgeted", thinking_display="updates")


def test_an_unknown_display_is_refused_at_load() -> None:
    """서버는 모르는 값을 400 으로 거절한다(실측) -- 카탈로그가 먼저 막는다."""
    with pytest.raises(ValueError):
        ModelSpec(provider="anthropic", thinking="adaptive", thinking_display="verbose")

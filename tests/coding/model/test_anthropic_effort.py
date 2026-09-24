"""사고량이 요청에 실리는 자리 (로드맵 K5 ③).

게이트는 **여기 없다.** `resolve_effort` 가 이미 "이 모델이 이 레벨을
받는가" 를 물었고, 그 판단을 여기서 다시 하면 한쪽만 고쳐지는 날이 온다.
어댑터는 받은 것을 충실히 렌더링한다 -- 비어 있으면 키 자체를 넣지 않는다.

키를 넣지 않는 것이 중요하다. `output_config: {"effort": None}` 을 보내는
것과 `output_config` 를 아예 안 보내는 것은 다른 요청이고, K5 의 배선
커밋들이 "요청이 예전과 바이트가 같다" 를 주장하려면 후자여야 한다.
"""

from __future__ import annotations

import pytest

from neos.coding.model.base import (
    CanonicalMessage,
    ModelLimits,
    ModelRequest,
    TextContent,
)

pytestmark = pytest.mark.no_db


def _request(**limit_kwargs) -> ModelRequest:
    limits = {"max_output_tokens": 4096, "timeout_sec": 120.0}
    limits.update(limit_kwargs)
    return ModelRequest(
        system="s",
        messages=(
            CanonicalMessage(role="user", content=(TextContent(text="안녕"),)),
        ),
        tools=(),
        model="claude-opus-5-5",
        limits=ModelLimits(**limits),
        task_id="t",
        run_id="r",
        turn_id="turn",
    )


def test_no_effort_means_no_output_config_key() -> None:
    """K5 의 기본 상태 -- 요청이 예전과 바이트가 같다."""
    from neos.coding.model.anthropic import _to_anthropic_request

    payload = _to_anthropic_request(_request())

    assert "output_config" not in payload


def test_an_effort_rides_in_output_config() -> None:
    """SDK 가 정한 자리다 -- `message_create_params.output_config`."""
    from neos.coding.model.anthropic import _to_anthropic_request

    payload = _to_anthropic_request(_request(effort="high"))

    assert payload["output_config"] == {"effort": "high"}


def test_the_effort_does_not_disturb_the_rest_of_the_payload() -> None:
    """추가는 추가여야 한다 -- 다른 필드가 움직이면 그것은 다른 요청이다."""
    from neos.coding.model.anthropic import _to_anthropic_request

    without = _to_anthropic_request(_request())
    with_effort = _to_anthropic_request(_request(effort="low"))

    assert {k: v for k, v in with_effort.items() if k != "output_config"} == without

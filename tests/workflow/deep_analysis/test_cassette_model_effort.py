"""카세트 키가 사고량을 안다 (로드맵 K5 ③ × J3).

effort 가 요청에 실리기 시작하면 카세트에 구멍이 하나 생긴다: **low 로 녹음한
턴이 high 요청에서 적중한다.** 그러면 섀도가 "존재하지 않는 실행" 을
비교하게 되고, 그것은 `test_an_edited_tool_description_misses` 가 막으려던
것과 같은 사고다 -- 모델이 본 것이 달라졌으면 그 녹음은 증거가 아니다.

사고량은 모델이 **본** 것이 아니라 모델이 **어떻게 생각하는가**지만, 답을
바꾸는 것은 같다. 그래서 키에 들어간다.
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


def _request(effort: str = "") -> ModelRequest:
    return ModelRequest(
        system="s",
        messages=(
            CanonicalMessage(role="user", content=(TextContent(text="질문"),)),
        ),
        tools=(),
        model="claude-opus-5-5",
        limits=ModelLimits(
            max_output_tokens=4096, timeout_sec=120.0, effort=effort
        ),
        task_id="t",
        run_id="r",
        turn_id="turn",
    )


def test_two_efforts_are_two_keys() -> None:
    from neos.workflow.deep_analysis.cassette_model import request_key_payload

    assert request_key_payload(_request("low")) != request_key_payload(
        _request("high")
    )


def test_no_effort_is_its_own_key() -> None:
    """"안 보냈다" 와 "low 로 보냈다" 는 다른 실행이다."""
    from neos.workflow.deep_analysis.cassette_model import request_key_payload

    assert request_key_payload(_request()) != request_key_payload(_request("low"))


def test_the_same_effort_still_hits() -> None:
    """구별이 지나치면 재생이 영원히 빗나간다 -- 양쪽을 다 건다."""
    from neos.workflow.deep_analysis.cassette_model import request_key_payload

    assert request_key_payload(_request("high")) == request_key_payload(
        _request("high")
    )

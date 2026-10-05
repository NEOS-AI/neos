"""D107: 체크포인트 가림이 모델 입력을 지우지 않는다.

자식의 다음 턴은 체크포인트 상태에서 다시 지어진다. 깊이 6 에서 자르면 `list_tree` 의 항목과
도구 인자의 `path` 가 모델에게 `<redacted>` 로 보였다 -- 표본 #26 의 compose 자식이 "Paths are
redacted" 라고 적고 우회하다 턴 상한에 걸렸다. 비밀 키 가림은 깊이와 무관하게 남아야 한다.
"""

from __future__ import annotations

from neos.coding.redact import redact_sensitive
from neos.subagent.identity import persist_payload


def _state():
    return {
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [{"name": "read_file.v1", "input": {"path": "claims/INDEX.md"}}],
            },
            {
                "role": "tool",
                "name": "list_tree.v1",
                "content": {"entries": [{"path": "claims/q1.md", "kind": "file", "size": 12}]},
            },
            {"role": "tool", "content": {"nested": {"api_key": "sk-live-123", "deep": {"x": {"y": {"token": "t"}}}}}},
        ]
    }


def test_a_checkpoint_keeps_what_the_model_must_see():
    saved = persist_payload(_state())
    assert saved["messages"][0]["tool_calls"][0]["input"]["path"] == "claims/INDEX.md"
    assert saved["messages"][1]["content"]["entries"][0]["path"] == "claims/q1.md"


def test_secret_keys_are_still_redacted_at_any_depth():
    saved = persist_payload(_state())
    nested = saved["messages"][2]["content"]["nested"]
    assert nested["api_key"] == "<redacted>"
    assert nested["deep"]["x"]["y"]["token"] == "<redacted>"


def test_the_default_depth_is_unchanged_for_other_callers():
    """다른 24 곳의 호출부는 예전과 같은 바이트를 받는다."""
    assert redact_sensitive(_state())["messages"][1]["content"]["entries"][0]["path"] == "<redacted>"

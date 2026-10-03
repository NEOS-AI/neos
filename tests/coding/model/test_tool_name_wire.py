"""도구 이름의 와이어 규칙 (DECISIONS D106).

공급자는 `^[a-zA-Z0-9_-]{1,64}$` 밖의 도구 이름을 받지 않는다 -- 2026-10-03 Anthropic 실호출이
`submit.v1` 을 400 으로 거절했다. 가짜 클라이언트는 이름을 검사하지 않으므로 이 규칙은 **여기서**
검사한다: 네 어댑터의 요청 payload 에서 이름이 나오는 모든 자리를 훑어 규칙에 맞는지 본다.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from neos.coding.model.anthropic import AnthropicCodingModel, _to_anthropic_request
from neos.coding.model.base import (
    CanonicalMessage,
    ModelLimits,
    ModelRequest,
    TextContent,
    ToolAdditionContent,
    ToolDefinition,
    ToolInputDelta,
    ToolResultContent,
    ToolUseContent,
)
from neos.coding.model.errors import CodingModelError
from neos.coding.model.gemini import _to_gemini_request
from neos.coding.model.names import ToolNameCodec
from neos.coding.model.ollama import _to_ollama_request
from neos.coding.model.openai import _to_openai_request
from tests.coding.model.test_anthropic import FakeAnthropicClient, content_start, event, input_delta

WIRE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _tool(name: str, *, deferred: bool = False) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="d",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        deferred=deferred,
    )


def _request() -> ModelRequest:
    """도구 목록 · 이력의 tool_use · tool_result · deferred 공개 -- 이름이 나오는 자리 전부."""
    return ModelRequest(
        system="s",
        messages=(
            CanonicalMessage(role="user", content=(TextContent("go"),)),
            CanonicalMessage(
                role="assistant",
                content=(ToolUseContent("toolu_1", "read_file.v1", {"path": "a"}),),
            ),
            CanonicalMessage(
                role="tool",
                content=(ToolResultContent("toolu_1", "ok", {"text": "x"}),),
            ),
            CanonicalMessage(role="system", content=(ToolAdditionContent("search_text.v1"),)),
        ),
        tools=(_tool("read_file.v1"), _tool("submit.v1"), _tool("search_text.v1", deferred=True)),
        model="claude-test",
        limits=ModelLimits(max_output_tokens=10, timeout_sec=5),
        task_id="t",
        run_id="r",
        turn_id="u",
    )


def _names(payload) -> list[str]:
    """payload 안의 모든 `name` 값(tool_result 의 Gemini `function_response.name` 은 call id 라 뺀다)."""
    found: list[str] = []

    def walk(node, parent_key=""):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "name" and isinstance(value, str) and parent_key != "function_response":
                    found.append(value)
                walk(value, key)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item, parent_key)

    walk(payload)
    return found


@pytest.mark.parametrize(
    "build",
    [_to_anthropic_request, _to_openai_request, _to_gemini_request, _to_ollama_request],
    ids=["anthropic", "openai", "gemini", "ollama"],
)
def test_every_name_on_the_wire_obeys_the_provider_rule(build):
    names = _names(build(_request()))
    assert names, "payload 에서 이름을 하나도 못 찾았다 -- 이 검사가 공허하다"
    assert [n for n in names if not WIRE.match(n)] == []
    assert "read_file_v1" in names


def test_valid_names_pass_unchanged_and_dotted_ones_round_trip():
    codec = ToolNameCodec(["read_file.v1", "ask_user", "mcp__srv__tool"])
    assert codec.wire("ask_user") == "ask_user"
    assert codec.wire("mcp__srv__tool") == "mcp__srv__tool"
    assert codec.original(codec.wire("read_file.v1")) == "read_file.v1"
    assert codec.original("made_up_tool") == "made_up_tool"  # 지어낸 이름은 레지스트리가 거절한다


def test_a_collision_fails_loudly():
    with pytest.raises(CodingModelError) as info:
        ToolNameCodec(["read_file.v1", "read_file_v1"])
    assert info.value.code == "tool_name_collision"


async def test_the_anthropic_stream_returns_the_original_name():
    client = FakeAnthropicClient(
        [
            event("message_start", message=SimpleNamespace(usage=SimpleNamespace(input_tokens=1, output_tokens=0))),
            content_start(0, "toolu_9", "submit_v1"),
            input_delta(0, "{}"),
            event("content_block_stop", index=0),
            event("message_delta", delta=SimpleNamespace(stop_reason="tool_use"), usage=SimpleNamespace(output_tokens=1)),
        ]
    )
    events = [item async for item in AnthropicCodingModel(client).stream(_request())]
    assert ToolInputDelta("toolu_9", "submit.v1", "{}") in events
    sent = client.messages.requests[0]
    assert [t["name"] for t in sent["tools"]] == ["read_file_v1", "submit_v1", "search_text_v1"]

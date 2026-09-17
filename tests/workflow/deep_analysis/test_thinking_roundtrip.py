"""Deep analysis replays thinking blocks through both call paths (K1c).

`run_discovery` appends `response.content` as the next assistant turn, so a
block dropped on the way out is a block missing on the way back in.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from neos.coding.harness import ModelTurn
from neos.coding.model.base import (
    ModelCompleted,
    ModelUsage,
    ThinkingCompleted,
    ThinkingContent,
    ToolCallCompleted,
)
from neos.workflow.deep_analysis.harness_bridge import (
    messages_to_canonical,
    turn_to_llm_response,
)
from neos.workflow.deep_analysis.llm import _blocks_to_dicts

pytestmark = pytest.mark.no_db

THINKING_BLOCK = {
    "type": "thinking",
    "thinking": "Check arxiv first",
    "signature": "sig-da-1",
}


def test_thinking_blocks_become_canonical_thinking() -> None:
    messages = messages_to_canonical(
        [
            {"role": "user", "content": "조사해"},
            {
                "role": "assistant",
                "content": [
                    THINKING_BLOCK,
                    {"type": "text", "text": "검색"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "search_arxiv",
                        "input": {"query": "moe"},
                    },
                ],
            },
        ]
    )

    assert messages[1].content[0] == ThinkingContent("Check arxiv first", "sig-da-1")


def test_harness_turn_carries_thinking_into_the_next_request() -> None:
    turn = ModelTurn(
        text_parts=("검색",),
        tool_calls=(ToolCallCompleted("toolu_1", "search_arxiv", {"query": "moe"}),),
        completion=ModelCompleted("tool_use", ModelUsage(7, 3)),
        thinking=(ThinkingCompleted("Check arxiv first", "sig-da-1"),),
    )

    response = turn_to_llm_response("claude-sonnet-5", turn)

    assert response.content[0] == THINKING_BLOCK
    replayed = messages_to_canonical(
        [
            {"role": "user", "content": "조사해"},
            {"role": "assistant", "content": response.content},
        ]
    )
    assert replayed[1].content[0] == ThinkingContent("Check arxiv first", "sig-da-1")


def test_injected_sdk_blocks_keep_thinking() -> None:
    blocks = _blocks_to_dicts(
        [
            SimpleNamespace(
                type="thinking", thinking="Check arxiv first", signature="sig-da-1"
            ),
            SimpleNamespace(type="text", text="검색"),
        ]
    )

    assert blocks[0] == THINKING_BLOCK
    assert blocks[1] == {"type": "text", "text": "검색"}


def test_unsigned_thinking_block_is_dropped_rather_than_replayed() -> None:
    blocks = _blocks_to_dicts(
        [SimpleNamespace(type="thinking", thinking="no signature", signature="")]
    )

    assert blocks == []
    assert (
        messages_to_canonical(
            [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "no signature", "signature": ""},
                        {"type": "text", "text": "검색"},
                    ],
                }
            ]
        )[0].content
        == messages_to_canonical(
            [{"role": "assistant", "content": [{"type": "text", "text": "검색"}]}]
        )[0].content
    )

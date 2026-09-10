"""Finding 5 — attachment_notices must survive the dispatcher hop.

`chat_llm_service`의 4개 경로 모두 "complete" chunk 에 `attachment_notices` 를
싣지만, `ChunkEventDispatcher._handle_complete` 가 usage/cost/latency_ms 만
읽고 그것을 버렸다. 이 테스트는 dispatch 뒤 `StreamAccumulator` 에
`attachment_notices` 가 남아 있는지, 없을 때는 조용히 None 인지를 확인한다.
"""

import pytest

from neos.api.adapters.stream_adapter import StreamAdapterState
from neos.api.services.chat_chunk_dispatcher import (
    ChunkEventDispatcher,
    StreamAccumulator,
)


def _dispatcher() -> tuple[ChunkEventDispatcher, StreamAccumulator]:
    acc = StreamAccumulator()
    dispatcher = ChunkEventDispatcher(
        stream_state=StreamAdapterState(),
        accumulator=acc,
        user_id="u1",
        conversation_id="c1",
    )
    return dispatcher, acc


@pytest.mark.asyncio
async def test_complete_chunk_forwards_attachment_notices() -> None:
    dispatcher, acc = _dispatcher()

    chunk = {
        "type": "complete",
        "usage": {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0},
        "cost": {"total_cost": 0.0},
        "latency_ms": 12.5,
        "attachment_notices": ["old.png: 길이 상한으로 제외됨"],
    }

    events = [event async for event in dispatcher.dispatch(chunk)]

    assert events == []  # complete 는 SSE 이벤트를 내지 않는다 (usage/cost 처럼)
    assert acc.attachment_notices == ["old.png: 길이 상한으로 제외됨"]
    # usage/cost 도 여전히 옮겨진다 — 회귀 방지
    assert acc.usage_info == chunk["usage"]
    assert acc.cost_info == chunk["cost"]
    assert acc.latency_ms == 12.5


@pytest.mark.asyncio
async def test_complete_chunk_without_notices_leaves_it_none() -> None:
    dispatcher, acc = _dispatcher()

    chunk = {
        "type": "complete",
        "usage": {"total_tokens": 1, "prompt_tokens": 1, "completion_tokens": 0},
        "cost": {"total_cost": 0.0},
        "latency_ms": 5.0,
    }

    async for _ in dispatcher.dispatch(chunk):
        pass

    assert acc.attachment_notices is None

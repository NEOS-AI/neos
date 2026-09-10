"""N8 리뷰 Finding 5 — 거부 사유 `code` 가 클라이언트까지 살아남아야 한다.

`ChunkEventDispatcher._handle_error` 는 `chunk["code"]` 를 버리고
`ErrorInfo(type="server_error", message=...)` 만 만들었다 — 그러면
클라이언트는 첨부 거부와 다른 모든 실패를 구별할 수 없다.
"""

import pytest

from neos.api.adapters.stream_adapter import StreamAdapterState
from neos.api.models.open_responses import ResponseObject, ResponseStatus
from neos.api.services.chat_chunk_dispatcher import (
    ChunkEventDispatcher,
    StreamAccumulator,
)


def _dispatcher() -> ChunkEventDispatcher:
    state = StreamAdapterState()
    state.response = ResponseObject(id="r1", status=ResponseStatus.IN_PROGRESS, output=[])
    return ChunkEventDispatcher(
        stream_state=state,
        accumulator=StreamAccumulator(),
        user_id="u1",
        conversation_id="c1",
    )


@pytest.mark.asyncio
async def test_error_chunk_carries_its_code_through() -> None:
    dispatcher = _dispatcher()

    chunk = {
        "type": "error",
        "error": "blind-model는 첨부 1개(scan.png)를 받지 않습니다.",
        "code": "attachment_unsupported",
    }

    async for _ in dispatcher.dispatch(chunk):
        pass

    error = dispatcher._state.response.error
    assert error.code == "attachment_unsupported"
    assert error.message == chunk["error"]
    assert error.type == "server_error"  # 모양은 바뀌지 않는다


@pytest.mark.asyncio
async def test_error_chunk_without_code_keeps_the_shape_unchanged() -> None:
    dispatcher = _dispatcher()

    chunk = {"type": "error", "error": "boom"}

    async for _ in dispatcher.dispatch(chunk):
        pass

    error = dispatcher._state.response.error
    assert error.code is None
    assert error.message == "boom"

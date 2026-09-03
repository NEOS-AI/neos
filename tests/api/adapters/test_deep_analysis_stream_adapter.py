"""legacy 스트림 이벤트 → neos:deep_analysis_started 변환 고정 (D23).

챗 SSE 배관(워크플로우 이벤트 → `neos:deep_analysis_started`)은
`tests/api/services/test_chat_stream_pipeline_autonomy.py`가
`_run_workflow`를 실제로 돌려서 고정한다.

여기 있던 `test_chat_handler_maps_deep_analysis_started`는 그 배관을
`chat_handlers.py`의 **소스 문자열**로 확인했는데, 그 파일에서 분기를 갖고
있던 것은 프론트가 쓰지 않는 `stream_message_legacy` 쪽이었다. 운영 경로
(`ChatStreamPipeline`)에는 분기가 없는데도 테스트는 초록이었다 —
문자열 검사는 "어느 코드가 실행되는가"를 묻지 못한다. 그래서 지웠다.
"""

import pytest

pytestmark = pytest.mark.no_db


def test_adapter_converts_deep_analysis_started():
    from neos.api.adapters.stream_adapter import (
        StreamAdapterState,
        adapt_legacy_event,
    )

    state = StreamAdapterState()
    events = adapt_legacy_event(
        {
            "type": "deep_analysis_started",
            "data": {
                "run_id": "run00009",
                "events_url": "/api/v1/deep-analysis/run00009/events",
                "assistant_message_id": "msg-9",
            },
        },
        state,
    )

    assert len(events) == 1
    dumped = events[0].model_dump()
    assert dumped["type"] == "neos:deep_analysis_started"
    assert dumped["run_id"] == "run00009"
    assert dumped["events_url"] == "/api/v1/deep-analysis/run00009/events"
    assert dumped["assistant_message_id"] == "msg-9"

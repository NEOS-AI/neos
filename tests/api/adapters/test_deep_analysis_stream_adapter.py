"""legacy 스트림 이벤트 → neos:deep_analysis_started 변환 고정 (D23)."""

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


def test_chat_handler_maps_deep_analysis_started():
    """챗 SSE 루프가 이 이벤트를 흘려보내는지 소스 수준으로 고정한다.

    챗 스트리밍 루프는 LLM/DB에 깊이 얽혀 있어 단위 실행이 비싸다. 배관이
    빠지면 프론트가 job 핸들을 아예 못 받으므로(AC4 파손) 최소한 존재는
    강제한다.
    """
    from pathlib import Path

    source = Path("neos/api/handlers/chat_handlers.py").read_text(encoding="utf-8")
    assert 'event.event == "deep_analysis_started"' in source
    assert "NeosDeepAnalysisStartedEvent" in source

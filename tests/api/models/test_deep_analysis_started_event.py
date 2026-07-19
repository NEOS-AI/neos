"""Phase 3b 챗 SSE 계약 고정 (D23).

이 이벤트의 필드 이름은 프론트엔드와 공유된 계약이다. 바꾸려면 FE와 동기화가
필요하므로 테스트로 못 박는다.
"""

import pytest

pytestmark = pytest.mark.no_db


def test_deep_analysis_started_event_shape():
    from neos.api.models.open_responses import NeosDeepAnalysisStartedEvent

    event = NeosDeepAnalysisStartedEvent(
        run_id="run00001",
        events_url="/api/v1/deep-analysis/run00001/events",
        assistant_message_id="msg-1",
    )
    dumped = event.model_dump()
    assert dumped == {
        "type": "neos:deep_analysis_started",
        "run_id": "run00001",
        "events_url": "/api/v1/deep-analysis/run00001/events",
        "assistant_message_id": "msg-1",
    }


def test_assistant_message_id_is_optional():
    """대화 밖에서 시작된 run(예: /api/v1/query)은 메시지가 없다."""
    from neos.api.models.open_responses import NeosDeepAnalysisStartedEvent

    event = NeosDeepAnalysisStartedEvent(
        run_id="run00002",
        events_url="/api/v1/deep-analysis/run00002/events",
    )
    assert event.assistant_message_id is None


def test_stream_event_type_constant():
    from neos.api.models.query_models import WorkflowStreamEventType

    assert WorkflowStreamEventType.DEEP_ANALYSIS_STARTED == "deep_analysis_started"


@pytest.mark.asyncio
async def test_callback_enqueues_deep_analysis_started():
    import asyncio

    from neos.api.handlers.workflow_stream_handlers import WorkflowStreamCallback

    queue = asyncio.Queue()
    cb = WorkflowStreamCallback(
        session_id="conv-1", event_queue=queue, enable_db_logging=False
    )
    await cb.on_deep_analysis_started(
        run_id="run00003",
        events_url="/api/v1/deep-analysis/run00003/events",
        assistant_message_id="msg-3",
    )

    event = queue.get_nowait()
    assert event.event == "deep_analysis_started"
    assert event.data == {
        "run_id": "run00003",
        "events_url": "/api/v1/deep-analysis/run00003/events",
        "assistant_message_id": "msg-3",
    }

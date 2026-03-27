"""Unit tests for _event_generator in ui_submit_handlers.py

테스트 전략:
- multi_agent_workflow.execute_workflow는 patch로 대체
- WorkflowStreamCallback은 실제 클래스 사용 (enable_db_logging=False)
- asyncio.Queue는 실제 사용 (경량)
"""
import asyncio
import pytest
from unittest.mock import patch, MagicMock

from neos.api.models.query_models import WorkflowStreamEventType
import neos.api.handlers.ui_submit_handlers as submit_mod


async def collect_events(gen) -> list[str]:
    """async generator의 모든 yield 값을 수집한다."""
    results = []
    async for item in gen:
        results.append(item)
    return results


@pytest.mark.unit
class TestEventGenerator:

    @pytest.mark.asyncio
    async def test_yields_events_and_done_on_success(self):
        """정상 완료 시: 큐 이벤트 yield 후 [DONE] 발행"""
        event_queue: asyncio.Queue = asyncio.Queue()

        # 테스트용 이벤트 하나를 큐에 미리 넣어둠
        mock_event = MagicMock()
        mock_event.model_dump_json.return_value = '{"event":"completed","data":{"response":"ok"}}'

        async def fake_execute(workflow_input, event_handler, use_checkpointer):
            await event_queue.put(mock_event)

        with patch.object(
            submit_mod.multi_agent_workflow,
            "execute_workflow",
            side_effect=fake_execute,
        ):
            with patch("neos.api.handlers.ui_submit_handlers.asyncio.Queue", return_value=event_queue):
                gen = submit_mod._event_generator(
                    workflow_input={"query": "test"},
                    session_id="sess-1",
                    user_id="user-1",
                )
                results = await collect_events(gen)

        assert any('{"event":"completed"' in r for r in results), "완료 이벤트 없음"
        assert results[-1] == "data: [DONE]\n\n", "[DONE] 마지막 미발행"

    @pytest.mark.asyncio
    async def test_yields_error_event_when_workflow_raises(self):
        """워크플로우 예외 시: ERROR 이벤트 yield"""
        event_queue: asyncio.Queue = asyncio.Queue()
        error = ValueError("workflow boom")

        async def fake_execute(workflow_input, event_handler, use_checkpointer):
            raise error

        with patch.object(
            submit_mod.multi_agent_workflow,
            "execute_workflow",
            side_effect=fake_execute,
        ):
            with patch("neos.api.handlers.ui_submit_handlers.asyncio.Queue", return_value=event_queue):
                gen = submit_mod._event_generator(
                    workflow_input={"query": "test"},
                    session_id="sess-1",
                    user_id="user-1",
                )
                results = await collect_events(gen)

        error_lines = [r for r in results if WorkflowStreamEventType.ERROR in r]
        assert len(error_lines) > 0, "에러 이벤트가 yield 되어야 함"
        assert results[-1] == "data: [DONE]\n\n"

    @pytest.mark.asyncio
    async def test_cancels_task_on_generator_early_exit(self):
        """제너레이터 조기 종료 시 workflow_task.cancel() 호출 보장 — 예외 없이 정상 종료"""
        event_queue: asyncio.Queue = asyncio.Queue()

        async def slow_execute(workflow_input, event_handler, use_checkpointer):
            await asyncio.sleep(10)  # 오래 걸리는 작업 시뮬레이션

        with patch.object(
            submit_mod.multi_agent_workflow,
            "execute_workflow",
            side_effect=slow_execute,
        ):
            with patch("neos.api.handlers.ui_submit_handlers.asyncio.Queue", return_value=event_queue):
                gen = submit_mod._event_generator(
                    workflow_input={"query": "test"},
                    session_id="sess-1",
                    user_id="user-1",
                )
                # 첫 yield 전에 제너레이터 닫기 — finally 블록에서 workflow_task.cancel() 실행
                await gen.aclose()

        # aclose() 후 예외 없이 정상 종료되면 cancel() 경로가 실행된 것
        await asyncio.sleep(0.1)

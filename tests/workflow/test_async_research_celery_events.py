import logging
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

from neos.workflow import celery_tasks


def _install_workflow(monkeypatch, execute: AsyncMock) -> None:
    fake_graph = SimpleNamespace(
        multi_agent_workflow=SimpleNamespace(execute_workflow=execute)
    )
    monkeypatch.setitem(sys.modules, "neos.workflow.graph", fake_graph)


async def test_workflow_publishes_started_then_completed(monkeypatch) -> None:
    execute = AsyncMock(return_value={"answer": "done"})
    _install_workflow(monkeypatch, execute)
    append = AsyncMock(side_effect=["1-0", "2-0"])
    monkeypatch.setattr(
        celery_tasks.async_research_event_stream, "append", append
    )

    result = await celery_tasks._execute_workflow_full_async(
        query="q",
        user_id="u1",
        conversation_id="c1",
        session_id="s1",
        language="ko",
        celery_task_id="j1",
    )

    assert append.await_args_list == [
        call("s1", "workflow_started", {"task_id": "j1", "query": "q"}),
        call(
            "s1",
            "workflow_completed",
            {"task_id": "j1", "status": "completed"},
        ),
    ]
    execute.assert_awaited_once()
    assert result == {
        "status": "completed",
        "task_id": "j1",
        "result": {"answer": "done"},
    }


async def test_start_publish_failure_prevents_workflow_execution(
    monkeypatch,
) -> None:
    execute = AsyncMock()
    _install_workflow(monkeypatch, execute)
    append = AsyncMock(side_effect=ConnectionError("redis unavailable"))
    monkeypatch.setattr(
        celery_tasks.async_research_event_stream, "append", append
    )

    with pytest.raises(ConnectionError, match="redis unavailable"):
        await celery_tasks._execute_workflow_full_async(
            query="q",
            user_id="u1",
            conversation_id="c1",
            session_id="s1",
            language="ko",
            celery_task_id="j1",
        )

    execute.assert_not_awaited()


async def test_completion_publish_failure_does_not_return_success(
    monkeypatch,
) -> None:
    execute = AsyncMock(return_value={"answer": "done"})
    _install_workflow(monkeypatch, execute)
    append = AsyncMock(
        side_effect=["1-0", ConnectionError("completion unavailable")]
    )
    monkeypatch.setattr(
        celery_tasks.async_research_event_stream, "append", append
    )

    with pytest.raises(ConnectionError, match="completion unavailable"):
        await celery_tasks._execute_workflow_full_async(
            query="q",
            user_id="u1",
            conversation_id="c1",
            session_id="s1",
            language="ko",
            celery_task_id="j1",
        )

    execute.assert_awaited_once()


async def test_publish_helper_returns_redis_event_id(monkeypatch) -> None:
    append = AsyncMock(return_value="42-0")
    monkeypatch.setattr(
        celery_tasks.async_research_event_stream, "append", append
    )

    event_id = await celery_tasks._publish_workflow_event(
        "s1", "workflow_failed", {"error": "boom"}
    )

    assert event_id == "42-0"
    append.assert_awaited_once_with(
        "s1", "workflow_failed", {"error": "boom"}
    )


def test_failure_publish_error_keeps_original_retry_cause(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    original_error = ValueError("workflow exploded")
    publish_error = ConnectionError("redis unavailable")
    errors = iter([original_error, publish_error])

    def fail_run_async(coroutine):
        coroutine.close()
        raise next(errors)

    run_async = Mock(side_effect=fail_run_async)
    retry = Mock(side_effect=lambda *, exc, countdown: exc)
    monkeypatch.setattr(celery_tasks, "run_async", run_async)
    monkeypatch.setattr(celery_tasks.execute_workflow_async, "retry", retry)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ValueError, match="workflow exploded"):
            celery_tasks.execute_workflow_async.run(
                query="q",
                user_id="u1",
                conversation_id="c1",
                session_id="s1",
            )

    retry.assert_called_once_with(exc=original_error, countdown=60)
    assert "Failed to publish workflow failure event" in caplog.text

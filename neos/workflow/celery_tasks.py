"""
Celery 태스크 정의 - 분산 에이전트 실행

Phase 3 Item 4: 에이전트를 Celery 태스크로 실행
"""

import asyncio
from typing import Dict, Any, List, Optional
import logging

from .celery_app import app
from .telemetry import trace_agent_execution
from neos.config.settings import settings

logger = logging.getLogger(__name__)


def run_async(coro):
    """
    Celery 태스크 내에서 async 함수 실행

    Celery는 동기 함수만 지원하므로 asyncio.run()으로 래핑
    """
    return asyncio.run(coro)


@app.task(bind=True, max_retries=3, default_retry_delay=30)
def execute_search_agent(
    self,
    agent_name: str,
    query: str,
    workflow_id: str,
    **kwargs
) -> Dict[str, Any]:
    """
    검색 에이전트 실행 태스크

    Args:
        agent_name: 에이전트 이름 (knowledge_search, realtime_info_search 등)
        query: 검색 쿼리
        workflow_id: 워크플로우 ID
        **kwargs: 추가 파라미터

    Returns:
        Dict: 검색 결과
    """
    try:
        logger.info(f"Executing search agent {agent_name} for workflow {workflow_id}")

        # 비동기 실행
        result = run_async(_execute_search_agent_async(
            agent_name, query, workflow_id, **kwargs
        ))

        logger.info(f"Search agent {agent_name} completed successfully")
        return result

    except Exception as e:
        logger.error(f"Search agent {agent_name} failed: {e}", exc_info=True)
        # 재시도
        raise self.retry(exc=e)


async def _execute_search_agent_async(
    agent_name: str,
    query: str,
    workflow_id: str,
    **kwargs
) -> Dict[str, Any]:
    """검색 에이전트 비동기 실행"""
    # Tracing
    with trace_agent_execution(agent_name, workflow_id) as span:
        # 에이전트 동적 import (on-demand)
        from neos.workflow.graph import multi_agent_workflow

        agents = multi_agent_workflow.agents
        agent = agents.get(agent_name)

        if not agent:
            raise ValueError(f"Unknown agent: {agent_name}")

        # 에이전트 실행
        result = await agent.execute(query, **kwargs)

        if span:
            span.set_attribute("result.count", len(result.get("results", [])))

        return {
            "agent": agent_name,
            "query": query,
            "result": result,
            "success": True
        }


@app.task(bind=True, max_retries=3)
def execute_analysis_agent(
    self,
    agent_name: str,
    data: Dict[str, Any],
    workflow_id: str,
    **kwargs
) -> Dict[str, Any]:
    """
    분석 에이전트 실행 태스크

    Args:
        agent_name: 에이전트 이름
        data: 분석할 데이터
        workflow_id: 워크플로우 ID
        **kwargs: 추가 파라미터
    """
    try:
        logger.info(f"Executing analysis agent {agent_name} for workflow {workflow_id}")

        result = run_async(_execute_analysis_agent_async(
            agent_name, data, workflow_id, **kwargs
        ))

        logger.info(f"Analysis agent {agent_name} completed")
        return result

    except Exception as e:
        logger.error(f"Analysis agent {agent_name} failed: {e}", exc_info=True)
        raise self.retry(exc=e)


async def _execute_analysis_agent_async(
    agent_name: str,
    data: Dict[str, Any],
    workflow_id: str,
    **kwargs
) -> Dict[str, Any]:
    """분석 에이전트 비동기 실행"""
    with trace_agent_execution(agent_name, workflow_id):
        from neos.workflow.graph import multi_agent_workflow

        agents = multi_agent_workflow.agents
        agent = agents.get(agent_name)

        if not agent:
            raise ValueError(f"Unknown agent: {agent_name}")

        result = await agent.execute(data, **kwargs)

        return {
            "agent": agent_name,
            "result": result,
            "success": True
        }


@app.task(bind=True, max_retries=3)
def execute_generation_agent(
    self,
    agent_name: str,
    prompt: str,
    workflow_id: str,
    **kwargs
) -> Dict[str, Any]:
    """
    생성 에이전트 실행 태스크

    Args:
        agent_name: 에이전트 이름
        prompt: 생성 프롬프트
        workflow_id: 워크플로우 ID
        **kwargs: 추가 파라미터
    """
    try:
        logger.info(f"Executing generation agent {agent_name} for workflow {workflow_id}")

        result = run_async(_execute_generation_agent_async(
            agent_name, prompt, workflow_id, **kwargs
        ))

        logger.info(f"Generation agent {agent_name} completed")
        return result

    except Exception as e:
        logger.error(f"Generation agent {agent_name} failed: {e}", exc_info=True)
        raise self.retry(exc=e)


async def _execute_generation_agent_async(
    agent_name: str,
    prompt: str,
    workflow_id: str,
    **kwargs
) -> Dict[str, Any]:
    """생성 에이전트 비동기 실행"""
    with trace_agent_execution(agent_name, workflow_id):
        from neos.workflow.graph import multi_agent_workflow

        agents = multi_agent_workflow.agents
        agent = agents.get(agent_name)

        if not agent:
            raise ValueError(f"Unknown agent: {agent_name}")

        result = await agent.execute(prompt, **kwargs)

        return {
            "agent": agent_name,
            "result": result,
            "success": True
        }


@app.task(bind=True)
def execute_agent_generic(
    self,
    agent_name: str,
    input_data: Any,
    workflow_id: str,
    **kwargs
) -> Dict[str, Any]:
    """
    범용 에이전트 실행 태스크

    어떤 에이전트든 실행 가능한 범용 태스크
    """
    try:
        logger.info(f"Executing agent {agent_name} (generic) for workflow {workflow_id}")

        result = run_async(_execute_agent_generic_async(
            agent_name, input_data, workflow_id, **kwargs
        ))

        return result

    except Exception as e:
        logger.error(f"Agent {agent_name} failed: {e}", exc_info=True)
        raise self.retry(exc=e)


async def _execute_agent_generic_async(
    agent_name: str,
    input_data: Any,
    workflow_id: str,
    **kwargs
) -> Dict[str, Any]:
    """범용 에이전트 비동기 실행"""
    with trace_agent_execution(agent_name, workflow_id):
        from neos.workflow.graph import multi_agent_workflow

        agents = multi_agent_workflow.agents
        agent = agents.get(agent_name)

        if not agent:
            raise ValueError(f"Unknown agent: {agent_name}")

        result = await agent.execute(input_data, **kwargs)

        return {
            "agent": agent_name,
            "result": result,
            "success": True
        }


# ============================================================================
# Phase 3.5: 전체 워크플로우 비동기 실행
# ============================================================================

@app.task(bind=True, max_retries=1, soft_time_limit=600, time_limit=660)
def execute_workflow_async(
    self,
    query: str,
    user_id: str,
    conversation_id: str,
    session_id: Optional[str] = None,
    language: str = "auto",
    **kwargs
) -> Dict[str, Any]:
    """
    전체 워크플로우를 Celery task로 비동기 실행

    deep_research, hyper_deep_research 등 무거운 intent에 사용.
    즉시 job_id를 반환하고, StreamManager를 통해 SSE 진행 이벤트 발행.
    """
    task_id = self.request.id
    logger.info(
        f"[Celery] Starting async workflow: task={task_id}, "
        f"session={session_id}, query={query[:50]}..."
    )

    try:
        result = run_async(_execute_workflow_full_async(
            query=query,
            user_id=user_id,
            conversation_id=conversation_id,
            session_id=session_id or conversation_id,
            language=language,
            celery_task_id=task_id,
            **kwargs,
        ))

        logger.info(f"[Celery] Workflow completed: task={task_id}")
        return result

    except Exception as e:
        logger.error(f"[Celery] Workflow failed: task={task_id}, error={e}", exc_info=True)

        # Publish failure event via StreamManager
        try:
            run_async(_publish_workflow_event(
                session_id or conversation_id,
                "workflow_failed",
                {"error": str(e), "task_id": task_id},
            ))
        except Exception:
            pass

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60)
        return {"status": "failed", "error": str(e), "task_id": task_id}


async def _execute_workflow_full_async(
    query: str,
    user_id: str,
    conversation_id: str,
    session_id: str,
    language: str,
    celery_task_id: str,
    **kwargs,
) -> Dict[str, Any]:
    """전체 워크플로우 비동기 실행 (Celery worker 내)"""
    from neos.workflow.graph import multi_agent_workflow
    from neos.workflow.stream_manager import stream_manager

    # SSE 이벤트로 워크플로우 시작 알림
    await stream_manager.add_event(
        session_id=session_id,
        event="workflow_started",
        data={"task_id": celery_task_id, "query": query[:100]},
    )

    # 워크플로우 실행
    result = await multi_agent_workflow.execute_workflow(
        user_input={
            "user_id": user_id,
            "session_id": session_id,
            "conversation_id": conversation_id,
            "query": query,
            "language": language,
            **kwargs,
        },
        use_checkpointer=True,
    )

    # SSE 이벤트로 완료 알림
    await stream_manager.add_event(
        session_id=session_id,
        event="workflow_completed",
        data={
            "task_id": celery_task_id,
            "status": "completed",
        },
    )

    return {
        "status": "completed",
        "task_id": celery_task_id,
        "result": result,
    }


async def _publish_workflow_event(
    session_id: str, event: str, data: Dict[str, Any]
) -> None:
    """StreamManager를 통해 워크플로우 이벤트 발행"""
    from neos.workflow.stream_manager import stream_manager
    await stream_manager.add_event(session_id=session_id, event=event, data=data)


# ============================================================================
# 유지보수 태스크
# ============================================================================

@app.task
def cleanup_old_checkpoints():
    """오래된 체크포인트 정리 (Celery Beat 스케줄)"""
    logger.info("Running scheduled checkpoint cleanup...")

    try:
        result = run_async(_cleanup_old_checkpoints_async())
        logger.info(f"Checkpoint cleanup completed: {result}")
        return result

    except Exception as e:
        logger.error(f"Checkpoint cleanup failed: {e}", exc_info=True)
        raise


async def _cleanup_old_checkpoints_async() -> Dict[str, int]:
    """오래된 체크포인트 비동기 정리"""
    from neos.workflow.checkpointer import get_checkpointer
    from datetime import datetime, timedelta

    checkpointer = await get_checkpointer()

    # 7일 이상 된 체크포인트 삭제
    cutoff_date = datetime.now() - timedelta(days=7)

    # 구현은 checkpointer에 cleanup 메서드 추가 필요
    # deleted_count = await checkpointer.cleanup_old(cutoff_date)

    return {
        "deleted_count": 0,  # Placeholder
        "cutoff_date": cutoff_date.isoformat()
    }


@app.task
def update_cache_statistics():
    """캐시 통계 업데이트 (Celery Beat 스케줄)"""
    logger.info("Updating cache statistics...")

    try:
        result = run_async(_update_cache_statistics_async())
        logger.info(f"Cache statistics updated: {result}")
        return result

    except Exception as e:
        logger.error(f"Cache statistics update failed: {e}", exc_info=True)
        raise


async def _update_cache_statistics_async() -> Dict[str, Any]:
    """캐시 통계 비동기 업데이트"""
    from neos.utils.smart_cache_manager import smart_cache_manager

    # 통계 수집
    stats = await smart_cache_manager.get_cache_statistics()

    # 통계를 DB나 메트릭 시스템에 저장
    # (구현 필요)

    return {
        "total_entries": stats.get("total_entries", 0),
        "hit_rate": stats.get("hit_rate", 0.0),
        "updated_at": datetime.now().isoformat()
    }

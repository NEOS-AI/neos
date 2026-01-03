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

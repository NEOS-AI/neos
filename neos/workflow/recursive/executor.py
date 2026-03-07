"""
RecursiveExecutor: atomic 태스크 실행기

Atomizer가 ATOMIC으로 판별한 태스크를 기존 NEOS 에이전트/오케스트레이터로 실행합니다.
태스크 유형에 따라 SearchOrchestrator 또는 직접 LLM 호출을 선택합니다.
"""

import logging
import time
from typing import Any, Dict, Optional

from neos.config.settings import settings
from neos.utils.llm_factory import LLMFactory

from .models import RecursiveTaskNode, TaskStatus

logger = logging.getLogger(__name__)

_DIRECT_ANSWER_PROMPT = """You are a research assistant. Answer the following specific sub-task concisely and accurately.

Task: {description}
Original research query: {original_query}
Context from prior sub-tasks: {prior_context}

Provide a focused, factual answer. If you need to search for real-time information but cannot, say so clearly.
Answer:"""


class RecursiveExecutor:
    """atomic 태스크 실행기.

    태스크 유형에 따라 실행 방식을 선택합니다:
    1. SearchOrchestrator 활용 (검색이 필요한 태스크)
    2. 직접 LLM 호출 (지식 기반 태스크)

    기존 SearchOrchestrator를 직접 호출하면 full AgentState를 요구하므로,
    초기 구현에서는 LLM을 직접 호출하고 검색 결과는 orchestrator 레벨에서 활용합니다.
    """

    def __init__(self, search_orchestrator=None, agents: Optional[Dict[str, Any]] = None):
        self._search_orchestrator = search_orchestrator
        self._agents = agents or {}
        self._model = settings.RECURSIVE_ATOMIZER_MODEL  # Haiku 사용 (비용 절감)

    async def execute(
        self,
        task: RecursiveTaskNode,
        context: Dict[str, Any],
    ) -> str:
        """atomic 태스크 실행.

        Args:
            task: 실행할 atomic 태스크 노드
            context: 실행 컨텍스트 (original_query, prior_results 등)

        Returns:
            실행 결과 문자열
        """
        task.status = TaskStatus.IN_PROGRESS
        start = time.time()

        try:
            result = await self._execute_with_llm(task, context)
            task.status = TaskStatus.COMPLETED
            task.result = result
            task.execution_time_ms = int((time.time() - start) * 1000)
            logger.info(
                f"[Executor] Completed depth={task.depth}: {task.description[:50]} "
                f"({task.execution_time_ms}ms)"
            )
            return result

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.metadata["error"] = str(e)
            logger.error(f"[Executor] Failed: {task.description[:50]} | {e}")
            return f"[실행 실패: {task.description[:40]}] 정보를 가져올 수 없습니다."

    async def _execute_with_llm(
        self,
        task: RecursiveTaskNode,
        context: Dict[str, Any],
    ) -> str:
        """LLM을 직접 호출하여 태스크 실행.

        search_results가 context에 있으면 해당 정보를 활용합니다.
        """
        original_query = context.get("original_query", "")
        prior_results = context.get("prior_results", {})

        # 완료된 형제 태스크 결과를 컨텍스트로 제공
        prior_context = self._build_prior_context(prior_results)

        # search_results가 있으면 활용
        search_context = context.get("search_synthesis", "")
        if search_context:
            prior_context = f"Search results: {search_context[:500]}\n\n" + prior_context

        prompt = _DIRECT_ANSWER_PROMPT.format(
            description=task.description,
            original_query=original_query,
            prior_context=prior_context if prior_context else "None available.",
        )

        provider = "anthropic" if "claude" in self._model.lower() else settings.LLM_PROVIDER
        llm = LLMFactory.create_llm(
            provider=provider,
            model=self._model,
            temperature=0.1,
            max_tokens=2000,
        )

        response = await llm.ainvoke(prompt)
        result = response.content if hasattr(response, "content") else str(response)
        return result.strip()

    def _build_prior_context(self, prior_results: Dict[str, str]) -> str:
        """완료된 하위 태스크 결과를 컨텍스트 문자열로 조합."""
        if not prior_results:
            return ""
        parts = []
        for task_id, result in prior_results.items():
            if result:
                parts.append(f"- {result[:300]}")
        return "\n".join(parts[:3])  # 최대 3개 이전 결과만 포함

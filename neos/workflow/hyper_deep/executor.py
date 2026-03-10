"""
HyperDeepExecutor: ROMA leaf 노드 실행자 (HyperDeepResearchAgent 래퍼)

RecursiveOrchestrator의 atomic 태스크 실행 시 LLM 직접 호출 대신
HyperDeepResearchAgent.execute()를 호출합니다.

설계 원칙:
- 싱글톤 재사용: _get_agent()로 최초 1회만 생성, 이후 재사용
- 상태 격리: execute() 진입 시 agent 내부 상태 리셋
- Graceful degradation: Tavily API 불가 시 명시적 메시지 반환
"""

import logging
import time
from typing import Any, Dict, Optional

from neos.workflow.recursive.models import RecursiveTaskNode, TaskStatus

logger = logging.getLogger(__name__)


def _extract_content(output: Dict[str, Any]) -> str:
    """HyperDeepResearchAgent.execute() 반환값에서 본문 텍스트 추출.

    format_output() 반환 형식:
        {
            "agent": str,
            "result": List[SearchResult],
            "results": List[SearchResult],
            "metadata": dict,
            "success": bool,
        }
    SearchResult.content에 리포트 마크다운이 담겨 있습니다.
    """
    if not output or not output.get("success"):
        return ""

    results = output.get("results", [])
    if not results:
        return ""

    first = results[0]
    # SearchResult dataclass 또는 dict 모두 지원
    if hasattr(first, "content"):
        return first.content or ""
    if isinstance(first, dict):
        return first.get("content", "")
    return str(first)


class HyperDeepExecutor:
    """ROMA leaf 노드 실행자 — HyperDeepResearchAgent를 호출합니다.

    RecursiveOrchestrator의 atomic 태스크에 대해
    LLM 직접 호출 대신 전체 HyperDeepResearch 파이프라인을 실행합니다.

    사용 예:
        executor = HyperDeepExecutor()
        orchestrator = RecursiveOrchestrator(executor=executor, max_depth=1, ...)
    """

    def __init__(self):
        # Lazy init: HyperDeepResearchAgent.__init__이 무거우므로 첫 실행 시 생성
        self._agent = None

    def _get_agent(self):
        """싱글톤 에이전트 인스턴스 반환."""
        if self._agent is None:
            from neos.agents.search_agents.hyper_deep_research.agent import HyperDeepResearchAgent
            self._agent = HyperDeepResearchAgent()
            logger.info("[HyperDeepExecutor] HyperDeepResearchAgent initialized")
        return self._agent

    def _reset_agent_state(self, agent) -> None:
        """각 subtask 실행 전 agent 내부 상태 초기화.

        싱글톤 재사용 시 이전 실행의 상태가 남아있지 않도록
        리포트·소스·메타데이터 컨테이너를 초기화합니다.
        """
        agent.current_report_id = None
        agent.sections_data = []
        agent.all_collected_sources = []
        agent.research_metadata = {
            "total_queries_executed": 0,
            "total_sources_collected": 0,
            "unique_domains": set(),
            "analysis_iterations_completed": 0,
            "critical_reviews_completed": 0,
            "multi_query_searches": 0,
            "criticism_feedbacks_generated": 0,
            "additional_research_triggered": 0,
            "api_rate_limit_hits": 0,
            "llm_calls": 0,
            "estimated_total_tokens": 0,
            "llm_calls_by_phase": {},
            "selected_skills": [],
            "selected_tools": [],
            "selection_reasoning": "",
        }

    async def execute(
        self,
        task: RecursiveTaskNode,
        context: Dict[str, Any],
    ) -> str:
        """atomic subtask를 HyperDeepResearchAgent로 실행.

        Args:
            task: ROMA에서 ATOMIC으로 판별된 태스크 노드
            context: 실행 컨텍스트 (session_id, user_id 등 포함)

        Returns:
            HyperDeepResearch 리포트 본문 (마크다운 문자열)
        """
        task.status = TaskStatus.IN_PROGRESS
        start = time.time()

        logger.info(
            f"[HyperDeepExecutor] Executing depth={task.depth}: {task.description[:60]}"
        )

        try:
            agent = self._get_agent()
            self._reset_agent_state(agent)

            # _stream_callback을 agent에 전달하여 Phase 이벤트가 SSE로 브릿지되도록 함
            agent_context = {
                "session_id": context.get("session_id", ""),
                "user_id": context.get("user_id", ""),
                "_stream_callback": context.get("_stream_callback"),
            }
            output = await agent.execute(
                query=task.description,
                context=agent_context,
            )

            content = _extract_content(output)

            if not content:
                # Tavily API 불가 또는 빈 결과 처리
                logger.warning(
                    f"[HyperDeepExecutor] Empty result for: {task.description[:50]}"
                )
                content = (
                    f"[HyperDeep 실패: '{task.description[:40]}' 연구 결과를 가져올 수 없습니다. "
                    f"Tavily API 가용 여부를 확인하세요.]"
                )

            task.status = TaskStatus.COMPLETED
            task.result = content
            task.execution_time_ms = int((time.time() - start) * 1000)

            logger.info(
                f"[HyperDeepExecutor] Completed depth={task.depth} "
                f"({task.execution_time_ms}ms, {len(content)} chars)"
            )
            return content

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.metadata["error"] = str(e)
            elapsed_ms = int((time.time() - start) * 1000)
            logger.error(
                f"[HyperDeepExecutor] Failed depth={task.depth}: "
                f"{task.description[:50]} | {e}"
            )
            return (
                f"[HyperDeep 실행 오류: {task.description[:40]}] "
                f"오류 내용: {str(e)[:100]}"
            )

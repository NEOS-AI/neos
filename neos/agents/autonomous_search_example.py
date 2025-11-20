"""
자율 검색 에이전트 예시

기존 KnowledgeSearchAgent를 자율 에이전트로 마이그레이션하는 예시.
다른 에이전트들도 동일한 패턴으로 변환 가능.
"""

from typing import Dict, Any, List
from langchain_openai import ChatOpenAI

from neos.agents.autonomous_base import AutonomousAgent
from neos.workflow.distributed import AgentCapability
from neos.config.settings import settings


class AutonomousKnowledgeSearchAgent(AutonomousAgent):
    """
    자율 지식 검색 에이전트

    기존 KnowledgeSearchAgent를 AutonomousAgent로 확장.
    작업을 자동으로 발견하고, 다른 에이전트와 협력하며, 자율적으로 실행.
    """

    def __init__(self):
        # LLM 초기화
        llm = ChatOpenAI(
            model=settings.AGENT_MODEL,
            temperature=0.7
        )

        # 부모 클래스 초기화
        super().__init__(
            name="AutonomousKnowledgeSearch",
            llm=llm,
            role="Knowledge Search Specialist",
            goal="Search and retrieve relevant knowledge from various sources",
            backstory=(
                "You are an expert knowledge search agent skilled at finding "
                "relevant information from databases, documents, and knowledge bases."
            ),
            capabilities=[
                AgentCapability.KNOWLEDGE_SEARCH,
                AgentCapability.WEB_SEARCH  # 추가 능력
            ]
        )

    async def execute_autonomous_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        자율 작업 실행 (오버라이드)

        Args:
            task_data: 작업 데이터

        Returns:
            실행 결과
        """
        payload = task_data.get("payload", {})
        query = payload.get("query", "")
        context = payload.get("context", {})

        # 기존 execute 메서드 호출
        result = await self.execute(query, context)

        # 결과가 불충분하면 다른 에이전트에게 협력 요청
        if result.get("success") and len(result.get("result", [])) < 3:
            # 웹 검색 에이전트에게 추가 도움 요청
            collaboration_response = await self.request_collaboration(
                capability=AgentCapability.WEB_SEARCH,
                request_data={
                    "query": query,
                    "context": context,
                    "reason": "insufficient_knowledge_results"
                },
                timeout=30.0
            )

            if collaboration_response:
                # 협력 결과 통합
                additional_results = collaboration_response.get("results", [])
                result["result"].extend(additional_results)
                result["collaboration"] = True

        return result

    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        기존 execute 메서드 (하위 호환성)

        Args:
            query: 검색 쿼리
            context: 컨텍스트

        Returns:
            검색 결과
        """
        # 실제 검색 로직 (기존 KnowledgeSearchAgent와 동일)
        # 여기서는 간소화된 예시

        # 상태 업데이트
        await self.state_manager.update_agent_state(
            self.agent_id,
            {"progress": 0.5, "current_task": f"Searching for: {query}"},
            broadcast=True
        )

        # 검색 수행 (여기서는 모의 결과)
        results = await self._perform_search(query, context)

        # 상태 업데이트
        await self.state_manager.update_agent_state(
            self.agent_id,
            {"progress": 1.0},
            broadcast=True
        )

        return {
            "success": True,
            "result": results,
            "agent": self.name,
            "metadata": {
                "query": query,
                "result_count": len(results)
            }
        }

    async def _perform_search(self, query: str, context: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        실제 검색 수행

        Args:
            query: 검색 쿼리
            context: 컨텍스트

        Returns:
            검색 결과 리스트
        """
        # 실제 구현에서는 벡터 DB, 검색 엔진 등을 사용
        # 여기서는 예시를 위한 모의 결과

        return [
            {
                "title": f"Knowledge result 1 for: {query}",
                "content": "Sample content from knowledge base",
                "score": 0.95,
                "source": "knowledge_base"
            },
            {
                "title": f"Knowledge result 2 for: {query}",
                "content": "Another relevant piece of information",
                "score": 0.87,
                "source": "knowledge_base"
            }
        ]

    async def handle_collaboration_request(
        self,
        request_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        협력 요청 처리 (오버라이드)

        Args:
            request_data: 요청 데이터

        Returns:
            응답 데이터
        """
        query = request_data.get("query", "")
        context = request_data.get("context", {})

        # 간단한 검색 수행
        results = await self._perform_search(query, context)

        return {
            "agent_id": self.agent_id,
            "can_help": True,
            "results": results,
            "message": f"{self.name} provided {len(results)} knowledge results"
        }


# 마이그레이션 가이드:
#
# 1. 기존 에이전트 클래스를 AutonomousAgent로 확장
# 2. capabilities 정의
# 3. execute_autonomous_task() 메서드 구현
# 4. 필요시 handle_collaboration_request() 오버라이드
# 5. 기존 execute() 메서드는 하위 호환성을 위해 유지
#
# 사용 예시:
# ```python
# from neos.workflow.distributed_graph import distributed_workflow
#
# # 자율 에이전트 생성
# agent = AutonomousKnowledgeSearchAgent()
#
# # 워크플로우에 등록
# await distributed_workflow.initialize()
# await distributed_workflow.register_autonomous_agent(agent)
#
# # 이제 에이전트는 자동으로 작업을 발견하고 실행함
# ```

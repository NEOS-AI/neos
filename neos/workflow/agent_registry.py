"""워크플로우에서 사용할 에이전트 레지스트리"""

from typing import Dict, Any, List, Optional, Type
from dataclasses import dataclass
import logging

from neos.agents.base import BaseAgent
from neos.agents.search_agents import (
    KnowledgeSearchAgent,
    RealtimeInfoSearchAgent,
    RealtimeDataSearchAgent,
    MultiQuerySearchAgent,
    DeepResearchAgent,
    HyperDeepResearchAgent
)
from neos.agents.analysis_agents import (
    DataAnalysisAgent,
    ComparativeAnalysisAgent,
    WebLookupAgent
)
from neos.agents.generation_agents import (
    ImageGenerationAgent,
    ApiCallAgent,
    FileProcessingAgent,
    TaskCreationAgent
)


logger = logging.getLogger(__name__)


@dataclass
class AgentInfo:
    """에이전트 정보"""
    name: str
    agent_class: Type[BaseAgent]
    category: str
    description: str
    capabilities: List[str]


class AgentRegistry:
    """에이전트 레지스트리 - 사용 가능한 모든 에이전트 관리"""

    def __init__(self):
        self._agents: Dict[str, AgentInfo] = {}
        self._instances: Dict[str, BaseAgent] = {}
        self._register_default_agents()

    def _register_default_agents(self):
        """기본 에이전트들 등록"""

        # 검색 에이전트들
        search_agents = [
            AgentInfo(
                name="knowledge_search",
                agent_class=KnowledgeSearchAgent,
                category="search",
                description="벡터 데이터베이스 기반 지식 검색",
                capabilities=["vector_search", "semantic_search", "knowledge_retrieval"]
            ),
            AgentInfo(
                name="realtime_info_search",
                agent_class=RealtimeInfoSearchAgent,
                category="search",
                description="실시간 정보 검색 (Tavily API)",
                capabilities=["real_time_search", "web_search", "current_events"]
            ),
            AgentInfo(
                name="realtime_data_search",
                agent_class=RealtimeDataSearchAgent,
                category="search",
                description="실시간 데이터 검색 (통계, 수치 데이터)",
                capabilities=["data_search", "statistics", "numerical_data"]
            ),
            AgentInfo(
                name="multi_query_search",
                agent_class=MultiQuerySearchAgent,
                category="search",
                description="다중 쿼리 검색 (여러 각도에서 검색)",
                capabilities=["multi_query", "diverse_search", "comprehensive_search"]
            ),
            AgentInfo(
                name="deep_research",
                agent_class=DeepResearchAgent,
                category="search",
                description="심층 조사 (15-25분 소요)",
                capabilities=["deep_research", "comprehensive_analysis", "gap_analysis"]
            ),
            AgentInfo(
                name="hyper_deep_research",
                agent_class=HyperDeepResearchAgent,
                category="search",
                description="초심층 조사 (30-60분 소요)",
                capabilities=["hyper_deep_research", "exhaustive_analysis", "critical_thinking"]
            ),
        ]

        # 분석 에이전트들
        analysis_agents = [
            AgentInfo(
                name="data_analysis",
                agent_class=DataAnalysisAgent,
                category="analysis",
                description="데이터 분석 및 인사이트 도출",
                capabilities=["data_analysis", "insight_generation", "pattern_recognition"]
            ),
            AgentInfo(
                name="comparative_analysis",
                agent_class=ComparativeAnalysisAgent,
                category="analysis",
                description="비교 분석 (여러 항목 비교)",
                capabilities=["comparative_analysis", "comparison", "evaluation"]
            ),
            AgentInfo(
                name="web_lookup",
                agent_class=WebLookupAgent,
                category="analysis",
                description="웹 정보 조회 및 검증",
                capabilities=["web_lookup", "fact_checking", "verification"]
            ),
        ]

        # 생성 에이전트들
        generation_agents = [
            AgentInfo(
                name="image_generation",
                agent_class=ImageGenerationAgent,
                category="generation",
                description="이미지 생성 (DALL-E 등)",
                capabilities=["image_generation", "visual_creation"]
            ),
            AgentInfo(
                name="api_call",
                agent_class=ApiCallAgent,
                category="generation",
                description="외부 API 호출",
                capabilities=["api_call", "external_integration"]
            ),
            AgentInfo(
                name="file_processing",
                agent_class=FileProcessingAgent,
                category="generation",
                description="파일 처리 및 변환",
                capabilities=["file_processing", "file_conversion"]
            ),
            AgentInfo(
                name="task_creation",
                agent_class=TaskCreationAgent,
                category="generation",
                description="작업 생성 및 분해",
                capabilities=["task_creation", "task_breakdown"]
            ),
        ]

        # 모든 에이전트 등록
        all_agents = search_agents + analysis_agents + generation_agents
        for agent_info in all_agents:
            self._agents[agent_info.name] = agent_info
            logger.info(f"Registered agent: {agent_info.name} ({agent_info.category})")

        logger.info(f"Total {len(self._agents)} agents registered")

    def get_agent(self, agent_name: str) -> Optional[BaseAgent]:
        """에이전트 인스턴스 가져오기 (싱글톤)"""
        if agent_name not in self._agents:
            logger.error(f"Agent '{agent_name}' not found in registry")
            return None

        # 이미 인스턴스가 있으면 재사용
        if agent_name in self._instances:
            return self._instances[agent_name]

        # 새 인스턴스 생성
        agent_info = self._agents[agent_name]
        try:
            instance = agent_info.agent_class()
            self._instances[agent_name] = instance
            logger.info(f"Created agent instance: {agent_name}")
            return instance
        except Exception as e:
            logger.error(f"Failed to create agent instance '{agent_name}': {e}")
            return None

    def get_agent_info(self, agent_name: str) -> Optional[AgentInfo]:
        """에이전트 정보 가져오기"""
        return self._agents.get(agent_name)

    def list_agents(
        self,
        category: Optional[str] = None
    ) -> List[AgentInfo]:
        """에이전트 목록 조회"""
        agents = list(self._agents.values())

        if category:
            agents = [a for a in agents if a.category == category]

        return agents

    def get_categories(self) -> List[str]:
        """사용 가능한 카테고리 목록"""
        categories = set(agent.category for agent in self._agents.values())
        return sorted(categories)

    def agent_exists(self, agent_name: str) -> bool:
        """에이전트 존재 여부 확인"""
        return agent_name in self._agents

    def get_agents_by_capability(self, capability: str) -> List[AgentInfo]:
        """특정 capability를 가진 에이전트 목록"""
        return [
            agent for agent in self._agents.values()
            if capability in agent.capabilities
        ]


# 전역 에이전트 레지스트리
agent_registry = AgentRegistry()

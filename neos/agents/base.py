from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio
import logging
from crewai import Agent, Task, Crew
# from langchain_openai import ChatOpenAI
from langchain_core.language_models.base import BaseLanguageModel

from neos.config.settings import settings

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """기본 에이전트 클래스"""

    def __init__(
        self,
        name: str,
        llm: BaseLanguageModel,
        role: str | None = None,
        goal: str | None = None,
        backstory: str | None = None
    ):
        self.name = name
        self.role = role or name
        self.goal = goal or f"Perform tasks as the {name} agent."
        self.backstory = backstory or f"You are {name}, an AI agent designed to assist with various tasks."
        self.llm = llm
        self.agent = self._create_agent()


    def _create_agent(self) -> Agent:
        """CrewAI 에이전트 생성"""
        return Agent(
            role=self.role,
            goal=self.goal,
            backstory=self.backstory,
            llm=self.llm,
            verbose=settings.DEBUG,
            allow_delegation=False,
            max_execution_time=settings.AGENT_TIMEOUT
        )

    @abstractmethod
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """에이전트 실행 (하위 클래스에서 구현)"""
        pass
    
    async def create_task(self, description: str, context: Dict[str, Any] = None) -> Task:
        """태스크 생성"""
        task_context = f"""
        Query: {context.get('query', '')}
        User ID: {context.get('user_id', '')}
        Session ID: {context.get('session_id', '')}
        Additional Context: {context.get('additional_context', {})}
        """
        
        return Task(
            description=f"{description}\n\nContext:\n{task_context}",
            agent=self.agent,
            expected_output="Structured result with analysis and insights"
        )
    
    async def run_crew(self, tasks: List[Task]) -> Dict[str, Any]:
        """
        Crew 실행 (비동기 래퍼)

        CrewAI의 kickoff()는 동기 함수이므로 asyncio.to_thread()를 사용하여
        별도 스레드에서 실행하여 이벤트 루프를 블로킹하지 않습니다.
        """
        try:
            start_time = datetime.now()

            crew = Crew(
                agents=[self.agent],
                tasks=tasks,
                verbose=settings.DEBUG,
                process="sequential"
            )

            # 동기 crew.kickoff()를 별도 스레드에서 실행
            logger.debug(f"{self.name} - Crew 실행 시작")
            result = await asyncio.to_thread(crew.kickoff)
            logger.debug(f"{self.name} - Crew 실행 완료")

            execution_time = (datetime.now() - start_time).total_seconds()

            return {
                "success": True,
                "result": result,
                "agent": self.name,
                "execution_time": execution_time
            }

        except Exception as e:
            logger.error(f"{self.name} - Crew 실행 에러: {e}")
            return {
                "success": False,
                "error": str(e),
                "agent": self.name
            }

    def validate_input(self, query: str, context: Dict[str, Any] = None) -> bool:
        """입력 검증"""
        if not query or not query.strip():
            return False
        
        if len(query) > 10000:  # 최대 쿼리 길이 제한
            return False
            
        return True

    def format_output(self, result: Any, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """출력 형식 표준화"""
        return {
            "agent": self.name,
            "result": result,  # 하위 호환성
            "results": result if isinstance(result, list) else [result],  # CLI 호환성
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat(),
            "success": True
        }


class SearchAgent(BaseAgent):
    """검색 에이전트 기본 클래스"""
    
    def __init__(
        self, 
        name: str, 
        search_type: str, 
        llm: Optional[BaseLanguageModel] = None,
        **kwargs
    ):
        self.search_type = search_type
        super().__init__(name=name, llm=llm, **kwargs)

    async def search(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        """검색 실행 (하위 클래스에서 구현)"""
        raise NotImplementedError("Subclasses must implement the search method.")

class AnalysisAgent(BaseAgent):
    """분석 에이전트 기본 클래스"""
    
    def __init__(
        self, 
        name: str, 
        analysis_type: str, 
        llm: Optional[BaseLanguageModel] = None,
        **kwargs
    ):
        self.analysis_type = analysis_type
        super().__init__(name=name, llm=llm, **kwargs)
    
    async def analyze(self, data: Any, **kwargs) -> Dict[str, Any]:
        """데이터 분석 (하위 클래스에서 구현)"""
        raise NotImplementedError("Subclasses must implement the analyze method.")


class GenerationAgent(BaseAgent):
    """생성 에이전트 기본 클래스"""

    def __init__(
        self, 
        name: str, 
        generation_type: str, 
        llm: Optional[BaseLanguageModel] = None,
        **kwargs
    ):
        self.generation_type = generation_type
        super().__init__(name=name, llm=llm, **kwargs)

    async def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """콘텐츠 생성 (하위 클래스에서 구현)"""
        raise NotImplementedError("Subclasses must implement the generate method.")

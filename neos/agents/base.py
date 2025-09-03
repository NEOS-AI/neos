from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime
from crewai import Agent, Task, Crew
# from langchain_openai import ChatOpenAI
from langchain_core.language_models.base import BaseLanguageModel

from neos.config.settings import settings


class BaseAgent(ABC):
    """기본 에이전트 클래스"""

    def __init__(self, name: str, llm: BaseLanguageModel, role: str, goal: str, backstory: str):
        self.name = name
        self.role = role
        self.goal = goal
        self.backstory = backstory
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
        """Crew 실행"""
        try:
            crew = Crew(
                agents=[self.agent],
                tasks=tasks,
                verbose=settings.DEBUG,
                process="sequential"
            )
            
            result = crew.kickoff()
            
            return {
                "success": True,
                "result": result,
                "agent": self.name,
                "execution_time": None
            }
            
        except Exception as e:
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
            "result": result,
            "metadata": metadata or {},
            "timestamp": datetime.utcnow().isoformat(),
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
        pass

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
        pass


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
        pass

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime
import logging
# from langchain_openai import ChatOpenAI
from langchain_core.language_models.base import BaseLanguageModel

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

    @abstractmethod
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """에이전트 실행 (하위 클래스에서 구현)"""
        pass
    
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

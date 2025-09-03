from typing import Dict, Any, List
from tavily import TavilyClient
from sqlalchemy import text

from neos.config.settings import settings
from neos.workflow.state import SearchResult
from neos.utils.cache import cache_manager
from neos.database.connection import db_manager

from .base import SearchAgent


class KnowledgeSearchAgent(SearchAgent):
    """지식 기반 검색 에이전트"""
    
    def __init__(self):
        super().__init__(
            name="knowledge_search",
            search_type="knowledge",
            role="Knowledge Base Searcher",
            goal="Search through internal knowledge base and historical queries to find relevant information",
            backstory="You are an expert at searching through structured knowledge bases and finding patterns in historical data."
        )
    
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}
        
        # 캐시 확인
        cache_key = f"knowledge_search:{hash(query)}"
        cached_result = await cache_manager.get(cache_key)
        if cached_result:
            return cached_result
        
        try:
            # 벡터 유사도 검색
            similar_queries = await self._search_similar_queries(query, context.get('query_embedding'))
            
            # 지식 베이스 검색 (여기서는 과거 쿼리 결과 활용)
            knowledge_results = await self._search_knowledge_base(query)
            
            results = []
            for item in similar_queries + knowledge_results:
                results.append(SearchResult(
                    source="knowledge_base",
                    title=item.get("title", "Knowledge Item"),
                    content=item.get("content", ""),
                    score=item.get("score", 0.0),
                    metadata=item.get("metadata", {})
                ))
            
            result = self.format_output(results, {"search_type": "knowledge"})
            
            # 결과 캐싱
            await cache_manager.set(cache_key, result, ttl=3600)
            return result
            
        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    async def _search_similar_queries(self, query: str, query_embedding: List[float]) -> List[Dict[str, Any]]:
        """유사한 쿼리 검색"""
        if not query_embedding:
            return []
        
        async with db_manager.get_session() as session:
            # 벡터 유사도 검색
            sql = text("""
                SELECT original_query, search_results, response_quality_score,
                       query_vector <=> :query_vector as distance
                FROM query_history
                WHERE query_vector IS NOT NULL
                ORDER BY query_vector <=> :query_vector
                LIMIT 5
            """)
            
            result = await session.execute(sql, {"query_vector": str(query_embedding)})
            rows = result.fetchall()
            
            similar_queries = []
            for row in rows:
                if row.distance < 0.3:  # 유사도 임계값
                    similar_queries.append({
                        "title": row.original_query,
                        "content": str(row.search_results) if row.search_results else "",
                        "score": 1 - row.distance,
                        "metadata": {"quality_score": row.response_quality_score}
                    })
            
            return similar_queries
    
    async def _search_knowledge_base(self, query: str) -> List[Dict[str, Any]]:
        """지식 베이스 검색 (트리그램 기반)"""
        async with db_manager.get_session() as session:
            sql = text("""
                SELECT original_query, search_results, response_quality_score,
                       similarity(original_query, :query) as sim_score
                FROM query_history
                WHERE similarity(original_query, :query) > 0.3
                ORDER BY similarity(original_query, :query) DESC
                LIMIT 3
            """)
            
            result = await session.execute(sql, {"query": query})
            rows = result.fetchall()
            
            knowledge_results = []
            for row in rows:
                knowledge_results.append({
                    "title": row.original_query,
                    "content": str(row.search_results) if row.search_results else "",
                    "score": row.sim_score,
                    "metadata": {"quality_score": row.response_quality_score}
                })
            
            return knowledge_results

class RealtimeInfoSearchAgent(SearchAgent):
    """실시간 정보 검색 에이전트"""
    
    def __init__(self):
        super().__init__(
            name="realtime_info_search",
            search_type="realtime",
            role="Real-time Information Searcher",
            goal="Search for the most current and up-to-date information from web sources",
            backstory="You specialize in finding the latest news, trends, and real-time information from various web sources."
        )
        self.tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}
        
        try:
            # Tavily 검색 실행
            search_results = await self._tavily_search(query)
            
            results = []
            for item in search_results:
                results.append(SearchResult(
                    source="web",
                    title=item.get("title", ""),
                    content=item.get("content", ""),
                    url=item.get("url", ""),
                    score=item.get("score", 0.0),
                    metadata={
                        "published_date": item.get("published_date"),
                        "domain": item.get("domain")
                    }
                ))
            
            return self.format_output(results, {"search_type": "realtime"})
            
        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    async def _tavily_search(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Tavily 웹 검색"""
        try:
            response = self.tavily_client.search(
                query=query,
                search_depth="advanced",
                max_results=max_results,
                include_domains=[],
                exclude_domains=["reddit.com", "quora.com"],  # 특정 도메인 제외
                include_answer=True,
                include_raw_content=True
            )
            
            return response.get("results", [])
            
        except Exception as e:
            print(f"Tavily search error: {e}")
            return []

class RealtimeDataSearchAgent(SearchAgent):
    """실시간 데이터 검색 에이전트"""
    
    def __init__(self):
        super().__init__(
            name="realtime_data_search", 
            search_type="data",
            role="Real-time Data Searcher",
            goal="Search for real-time data, statistics, and numerical information",
            backstory="You are an expert at finding current data, statistics, market information, and quantitative insights."
        )
        self.tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input"}
        
        try:
            # 데이터 중심 검색
            data_results = await self._search_data_sources(query)
            
            results = []
            for item in data_results:
                results.append(SearchResult(
                    source="data_source",
                    title=item.get("title", ""),
                    content=item.get("content", ""),
                    url=item.get("url", ""),
                    score=item.get("score", 0.0),
                    metadata={
                        "data_type": item.get("data_type", "general"),
                        "last_updated": item.get("last_updated"),
                        "source_reliability": item.get("source_reliability", 0.5)
                    }
                ))
            
            return self.format_output(results, {"search_type": "data"})
            
        except Exception as e:
            return {"success": False, "error": str(e), "agent": self.name}
    
    async def _search_data_sources(self, query: str) -> List[Dict[str, Any]]:
        """데이터 소스 검색"""
        try:
            # 데이터 관련 키워드 추가
            data_query = f"{query} statistics data trends numbers"
            
            response = self.tavily_client.search(
                query=data_query,
                search_depth="advanced",
                max_results=5,
                include_domains=[
                    "statista.com",
                    "data.gov",
                    "worldbank.org", 
                    "nasdaq.com",
                    "yahoo.com"
                ],
                include_answer=True,
                include_raw_content=True
            )
            
            results = response.get("results", [])
            
            # 데이터 관련성 점수 조정
            for result in results:
                content = result.get("content", "").lower()
                data_keywords = ["data", "statistics", "percent", "%", "number", "trend", "chart", "graph"]
                score_boost = sum(1 for keyword in data_keywords if keyword in content) * 0.1
                result["score"] = min(1.0, result.get("score", 0.5) + score_boost)
                result["data_type"] = self._classify_data_type(content)
            
            return results
            
        except Exception as e:
            print(f"Data search error: {e}")
            return []


    def _classify_data_type(self, content: str) -> str:
        """데이터 유형 분류"""
        content_lower = content.lower()
        
        if any(word in content_lower for word in ["financial", "stock", "price", "market"]):
            return "financial"
        elif any(word in content_lower for word in ["demographic", "population", "census"]):
            return "demographic"
        elif any(word in content_lower for word in ["economic", "gdp", "inflation", "unemployment"]):
            return "economic"
        elif any(word in content_lower for word in ["technology", "digital", "internet", "software"]):
            return "technology"
        else:
            return "general"

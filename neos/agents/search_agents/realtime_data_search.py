"""Real-time data search agent"""

from typing import Dict, Any, List
import asyncio
import concurrent.futures
import time
from tavily import TavilyClient

from neos.config.settings import settings
from neos.database.web_search_logger import get_search_logger
from neos.database.web_search_types import SearchLogRequest, SearchLogComplete, SearchResultItem, SearchQueryStatus
from neos.workflow.state import SearchResult

from ..base import SearchAgent


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
        # Check if Tavily API key is available and try to create client
        self.tavily_client = None
        self.api_available = False

        print(f"[DEBUG] RealtimeDataSearchAgent checking TAVILY_API_KEY: {'SET' if settings.TAVILY_API_KEY else 'NOT SET'}")
        if settings.TAVILY_API_KEY and settings.TAVILY_API_KEY.strip():
            try:
                print("[DEBUG] Creating TavilyClient for data search...")
                self.tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
                self.api_available = True
                print("[DEBUG] TavilyClient created successfully for data search")
            except Exception as e:
                print(f"[WARNING] Failed to create TavilyClient for data search: {e}")
                import traceback
                print(f"[WARNING] TavilyClient creation traceback: {traceback.format_exc()}")
                self.tavily_client = None
                self.api_available = False
        else:
            print("[WARNING] TAVILY_API_KEY not set, RealtimeDataSearchAgent will return empty results")

    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        print(f"[DEBUG] RealtimeDataSearchAgent.execute called with query: {query[:50]}...")

        if not self.validate_input(query, context):
            print("[ERROR] RealtimeDataSearchAgent: Invalid input")
            return {"success": False, "error": "Invalid input"}

        # Check if API is available
        if not self.api_available:
            print("[WARNING] TAVILY_API_KEY not available, returning empty results")
            return self.format_output([], {"search_type": "data", "warning": "API key not available"})

        # 검색 로거 초기화
        search_logger = await get_search_logger()
        query_id = None
        start_time = time.time()

        try:
            # 검색 시작 로그
            log_request = SearchLogRequest(
                query_text=query,
                engine_name="tavily",
                user_id=context.get("user_id") if context else None,
                session_id=context.get("session_id") if context else None,
                query_language=context.get("detected_language") if context else None,
                query_intent=context.get("query_intent") if context else None,
                search_params={"search_type": "data", "search_depth": "advanced"},
                trace_id=context.get("trace_id") if context else None
            )
            query_id = await search_logger.log_search_start(log_request)
            print(f"[DEBUG] Search logging started with query_id={query_id}")

            print("[DEBUG] Starting data search...")
            # 데이터 중심 검색
            data_results = await self._search_data_sources(query)

            results = []
            log_results = []
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

                # 로깅용 결과 아이템
                log_results.append(SearchResultItem(
                    url=item.get("url", ""),
                    title=item.get("title"),
                    content=item.get("content"),
                    score=item.get("score"),
                    metadata={"data_type": item.get("data_type", "general")}
                ))

            # 검색 완료 로그
            execution_time_ms = int((time.time() - start_time) * 1000)
            log_complete = SearchLogComplete(
                query_id=query_id,
                results=log_results,
                execution_time_ms=execution_time_ms,
                status=SearchQueryStatus.COMPLETED,
                quality_score=self._calculate_quality_score(results)
            )
            await search_logger.log_search_complete(log_complete)
            print(f"[DEBUG] Search logging completed for query_id={query_id}")

            return self.format_output(results, {"search_type": "data"})

        except Exception as e:
            # 에러 로그
            if query_id:
                execution_time_ms = int((time.time() - start_time) * 1000)
                log_complete = SearchLogComplete(
                    query_id=query_id,
                    results=[],
                    execution_time_ms=execution_time_ms,
                    status=SearchQueryStatus.FAILED,
                    error_message=str(e)
                )
                await search_logger.log_search_complete(log_complete)

            return {"success": False, "error": str(e), "agent": self.name}

    def _calculate_quality_score(self, results: List) -> float:
        """결과 품질 점수 계산"""
        if not results:
            return 0.0

        # 평균 스코어 계산
        avg_score = sum(r.score for r in results if hasattr(r, 'score')) / len(results)
        # 결과 수에 따른 보정 (최대 10개 결과 기준)
        count_factor = min(len(results) / 10.0, 1.0)

        return min(avg_score * count_factor, 1.0)

    async def _search_data_sources(self, query: str) -> List[Dict[str, Any]]:
        """데이터 소스 검색"""
        try:
            print(f"[DEBUG] Making Tavily data search API call for query: {query[:50]}...")

            # Check API availability before making call
            if not self.api_available or not self.tavily_client:
                print("[WARNING] Tavily API not available for data search, returning empty results")
                return []

            # 데이터 관련 키워드 추가
            data_query = f"{query} statistics data trends numbers"

            # Create a thread pool executor with timeout
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                try:
                    print("[DEBUG] Submitting Tavily data search API call to thread pool...")
                    future = executor.submit(
                        self.tavily_client.search,
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

                    print("[DEBUG] Waiting for Tavily data search API response...")
                    # Use asyncio.create_task with proper timeout handling
                    def get_result_with_timeout():
                        try:
                            return future.result(timeout=20)  # 20 seconds for the actual call
                        except concurrent.futures.TimeoutError:
                            print("[WARNING] Tavily data search API call timed out at 20 seconds")
                            return None

                    response = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, get_result_with_timeout),
                        timeout=25  # 25 second total timeout
                    )

                    print("[DEBUG] Tavily data search API call completed successfully")
                    results = response.get("results", []) if response else []

                    # 데이터 관련성 점수 조정
                    for result in results:
                        # Handle both dict and SearchResult objects
                        if isinstance(result, dict):
                            content = result.get("content", "").lower()
                            data_keywords = ["data", "statistics", "percent", "%", "number", "trend", "chart", "graph"]
                            score_boost = sum(1 for keyword in data_keywords if keyword in content) * 0.1
                            result["score"] = min(1.0, result.get("score", 0.5) + score_boost)
                            result["data_type"] = self._classify_data_type(content)
                        # Note: SearchResult objects are immutable dataclasses, skip score adjustment

                    print(f"[DEBUG] Tavily data search API returned {len(results)} results")
                    return results

                except concurrent.futures.TimeoutError:
                    print("[ERROR] Tavily data search API call timed out in thread pool")
                    return []
                except Exception as e:
                    print(f"[ERROR] Error in data search thread pool execution: {e}")
                    return []

        except asyncio.TimeoutError:
            print("[ERROR] Tavily data search timed out after 30 seconds")
            return []
        except Exception as e:
            print(f"[ERROR] Data search error: {e}")
            import traceback
            print(f"[ERROR] Data search traceback: {traceback.format_exc()}")
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

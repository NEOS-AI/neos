from typing import Dict, Any, List
from tavily import TavilyClient
from sqlalchemy import text
from langchain.schema import HumanMessage

from neos.config.settings import settings
from neos.workflow.state import SearchResult
from neos.utils.cache import cache_manager
from neos.utils.llm_factory import create_llm
from neos.database.connection import db_manager
# from neos.database.models import QueryHistory

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
        print(f"[DEBUG] KnowledgeSearchAgent.execute called with query: {query[:50]}...")

        if not self.validate_input(query, context):
            print("[ERROR] KnowledgeSearchAgent: Invalid input")
            return {"success": False, "error": "Invalid input"}

        # 캐시 확인
        cache_key = f"knowledge_search:{hash(query)}"
        print(f"[DEBUG] Checking cache with key: {cache_key}")
        cached_result = await cache_manager.get(cache_key)
        if cached_result:
            print("[DEBUG] Found cached result, returning")
            return cached_result

        try:
            print("[DEBUG] Searching knowledge base...")
            similar_queries = await self._search_knowledge_base(query, context.get('query_embedding'))
            print(f"[DEBUG] Knowledge base returned {len(similar_queries)} items")

            results = []
            for item in similar_queries:
                results.append(SearchResult(
                    source="knowledge_base",
                    title=item.get("title", "Knowledge Item"),
                    content=item.get("content", ""),
                    score=item.get("score", 0.0),
                    metadata=item.get("metadata", {})
                ))

            print(f"[DEBUG] Created {len(results)} SearchResult objects")
            result = self.format_output(results, {"search_type": "knowledge"})

            # 결과 캐싱
            print("[DEBUG] Caching result...")
            await cache_manager.set(cache_key, result, ttl=3600)
            print("[DEBUG] KnowledgeSearchAgent execution completed successfully")
            return result
        except Exception as e:
            print(f"[ERROR] KnowledgeSearchAgent execution failed: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e), "agent": self.name}


    async def _search_knowledge_base(self, query: str, query_embedding: List[float]) -> List[Dict[str, Any]]:
        """지식 베이스 검색 (트리그램 기반)"""
        print(f"[DEBUG] _search_knowledge_base called with embedding: {type(query_embedding)}")

        # If no embedding provided, return empty results
        if not query_embedding:
            print("[WARNING] No query embedding provided, returning empty results")
            return []

        try:
            print("[DEBUG] Getting database session...")
            async with await db_manager.get_session() as session:
                print("[DEBUG] Database session acquired")
                #TODO pg_search 등 paradedb 기능 도입!
                sql = text("""
                    SELECT original_query, search_results, response_quality_score,
                           query_vector <=> :query_vector as distance
                    FROM query_history
                    WHERE query_vector IS NOT NULL
                    ORDER BY query_vector <=> :query_vector
                    LIMIT 5
                """)

                print(f"[DEBUG] Executing SQL query with embedding length: {len(query_embedding)}")
                result = await session.execute(sql, {"query_vector": str(query_embedding)})
                rows = result.fetchall()
                print(f"[DEBUG] SQL query returned {len(rows)} rows")

                knowledge_results = []
                for i, row in enumerate(rows):
                    print(f"[DEBUG] Processing row {i+1}: distance={row.distance}")
                    # Convert distance to similarity score (1 - distance, clamped between 0 and 1)
                    similarity_score = max(0.0, min(1.0, 1.0 - row.distance))
                    knowledge_results.append({
                        "title": row.original_query,
                        "content": str(row.search_results) if row.search_results else "",
                        "score": similarity_score,
                        "metadata": {"quality_score": row.response_quality_score}
                    })

                print(f"[DEBUG] Returning {len(knowledge_results)} knowledge results")
                return knowledge_results

        except Exception as e:
            print(f"[ERROR] Database search failed: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            return []


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
        # Check if Tavily API key is available and try to create client
        self.tavily_client = None
        self.api_available = False

        print(f"[DEBUG] Checking TAVILY_API_KEY: {'SET' if settings.TAVILY_API_KEY else 'NOT SET'}")
        if settings.TAVILY_API_KEY and settings.TAVILY_API_KEY.strip():
            try:
                print("[DEBUG] Creating TavilyClient...")
                self.tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
                self.api_available = True
                print("[DEBUG] TavilyClient created successfully")
            except Exception as e:
                print(f"[WARNING] Failed to create TavilyClient: {e}")
                import traceback
                print(f"[WARNING] TavilyClient creation traceback: {traceback.format_exc()}")
                self.tavily_client = None
                self.api_available = False
        else:
            print("[WARNING] TAVILY_API_KEY not set, RealtimeInfoSearchAgent will return empty results")
    
    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        print(f"[DEBUG] RealtimeInfoSearchAgent.execute called with query: {query[:50]}...")

        if not self.validate_input(query, context):
            print("[ERROR] RealtimeInfoSearchAgent: Invalid input")
            return {"success": False, "error": "Invalid input"}

        # Check if API is available
        if not self.api_available:
            print("[WARNING] TAVILY_API_KEY not available, returning empty results")
            return self.format_output([], {"search_type": "realtime", "warning": "API key not available"})

        try:
            print("[DEBUG] Starting Tavily search...")
            # Tavily 검색 실행
            search_results = await self._tavily_search(query)
            print(f"[DEBUG] Tavily search returned {len(search_results)} results")

            # Debug: Log detailed Tavily results for observability
            for i, item in enumerate(search_results):
                title = item.get("title", "")[:50]
                url = item.get("url", "")
                score = item.get("score", 0.0)
                domain = item.get("domain", "")
                print(f"[DEBUG] Tavily result {i+1}: score={score:.3f}, domain={domain}, title='{title}...', url={url}")

            # Process top N results with LLM to generate comprehensive response with citations
            print("[DEBUG] Processing Tavily results with LLM...")
            processed_results = await self._process_with_llm(query, search_results[:5])  # Top 5 results
            print(f"[DEBUG] LLM processing returned {len(processed_results)} results")

            print(f"[DEBUG] Created {len(processed_results)} SearchResult objects")
            result = self.format_output(processed_results, {"search_type": "realtime"})
            print("[DEBUG] RealtimeInfoSearchAgent execution completed successfully")
            return result

        except Exception as e:
            print(f"[ERROR] RealtimeInfoSearchAgent execution failed: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e), "agent": self.name}
    
    async def _tavily_search(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Tavily 웹 검색"""
        try:
            print(f"[DEBUG] Making Tavily API call for query: {query[:50]}...")

            # Check API availability before making call
            if not self.api_available or not self.tavily_client:
                print("[WARNING] Tavily API not available, returning empty results")
                return []

            # Use asyncio to run the synchronous Tavily client call in a thread pool with timeout
            import asyncio
            import concurrent.futures

            # Create a thread pool executor with timeout
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                try:
                    print("[DEBUG] Submitting Tavily API call to thread pool...")
                    future = executor.submit(
                        self.tavily_client.search,
                        query=query,
                        search_depth="advanced",
                        max_results=max_results,
                        include_domains=[],
                        exclude_domains=["reddit.com", "quora.com"],  # 특정 도메인 제외
                        include_answer=True,
                        include_raw_content=True
                    )

                    print("[DEBUG] Waiting for Tavily API response...")
                    # Use asyncio.create_task with proper timeout handling
                    def get_result_with_timeout():
                        try:
                            return future.result(timeout=20)  # 20 seconds for the actual call
                        except concurrent.futures.TimeoutError:
                            print("[WARNING] Tavily API call timed out at 20 seconds")
                            return None

                    response = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, get_result_with_timeout),
                        timeout=25  # 25 second total timeout
                    )

                    print("[DEBUG] Tavily API call completed successfully")
                    results = response.get("results", []) if response else []
                    print(f"[DEBUG] Tavily API returned {len(results)} results")
                    return results

                except concurrent.futures.TimeoutError:
                    print("[ERROR] Tavily API call timed out in thread pool")
                    return []
                except Exception as e:
                    print(f"[ERROR] Error in thread pool execution: {e}")
                    return []

        except asyncio.TimeoutError:
            print(f"[ERROR] Tavily search timed out after 30 seconds")
            return []
        except Exception as e:
            print(f"[ERROR] Tavily search error: {e}")
            import traceback
            print(f"[ERROR] Tavily search traceback: {traceback.format_exc()}")
            return []

    async def _process_with_llm(self, query: str, tavily_results: List[Dict[str, Any]]) -> List[SearchResult]:
        """LLM을 사용하여 Tavily 검색 결과를 처리하고 citation이 포함된 응답 생성"""
        try:
            if not tavily_results:
                print("[WARNING] No Tavily results to process with LLM")
                return []

            print(f"[DEBUG] Processing {len(tavily_results)} Tavily results with LLM...")

            # Create LLM instance with higher max_tokens for comprehensive responses
            llm = create_llm(temperature=0.1, max_tokens=4000)  # Low temperature for factual accuracy, higher token limit

            # Prepare search results context for LLM
            search_context = self._prepare_search_context(tavily_results)

            # Create prompt for LLM processing
            prompt = self._create_analysis_prompt(query, search_context)

            print("[DEBUG] Sending request to LLM for result processing...")
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            llm_response = response.content

            print(f"[DEBUG] LLM response length: {len(llm_response)} characters")

            # Create a single comprehensive SearchResult with LLM-processed content
            processed_result = SearchResult(
                source="llm_processed_web",
                title=f"AI 분석: {query}",
                content=llm_response,
                url="",  # No single URL since this is synthesized from multiple sources
                score=0.95,  # High score for LLM-processed content
                metadata={
                    "processing_type": "llm_synthesis",
                    "source_count": len(tavily_results),
                    "sources": [
                        {
                            "title": result.get("title", ""),
                            "url": result.get("url", ""),
                            "domain": result.get("domain", "")
                        }
                        for result in tavily_results
                    ]
                }
            )

            print("[DEBUG] LLM processing completed successfully")
            return [processed_result]

        except Exception as e:
            print(f"[ERROR] LLM processing failed: {e}")
            import traceback
            print(f"[ERROR] LLM processing traceback: {traceback.format_exc()}")

            # Fallback to original Tavily results if LLM processing fails
            print("[DEBUG] Falling back to original Tavily results")
            results = []
            for i, item in enumerate(tavily_results):
                result = SearchResult(
                    source="web",
                    title=item.get("title", ""),
                    content=item.get("content", ""),
                    url=item.get("url", ""),
                    score=item.get("score", 0.0),
                    metadata={
                        "published_date": item.get("published_date"),
                        "domain": item.get("domain"),
                        "fallback": True
                    }
                )
                results.append(result)
            return results

    def _prepare_search_context(self, tavily_results: List[Dict[str, Any]]) -> str:
        """Tavily 검색 결과를 LLM이 처리할 수 있는 형태로 준비"""
        context_parts = []

        for i, result in enumerate(tavily_results, 1):
            title = result.get("title", "제목 없음")
            content = result.get("content", "")
            url = result.get("url", "")
            domain = result.get("domain", "")

            # Limit content length to prevent context overflow
            if len(content) > 1000:
                content = content[:1000] + "..."

            context_parts.append(f"""
소스 {i}:
제목: {title}
출처: {domain} ({url})
내용: {content}
""")

        return "\n".join(context_parts)

    def _create_analysis_prompt(self, query: str, search_context: str) -> str:
        """LLM 분석을 위한 프롬프트 생성"""
        return f"""
사용자 질문: {query}

다음은 웹 검색을 통해 수집된 정보들입니다:

{search_context}

위 검색 결과들을 바탕으로 사용자의 질문에 대해 종합적이고 정확한 답변을 작성해주세요.

요구사항:
1. 각 정보의 출처를 명확히 인용하세요 (예: "출처: 도메인명")
2. 상충되는 정보가 있다면 이를 명시하고 설명하세요
3. 정확한 수치나 날짜가 있다면 그대로 인용하세요
4. 추측이나 확인되지 않은 정보는 추가하지 마세요
5. 한국어로 작성하되, 전문적이고 객관적인 톤을 유지하세요
6. **중요**: 답변을 완전히 작성하세요. 문장이나 문단 중간에 끊지 마세요.
7. 각 기업별로 상세한 분석을 제공하세요.

답변:"""

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

        try:
            print("[DEBUG] Starting data search...")
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
            print(f"[DEBUG] Making Tavily data search API call for query: {query[:50]}...")

            # Check API availability before making call
            if not self.api_available or not self.tavily_client:
                print("[WARNING] Tavily API not available for data search, returning empty results")
                return []

            # 데이터 관련 키워드 추가
            data_query = f"{query} statistics data trends numbers"

            import asyncio
            import concurrent.futures

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
                        content = result.get("content", "").lower()
                        data_keywords = ["data", "statistics", "percent", "%", "number", "trend", "chart", "graph"]
                        score_boost = sum(1 for keyword in data_keywords if keyword in content) * 0.1
                        result["score"] = min(1.0, result.get("score", 0.5) + score_boost)
                        result["data_type"] = self._classify_data_type(content)

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

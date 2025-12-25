"""Real-time information search agent"""

from typing import Dict, Any, List
import asyncio
import concurrent.futures
from tavily import TavilyClient
from langchain_core.messages import HumanMessage

from neos.config.settings import settings
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm
from neos.workflow.state import SearchResult

from ..base import SearchAgent


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
            # Extract session_id, user_id and detected_language from context
            session_id = context.get("session_id", "") if context else ""
            user_id = context.get("user_id", "") if context else ""
            detected_language = context.get("detected_language", "ko") if context else "ko"
            processed_results = await self._process_with_llm(query, search_results[:5], session_id=session_id, user_id=user_id, detected_language=detected_language)  # Top 5 results
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
            print("[ERROR] Tavily search timed out after 30 seconds")
            return []
        except Exception as e:
            print(f"[ERROR] Tavily search error: {e}")
            import traceback
            print(f"[ERROR] Tavily search traceback: {traceback.format_exc()}")
            return []


    async def _process_with_llm(
        self,
        query: str,
        tavily_results: List[Dict[str, Any]],
        session_id: str = "",
        user_id: str = "",
        detected_language: str = "ko"
    ) -> List["SearchResult"]:
        """LLM을 사용하여 Tavily 검색 결과를 처리하고 citation이 포함된 응답 생성"""
        try:
            if not tavily_results:
                print("[WARNING] No Tavily results to process with LLM")
                return []

            print(f"[DEBUG] Processing {len(tavily_results)} Tavily results with LLM...")

            # 중기 조치: max_tokens 최적화 (8000 → 2000) - 응답 시간 단축
            # 추가 최적화: thinking blocks 비활성화 - 검색 에이전트는 빠른 응답 필요
            base_llm = create_llm(
                temperature=0.1,
                max_tokens=2000,
                disable_thinking=settings.DISABLE_THINKING_FOR_SEARCH
            )

            # Wrap LLM with tracking for dataset collection
            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="realtime_info_search",
                agent_name=self.name,
                tags=["web_search", "synthesis"]
            )

            # Prepare search results context for LLM
            search_context = self._prepare_search_context(tavily_results)

            # Create prompt for LLM processing with detected language
            prompt = self._create_analysis_prompt(query, search_context, detected_language)

            print("[DEBUG] Sending request to LLM for result processing...")
            # 단기 조치: LLM 호출에 타임아웃 추가 (15초)
            try:
                response = await asyncio.wait_for(
                    llm.ainvoke([HumanMessage(content=prompt)]),
                    timeout=15.0  # 15초 타임아웃
                )
                llm_response = response.content
                print(f"[DEBUG] LLM response length: {len(llm_response)} characters")
            except asyncio.TimeoutError:
                print("[WARNING] LLM processing timed out after 15 seconds, returning raw results")
                # 타임아웃 시 raw 결과 반환 (빈 배열 대신)
                return self._create_raw_results(tavily_results)

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
                            "title": result.get("title", "") if isinstance(result, dict) else getattr(result, 'title', ''),
                            "url": result.get("url", "") if isinstance(result, dict) else getattr(result, 'url', ''),
                            "domain": result.get("domain", "") if isinstance(result, dict) else getattr(result, 'metadata', {}).get('domain', '') if hasattr(result, 'metadata') else ''
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

            # Fallback to raw results
            print("[DEBUG] Falling back to original Tavily results")
            return self._create_raw_results(tavily_results)

    def _create_raw_results(self, tavily_results: List[Dict[str, Any]]) -> List["SearchResult"]:
        """LLM 처리 없이 raw Tavily 결과를 SearchResult로 변환"""
        results = []
        for item in tavily_results:
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
            # Handle both dict and SearchResult objects
            if isinstance(result, dict):
                title = result.get("title", "제목 없음")
                content = result.get("content", "")
                url = result.get("url", "")
                domain = result.get("domain", "")
            else:
                # Handle SearchResult dataclass
                title = getattr(result, 'title', '제목 없음')
                content = getattr(result, 'content', '')
                url = getattr(result, 'url', '')
                domain = getattr(result, 'metadata', {}).get('domain', '') if hasattr(result, 'metadata') else ''

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

    def _create_analysis_prompt(self, query: str, search_context: str, detected_language: str = "ko") -> str:
        """LLM 분석을 위한 프롬프트 생성

        추가 최적화: 프롬프트 간소화 (7개 → 3개 요구사항)
        - 토큰 수 감소 및 LLM 처리 속도 향상
        """
        # 언어별 프롬프트 템플릿
        language_instructions = {
            "ko": """사용자 질문: {query}

검색 결과:
{search_context}

위 정보를 바탕으로 사용자 질문에 **한국어로** 답변하세요.
- 출처 명시 (예: 출처: 도메인)
- 정확한 수치/날짜 인용
- 객관적이고 완전한 답변 작성

답변:""",

            "en": """User Question: {query}

Search Results:
{search_context}

Answer the user's question **in English** based on the above information.
- Cite sources (e.g., Source: domain)
- Quote accurate figures/dates
- Provide objective and complete answer

Answer:""",

            "ja": """ユーザーの質問: {query}

検索結果:
{search_context}

上記の情報に基づき、ユーザーの質問に**日本語で**回答してください。
- 出典を明示（例：出典：ドメイン）
- 正確な数値/日付を引用
- 客観的で完全な回答を作成

回答:""",

            "zh": """用户问题: {query}

搜索结果:
{search_context}

基于上述信息，用**中文**回答用户问题。
- 标明来源（例：来源：域名）
- 引用准确数字/日期
- 提供客观完整的回答

回答:"""
        }

        template = language_instructions.get(detected_language, language_instructions["en"])
        return template.format(query=query, search_context=search_context)

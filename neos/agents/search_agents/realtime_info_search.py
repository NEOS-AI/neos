"""Real-time information search agent"""

from typing import Dict, Any, List, TYPE_CHECKING
import asyncio
import concurrent.futures
from tavily import TavilyClient
from langchain.schema import HumanMessage

from neos.config.settings import settings
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm

from ..base import SearchAgent

if TYPE_CHECKING:
    from neos.workflow.state import SearchResult


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

    async def _process_with_llm(self, query: str, tavily_results: List[Dict[str, Any]], session_id: str = "", user_id: str = "", detected_language: str = "ko") -> List["SearchResult"]:
        """LLM을 사용하여 Tavily 검색 결과를 처리하고 citation이 포함된 응답 생성"""
        try:
            if not tavily_results:
                print("[WARNING] No Tavily results to process with LLM")
                return []

            print(f"[DEBUG] Processing {len(tavily_results)} Tavily results with LLM...")

            # Create LLM instance with higher max_tokens for comprehensive responses
            base_llm = create_llm(temperature=0.1, max_tokens=4000)  # Low temperature for factual accuracy, higher token limit

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
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            llm_response = response.content

            print(f"[DEBUG] LLM response length: {len(llm_response)} characters")

            from neos.workflow.state import SearchResult

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

            from neos.workflow.state import SearchResult

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

    def _create_analysis_prompt(self, query: str, search_context: str, detected_language: str = "ko") -> str:
        """LLM 분석을 위한 프롬프트 생성"""
        # 언어별 프롬프트 템플릿
        language_instructions = {
            "ko": """
사용자 질문: {query}

다음은 웹 검색을 통해 수집된 정보들입니다:

{search_context}

위 검색 결과들을 바탕으로 사용자의 질문에 대해 종합적이고 정확한 답변을 **한국어로** 작성해주세요.

요구사항:
1. 각 정보의 출처를 명확히 인용하세요 (예: "출처: 도메인명")
2. 상충되는 정보가 있다면 이를 명시하고 설명하세요
3. 정확한 수치나 날짜가 있다면 그대로 인용하세요
4. 추측이나 확인되지 않은 정보는 추가하지 마세요
5. **한국어로 작성하되**, 전문적이고 객관적인 톤을 유지하세요
6. **중요**: 답변을 완전히 작성하세요. 문장이나 문단 중간에 끊지 마세요.
7. 각 주제별로 상세한 분석을 제공하세요.

답변:""",

            "en": """
User Question: {query}

The following information was collected through web search:

{search_context}

Based on the above search results, please write a comprehensive and accurate answer to the user's question **in English**.

Requirements:
1. Clearly cite the source of each piece of information (e.g., "Source: domain name")
2. If there is conflicting information, explicitly mention and explain it
3. If there are accurate figures or dates, quote them as is
4. Do not add speculation or unverified information
5. **Write in English** while maintaining a professional and objective tone
6. **Important**: Complete your answer fully. Do not stop in the middle of sentences or paragraphs.
7. Provide detailed analysis for each topic.

Answer:""",

            "ja": """
ユーザーの質問: {query}

以下は、ウェブ検索を通じて収集された情報です:

{search_context}

上記の検索結果に基づいて、ユーザーの質問に対する包括的で正確な回答を**日本語で**作成してください。

要件:
1. 各情報の出典を明確に引用してください（例：「出典：ドメイン名」）
2. 矛盾する情報がある場合は、それを明示して説明してください
3. 正確な数値や日付がある場合は、そのまま引用してください
4. 推測や未確認の情報は追加しないでください
5. **日本語で作成し**、プロフェッショナルで客観的なトーンを維持してください
6. **重要**: 回答を完全に作成してください。文章や段落の途中で止めないでください。
7. 各トピックについて詳細な分析を提供してください。

回答:""",

            "zh": """
用户问题: {query}

以下是通过网络搜索收集的信息:

{search_context}

基于上述搜索结果，请用**中文**撰写对用户问题的全面准确的回答。

要求:
1. 明确引用每条信息的来源（例如："来源：域名"）
2. 如有矛盾信息，请明确说明并解释
3. 如有准确的数字或日期，请原样引用
4. 不要添加推测或未经验证的信息
5. **用中文撰写**，保持专业客观的语气
6. **重要**: 完整撰写答案。不要在句子或段落中途停止。
7. 为每个主题提供详细分析。

回答:"""
        }

        template = language_instructions.get(detected_language, language_instructions["en"])
        return template.format(query=query, search_context=search_context)

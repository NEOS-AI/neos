"""Multi-query search agent - generates multiple queries and synthesizes results"""

from typing import Dict, Any, List, TYPE_CHECKING
from tavily import TavilyClient
from langchain.schema import HumanMessage

from neos.config.settings import settings
from neos.utils.llm_factory import create_llm

from ..base import SearchAgent
from ..planning_agent import PlanningAgent

if TYPE_CHECKING:
    from neos.workflow.state import SearchResult


class MultiQuerySearchAgent(SearchAgent):
    """복합검색 에이전트 - 여러 검색 쿼리를 생성하고 종합 분석"""

    def __init__(self):
        super().__init__(
            name="multi_query_search",
            search_type="multi_query",
            role="Multi-Query Search Specialist",
            goal="Generate multiple search queries, execute them, and synthesize comprehensive results",
            backstory="You are an expert at breaking down complex questions into multiple targeted search queries and synthesizing the results into comprehensive insights."
        )
        # Tavily client 초기화
        self.tavily_client = None
        self.api_available = False
        # Planning agent 초기화
        self.planning_agent = PlanningAgent()

        print(f"[DEBUG] MultiQuerySearchAgent checking TAVILY_API_KEY: {'SET' if settings.TAVILY_API_KEY else 'NOT SET'}")
        if settings.TAVILY_API_KEY and settings.TAVILY_API_KEY.strip():
            try:
                print("[DEBUG] Creating TavilyClient for multi-query search...")
                self.tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
                self.api_available = True
                print("[DEBUG] TavilyClient created successfully for multi-query search")
            except Exception as e:
                print(f"[WARNING] Failed to create TavilyClient for multi-query search: {e}")
                self.tavily_client = None
                self.api_available = False
        else:
            print("[WARNING] TAVILY_API_KEY not set, MultiQuerySearchAgent will return empty results")

    def _get_synthesis_language_instruction(self, language: str) -> str:
        """언어별 종합 분석 지침 반환"""
        instructions = {
            "ko": """위의 모든 분석 결과를 종합하여 사용자의 질문에 대한 포괄적이고 심층적인 답변을 **한국어로** 작성해주세요.

요구사항:
1. 모든 관점의 정보를 통합하여 전체적인 그림을 제시하세요
2. 상충되는 정보가 있다면 명시하고 설명하세요
3. 구체적인 수치, 날짜, 출처를 반드시 인용하세요
4. 각 기업/주제별로 구조화된 분석을 제공하세요
5. 객관적이고 전문적인 톤을 유지하세요
6. 답변을 완전히 작성하세요 (중간에 끊지 마세요)
7. 마크다운 형식으로 보기 좋게 구조화하세요
8. **모든 답변을 한국어로 작성하세요**

종합 분석:""",

            "en": """Based on all the analysis results above, please write a comprehensive and in-depth answer to the user's question **in English**.

Requirements:
1. Integrate information from all perspectives to present the complete picture
2. Explicitly mention and explain any conflicting information
3. Always cite specific numbers, dates, and sources
4. Provide structured analysis for each company/topic
5. Maintain an objective and professional tone
6. Complete the answer fully (do not stop in the middle)
7. Structure the content nicely in markdown format
8. **Write all content in English**

Comprehensive Analysis:""",

            "ja": """上記のすべての分析結果を統合して、ユーザーの質問に対する包括的で詳細な回答を**日本語で**作成してください。

要件：
1. すべての観点からの情報を統合して全体像を提示してください
2. 矛盾する情報があれば明示して説明してください
3. 具体的な数値、日付、出典を必ず引用してください
4. 各企業/トピックごとに構造化された分析を提供してください
5. 客観的でプロフェッショナルなトーンを維持してください
6. 回答を完全に作成してください（途中で止めないでください）
7. マークダウン形式で見やすく構造化してください
8. **すべての内容を日本語で作成してください**

総合分析：""",

            "zh": """基于以上所有分析结果，请用**中文**撰写一份对用户问题的全面深入回答。

要求：
1. 整合所有角度的信息，呈现完整图景
2. 如有冲突信息，请明确说明并解释
3. 务必引用具体的数字、日期和来源
4. 为每个公司/主题提供结构化分析
5. 保持客观专业的语气
6. 完整撰写答案（不要中途停止）
7. 使用markdown格式清晰结构化内容
8. **所有内容使用中文撰写**

综合分析："""
        }

        return instructions.get(language, instructions["en"])  # 기본값은 영어

    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        print(f"[DEBUG] MultiQuerySearchAgent.execute called with query: {query[:50]}...")

        if not self.validate_input(query, context):
            print("[ERROR] MultiQuerySearchAgent: Invalid input")
            return {"success": False, "error": "Invalid input"}

        if not self.api_available:
            print("[WARNING] TAVILY_API_KEY not available, returning empty results")
            return self.format_output([], {"search_type": "multi_query", "warning": "API key not available"})

        try:
            # Extract session_id and user_id from context
            session_id = context.get("session_id", "") if context else ""
            user_id = context.get("user_id", "") if context else ""

            # Extract detected_language from context
            detected_language = context.get("detected_language", "ko") if context else "ko"

            # Step 0: Create research plan using planning agent
            print("[DEBUG] Creating research plan...")
            research_plan = await self.planning_agent.create_research_plan(
                query=query,
                research_type="multi_query",
                session_id=session_id,
                user_id=user_id,
                detected_language=detected_language
            )
            print(f"[DEBUG] Research plan created with {len(research_plan)} tasks")
            print(f"[DEBUG] Plan:\n{self.planning_agent.get_task_summary(research_plan)}")

            # Step 1: LLM을 사용하여 검색 쿼리 후보 생성 (2-5개)
            # Update plan: mark query generation as in progress
            if research_plan:
                self.planning_agent.update_task_status(research_plan, 1, "in_progress")
                print(f"[DEBUG] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

            print("[DEBUG] Generating search query candidates...")
            search_queries = await self._generate_search_queries(query, session_id, user_id, detected_language)
            print(f"[DEBUG] Generated {len(search_queries)} search queries")

            # Mark query generation as completed
            if research_plan:
                self.planning_agent.update_task_status(
                    research_plan, 1, "completed",
                    result=f"Generated {len(search_queries)} queries: {', '.join(search_queries[:3])}"
                )
                print(f"[DEBUG] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

            # Step 2: 각 쿼리에 대해 병렬 검색 실행
            if research_plan and len(research_plan) > 1:
                self.planning_agent.update_task_status(research_plan, 2, "in_progress")
                print(f"[DEBUG] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

            print("[DEBUG] Executing parallel searches...")
            search_results = await self._execute_parallel_searches(search_queries)
            print(f"[DEBUG] Completed parallel searches, total results: {sum(len(r) for r in search_results)}")

            if research_plan and len(research_plan) > 1:
                self.planning_agent.update_task_status(
                    research_plan, 2, "completed",
                    result=f"Collected {sum(len(r) for r in search_results)} search results"
                )
                print(f"[DEBUG] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

            # Step 3: 각 검색 결과를 LLM으로 요약
            if research_plan and len(research_plan) > 2:
                self.planning_agent.update_task_status(research_plan, 3, "in_progress")
                print(f"[DEBUG] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

            print("[DEBUG] Summarizing individual search results...")
            summaries = await self._summarize_results(search_queries, search_results, session_id, user_id, detected_language)
            print(f"[DEBUG] Generated {len(summaries)} summaries")

            if research_plan and len(research_plan) > 2:
                self.planning_agent.update_task_status(
                    research_plan, 3, "completed",
                    result=f"Generated {len(summaries)} summaries"
                )
                print(f"[DEBUG] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

            # Step 4: 모든 요약을 종합하여 최종 분석 결과 생성
            if research_plan and len(research_plan) > 3:
                self.planning_agent.update_task_status(research_plan, 4, "in_progress")
                print(f"[DEBUG] Updated plan:\n{self.planning_agent.get_task_summary(research_plan)}")

            print("[DEBUG] Synthesizing final comprehensive analysis...")
            final_analysis = await self._synthesize_final_analysis(query, search_queries, summaries, session_id, user_id, context)
            print("[DEBUG] Final analysis completed")

            if research_plan and len(research_plan) > 3:
                self.planning_agent.update_task_status(
                    research_plan, 4, "completed",
                    result=f"Completed final analysis ({len(final_analysis)} characters)"
                )
                print(f"[DEBUG] Final plan:\n{self.planning_agent.get_task_summary(research_plan)}")

            # 결과 생성
            from neos.workflow.state import SearchResult
            result = SearchResult(
                source="multi_query_analysis",
                title=f"복합 분석: {query}",
                content=final_analysis,
                url="",
                score=0.98,  # High score for comprehensive multi-query analysis
                metadata={
                    "processing_type": "multi_query_synthesis",
                    "query_count": len(search_queries),
                    "search_queries": search_queries,
                    "total_sources": sum(len(r) for r in search_results),
                    "summaries": summaries
                }
            )

            print("[DEBUG] MultiQuerySearchAgent execution completed successfully")
            return self.format_output([result], {"search_type": "multi_query"})

        except Exception as e:
            print(f"[ERROR] MultiQuerySearchAgent execution failed: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")
            return {"success": False, "error": str(e), "agent": self.name}

    async def _generate_search_queries(self, original_query: str, session_id: str = "", user_id: str = "", detected_language: str = "ko") -> List[str]:
        """LLM을 사용하여 검색 쿼리 후보 2-5개 생성"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            base_llm = create_llm(temperature=0.3, max_tokens=1000)

            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="multi_query_search",
                agent_name=self.name,
                tags=["query_generation"]
            )

            # 언어별 프롬프트
            prompts = {
                "ko": f"""사용자 질문: {original_query}

위 질문에 대해 포괄적이고 정확한 답변을 얻기 위해 필요한 검색 쿼리 2-5개를 생성해주세요.

요구사항:
1. 각 쿼리는 서로 다른 관점이나 측면을 다뤄야 합니다
2. 너무 일반적이지 않고 구체적인 쿼리를 만드세요
3. 한국어와 영어를 적절히 혼합하여 사용하세요
4. 각 쿼리는 한 줄로 작성하고, 번호를 붙이지 마세요
5. 쿼리 사이는 빈 줄로 구분하세요

검색 쿼리:""",

                "en": f"""User Question: {original_query}

Generate 2-5 search queries needed to obtain comprehensive and accurate answers to the above question.

Requirements:
1. Each query should cover a different perspective or aspect
2. Make specific queries rather than too general ones
3. Use English appropriately
4. Write each query on a single line without numbering
5. Separate queries with blank lines

Search Queries:""",

                "ja": f"""ユーザーの質問: {original_query}

上記の質問に対して包括的で正確な回答を得るために必要な検索クエリを2-5個生成してください。

要件:
1. 各クエリは異なる観点や側面を扱う必要があります
2. あまり一般的でなく、具体的なクエリを作成してください
3. 日本語を適切に使用してください
4. 各クエリは1行で作成し、番号を付けないでください
5. クエリ間は空白行で区切ってください

検索クエリ:""",

                "zh": f"""用户问题: {original_query}

生成2-5个搜索查询，以获得对上述问题的全面准确的回答。

要求:
1. 每个查询应涵盖不同的观点或方面
2. 创建具体的查询，而不是过于笼统的
3. 适当使用中文
4. 每个查询写在一行，不要编号
5. 查询之间用空行分隔

搜索查询:"""
            }

            prompt = prompts.get(detected_language, prompts["en"])

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            query_text = response.content.strip()

            # 쿼리 파싱 (빈 줄 또는 줄바꿈으로 구분)
            queries = [q.strip() for q in query_text.split('\n') if q.strip() and not q.strip().startswith('#')]

            # 2-5개로 제한
            queries = queries[:5] if len(queries) >= 2 else queries

            # 최소 2개 보장
            if len(queries) < 2:
                queries = [original_query, f"{original_query} 최신 동향"]

            print(f"[DEBUG] Generated queries: {queries}")
            return queries

        except Exception as e:
            print(f"[ERROR] Failed to generate search queries: {e}")
            # Fallback: 원본 쿼리만 사용
            return [original_query]

    async def _execute_parallel_searches(self, queries: List[str]) -> List[List[Dict[str, Any]]]:
        """여러 검색 쿼리를 병렬로 실행"""
        import asyncio

        search_tasks = [self._single_tavily_search(q) for q in queries]
        results = await asyncio.gather(*search_tasks, return_exceptions=True)

        # Exception 처리
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"[WARNING] Search for query '{queries[i]}' failed: {result}")
                processed_results.append([])
            else:
                processed_results.append(result)

        return processed_results

    async def _single_tavily_search(self, query: str) -> List[Dict[str, Any]]:
        """단일 Tavily 검색"""
        try:
            if not self.api_available or not self.tavily_client:
                return []

            import asyncio
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                try:
                    future = executor.submit(
                        self.tavily_client.search,
                        query=query,
                        search_depth="advanced",
                        max_results=3,  # 각 쿼리당 3개 결과
                        include_answer=True,
                        include_raw_content=True
                    )

                    def get_result_with_timeout():
                        try:
                            return future.result(timeout=20)
                        except concurrent.futures.TimeoutError:
                            return None

                    response = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, get_result_with_timeout),
                        timeout=25
                    )

                    return response.get("results", []) if response else []

                except Exception as e:
                    print(f"[ERROR] Single search failed for '{query}': {e}")
                    return []

        except Exception as e:
            print(f"[ERROR] Tavily search error: {e}")
            return []

    async def _summarize_results(self, queries: List[str], results: List[List[Dict[str, Any]]], session_id: str = "", user_id: str = "", detected_language: str = "ko") -> List[str]:
        """각 검색 결과를 LLM으로 요약 (병렬 처리)"""
        import asyncio

        async def summarize_single_query(query: str, search_results: List[Dict[str, Any]]) -> str:
            """단일 쿼리 결과 요약"""
            # 언어별 fallback 메시지
            no_results_messages = {
                "ko": f"검색 쿼리 '{query}'에 대한 결과를 찾지 못했습니다.",
                "en": f"No results found for search query '{query}'.",
                "ja": f"検索クエリ '{query}' の結果が見つかりませんでした。",
                "zh": f"未找到搜索查询 '{query}' 的结果。"
            }

            if not search_results:
                return no_results_messages.get(detected_language, no_results_messages["en"])

            try:
                from neos.utils.llm_wrapper import create_tracked_llm
                base_llm = create_llm(temperature=0.1, max_tokens=1500)  # 토큰 수 줄임

                llm = create_tracked_llm(
                    llm=base_llm,
                    session_id=session_id,
                    user_id=user_id,
                    workflow_step="multi_query_search",
                    agent_name=self.name,
                    tags=["result_summarization"]
                )

                # 검색 결과를 문맥으로 준비
                context_parts = []
                for i, result in enumerate(search_results[:3], 1):  # 상위 3개만
                    title = result.get("title", "")
                    content = result.get("content", "")[:400]  # 400자로 줄임
                    url = result.get("url", "")

                    context_parts.append(f"""
Result {i}:
Title: {title}
Source: {url}
Content: {content}
""")

                context = "\n".join(context_parts)

                # 언어별 프롬프트
                prompts = {
                    "ko": f"""검색 쿼리: {query}

검색 결과:
{context}

위 검색 결과들을 바탕으로 핵심 정보를 간결하게 **한국어로** 요약해주세요 (3-5문장). 출처를 명시하고, 중요한 사실과 수치를 포함하세요.

요약:""",

                    "en": f"""Search Query: {query}

Search Results:
{context}

Based on the above search results, please provide a concise summary of key information **in English** (3-5 sentences). Include sources and important facts and figures.

Summary:""",

                    "ja": f"""検索クエリ: {query}

検索結果:
{context}

上記の検索結果に基づいて、重要な情報を簡潔に**日本語で**要約してください（3-5文）。出典を明記し、重要な事実と数値を含めてください。

要約:""",

                    "zh": f"""搜索查询: {query}

搜索结果:
{context}

根据以上搜索结果，请用**中文**简要总结关键信息（3-5句）。请注明来源，并包含重要事实和数据。

摘要:"""
                }

                prompt = prompts.get(detected_language, prompts["en"])

                response = await llm.ainvoke([HumanMessage(content=prompt)])
                return response.content.strip()

            except Exception as e:
                print(f"[ERROR] Failed to summarize results for '{query}': {e}")
                error_messages = {
                    "ko": f"검색 쿼리 '{query}'에 대한 요약 생성 실패",
                    "en": f"Failed to generate summary for search query '{query}'",
                    "ja": f"検索クエリ '{query}' の要約生成に失敗しました",
                    "zh": f"生成搜索查询 '{query}' 的摘要失败"
                }
                return error_messages.get(detected_language, error_messages["en"])

        # 모든 요약을 병렬로 처리
        print(f"[DEBUG] Starting parallel summarization for {len(queries)} queries...")
        summary_tasks = [summarize_single_query(q, r) for q, r in zip(queries, results)]

        try:
            summaries = await asyncio.wait_for(
                asyncio.gather(*summary_tasks, return_exceptions=True),
                timeout=60  # 60초 타임아웃
            )

            # Exception 처리
            error_messages = {
                "ko": "요약 생성 실패",
                "en": "Failed to generate summary",
                "ja": "要約生成に失敗しました",
                "zh": "生成摘要失败"
            }
            timeout_messages = {
                "ko": "요약 생성 시간 초과",
                "en": "Summary generation timed out",
                "ja": "要約生成がタイムアウトしました",
                "zh": "摘要生成超时"
            }

            processed_summaries = []
            for i, summary in enumerate(summaries):
                if isinstance(summary, Exception):
                    print(f"[ERROR] Summary task {i+1} failed: {summary}")
                    error_msg = error_messages.get(detected_language, error_messages["en"])
                    processed_summaries.append(f"{error_msg}: '{queries[i]}'")
                else:
                    processed_summaries.append(summary)

            print(f"[DEBUG] Parallel summarization completed: {len(processed_summaries)} summaries")
            return processed_summaries

        except asyncio.TimeoutError:
            print("[ERROR] Summarization timed out after 60 seconds")
            timeout_msg = timeout_messages.get(detected_language, timeout_messages["en"])
            return [f"{timeout_msg}: '{q}'" for q in queries]

    async def _synthesize_final_analysis(self, original_query: str, search_queries: List[str], summaries: List[str], session_id: str = "", user_id: str = "", context: Dict[str, Any] = None) -> str:
        """모든 요약을 종합하여 최종 분석 결과 생성"""
        try:
            from neos.utils.llm_wrapper import create_tracked_llm
            base_llm = create_llm(temperature=0.2, max_tokens=4000)

            llm = create_tracked_llm(
                llm=base_llm,
                session_id=session_id,
                user_id=user_id,
                workflow_step="multi_query_search",
                agent_name=self.name,
                tags=["final_synthesis"]
            )

            # 감지된 언어 가져오기
            detected_language = context.get("detected_language", "ko") if context else "ko"

            # 요약들을 하나의 문맥으로 결합
            summary_context = ""
            for i, (query, summary) in enumerate(zip(search_queries, summaries), 1):
                summary_context += f"""
검색 관점 {i}: {query}
분석 결과: {summary}

"""

            # 언어별 프롬프트 생성
            language_instruction = self._get_synthesis_language_instruction(detected_language)

            prompt = f"""사용자 질문: {original_query}

다음은 여러 관점에서 수집하고 분석한 정보입니다:

{summary_context}

{language_instruction}"""

            import asyncio

            # 최종 분석에도 타임아웃 추가 (90초)
            response = await asyncio.wait_for(
                llm.ainvoke([HumanMessage(content=prompt)]),
                timeout=90
            )
            final_analysis = response.content.strip()

            return final_analysis

        except asyncio.TimeoutError:
            print("[ERROR] Final analysis synthesis timed out after 90 seconds")
            # Fallback: 요약들을 단순 결합
            return "\n\n".join([f"**{q}**\n{s}" for q, s in zip(search_queries, summaries)])

        except Exception as e:
            print(f"[ERROR] Failed to synthesize final analysis: {e}")
            import traceback
            print(f"[ERROR] Traceback: {traceback.format_exc()}")

            # Fallback: 요약들을 단순 결합
            return "\n\n".join([f"**{q}**\n{s}" for q, s in zip(search_queries, summaries)])



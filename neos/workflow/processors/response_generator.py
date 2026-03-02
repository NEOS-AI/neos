"""응답 생성 모듈"""

import logging
from typing import Dict, Any, List
from datetime import datetime
from urllib.parse import urlparse
from langchain_core.messages import HumanMessage

from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm, extract_text_from_response
from neos.config.settings import settings
from ..state import AgentState

logger = logging.getLogger(__name__)


class ResponseGenerator:
    """최종 응답 생성"""

    def __init__(self):
        pass

    def _get_llm(self, temperature: float = 0.3, max_tokens: int = 4000):
        """
        LLM 인스턴스를 가져옵니다.

        LLMFactory의 다중 키 캐싱을 활용하여 (model, temperature, max_tokens) 조합별로
        인스턴스를 재사용합니다.
        """
        return create_llm(
            temperature=temperature,
            max_tokens=max_tokens,
            use_cache=True  # LLMFactory 캐시 활용
        )

    async def generate_response(self, state: AgentState) -> Dict[str, Any]:
        """최종 응답 생성"""
        logger.debug("[ResponseGenerator] Starting response generation...")

        # 모든 결과를 종합하여 응답 생성
        response_parts = []

        # 검색 결과 요약
        if state["search_results"] and len(state["search_results"]) > 0:
            logger.debug(f"[ResponseGenerator] Generating search summary from {len(state['search_results'])} results")
            search_summary = self._create_search_summary(state["search_results"])
            if search_summary and "검색된 고유한 결과가 없습니다" not in search_summary:
                response_parts.append(search_summary)
            else:
                logger.debug("[ResponseGenerator] No unique search results found, skipping search summary")

        # 분석 결과 요약
        if state["analysis_results"] and len(state["analysis_results"]) > 0:
            logger.debug(f"[ResponseGenerator] Generating analysis summary from {len(state['analysis_results'])} results")
            analysis_summary = self._create_analysis_summary(state["analysis_results"])
            if analysis_summary:
                response_parts.append(analysis_summary)

        # 생성 결과 요약
        if state["generation_results"] and len(state["generation_results"]) > 0:
            logger.debug(f"[ResponseGenerator] Generating generation summary from {len(state['generation_results'])} results")
            generation_summary = self._create_generation_summary(state["generation_results"])
            if generation_summary:
                response_parts.append(generation_summary)

        # Phase 3: 조건부 LLM 기반 최종 정제
        detected_language = state.get("detected_language", "ko")

        # 부분 성공 케이스이거나 에러가 있는 경우 LLM 정제 적용
        # 안전한 None 처리: search_metadata가 None일 수 있음 (타임아웃 등)
        search_metadata = state.get("search_metadata") or {}
        should_refine = (
            search_metadata.get("partial_success", False) or  # 부분 성공
            len(state.get("errors", [])) > 0  # 에러 발생
        )

        if should_refine and response_parts and settings.ENABLE_RESPONSE_REFINEMENT:
            logger.debug("[ResponseGenerator] Applying LLM-based response refinement (partial success or errors detected)")
            final_response = await self._refine_response_with_llm(
                query=state["original_query"],
                response_parts=response_parts,
                language=detected_language,
                session_id=state.get("session_id", ""),
                user_id=state.get("user_id", "")
            )
        else:
            # LLM 정제 없이 기본 구성
            final_response = self._construct_final_response(response_parts, detected_language)

        # Citation 적용
        if final_response and state["search_results"] and settings.CITATIONS_ENABLED:
            final_response = self._apply_citations(final_response, state)

        # Phase 4.1: 해결된 모순 정보를 응답에 포함
        if final_response:
            fact_check = state.get("fact_check_result") or {}
            resolutions = fact_check.get("contradiction_resolutions", [])
            if resolutions:
                headers = {
                    "ko": "**소스 간 모순 분석:**",
                    "en": "**Contradiction Analysis Across Sources:**",
                    "ja": "**ソース間の矛盾分析:**",
                    "zh": "**来源间矛盾分析:**",
                }
                header = headers.get(detected_language, headers["en"])
                resolution_block = f"\n\n---\n\n{header}\n\n"
                for r in resolutions:
                    resolution_block += f"{r}\n\n"
                final_response = final_response + resolution_block

        # Phase 2.10: Executive Summary 생성
        executive_summary = None
        if final_response and getattr(settings, "EXECUTIVE_SUMMARY_ENABLED", False):
            try:
                from ..utils.executive_summary import executive_summary_generator
                executive_summary = await executive_summary_generator.generate(
                    response=final_response,
                    query=state["original_query"],
                    language=detected_language,
                )
                if executive_summary:
                    state["executive_summary"] = executive_summary
                    final_response = f"> **TL;DR:** {executive_summary}\n\n---\n\n{final_response}"
                    logger.debug(f"[ResponseGenerator] Executive summary prepended ({len(executive_summary)} chars)")
            except Exception as e:
                logger.debug(f"[ResponseGenerator] Executive summary generation skipped: {e}")

        # 실행 시간 계산
        execution_time = int((datetime.now() - state["execution_start"]).total_seconds() * 1000)

        # 상태 업데이트
        state["final_response"] = final_response
        state["execution_time_ms"] = execution_time
        state["response_metadata"] = self._create_response_metadata(state)

        logger.debug("[ResponseGenerator] generation result: ", state["generation_results"])
        logger.debug(f"[ResponseGenerator] Response generation completed. Length: {len(final_response)} characters")

        state["execution_steps"].append({
            "step": "response_generation",
            "result": "completed",
            "timestamp": datetime.now().isoformat()
        })

        return state

    def _construct_final_response(self, response_parts: List[str], detected_language: str = "ko") -> str:
        """최종 응답 구성"""
        if response_parts:
            return "\n\n".join(response_parts)
        else:
            # 언어별 기본 메시지
            default_messages = {
                "ko": "죄송합니다. 요청하신 주제에 대한 관련 정보를 찾지 못했습니다. 다른 키워드로 다시 시도해 보시기 바랍니다.",
                "en": "Sorry, we couldn't find relevant information on the requested topic. Please try again with different keywords.",
                "ja": "申し訳ございません。お探しのトピックに関する関連情報が見つかりませんでした。別のキーワードで再度お試しください。",
                "zh": "抱歉，我们未能找到有关所请求主题的相关信息。请尝试使用不同的关键词重新搜索。"
            }
            return default_messages.get(detected_language, default_messages["en"])

    def _create_response_metadata(self, state: AgentState) -> Dict[str, Any]:
        """응답 메타데이터 생성"""
        return {
            "total_sources": len(state["search_results"]),
            "analysis_count": len(state["analysis_results"]),
            "generation_count": len(state["generation_results"]),
            "quality_score": state.get("quality_score", 0.0),
            "execution_time_ms": state.get("execution_time_ms", 0),
            "total_errors": len(state["errors"]),
            "processing_steps": len(state["execution_steps"])
        }

    def _create_search_summary(self, results: List[Any]) -> str:
        """검색 결과 요약 생성"""
        if not results:
            return ""

        # 점수순 정렬 및 중복 제거
        sorted_results = sorted(results, key=lambda x: getattr(x, 'score', 0), reverse=True)

        # 주제별 분류
        categorized_results = self._categorize_results_by_topic(sorted_results)

        if not any(categorized_results.values()):
            return "## 검색 결과\n검색된 고유한 결과가 없습니다."

        summary_lines = []

        # 모든 카테고리의 결과를 통합 (nvidia, meta, alphabet, general)
        all_results = []
        for category in ['nvidia', 'meta', 'alphabet', 'general']:
            all_results.extend(categorized_results.get(category, []))

        if all_results:
            summary_lines.append("\n### 🔹 검색 결과")
            summary_lines.extend(self._format_general_results(all_results))

        return "\n".join(summary_lines)

    def _format_company_results(self, results: List[Any]) -> List[str]:
        """회사별 결과 포맷팅"""
        formatted_results = []

        for i, result in enumerate(results[:2]):  # 상위 2개 결과만
            title = getattr(result, 'title', '제목 없음')
            content = getattr(result, 'content', '')
            url = getattr(result, 'url', '')

            # 소스별 처리
            source = getattr(result, 'source', '')
            if source == 'llm_processed_web':
                processed_content = content
                citation_info = ""  # LLM이 이미 인용 포함
            else:
                processed_content = self._process_content_for_display(content, max_length=1200)
                citation_info = self._format_citation(url)

            formatted_results.append(f"**{title}**\n{processed_content}{citation_info}\n")

        return formatted_results

    def _format_general_results(self, results: List[Any]) -> List[str]:
        """일반 결과 포맷팅"""
        formatted_results = []

        # LLM이 처리한 결과가 있으면 우선 표시
        llm_processed = [r for r in results if getattr(r, 'source', '') in ['llm_processed_web', 'multi_query_analysis', 'deep_research_report']]
        other_results = [r for r in results if getattr(r, 'source', '') not in ['llm_processed_web', 'multi_query_analysis', 'deep_research_report']]

        # LLM 처리 결과는 전체 표시 (이미 요약되어 있음)
        for result in llm_processed[:3]:  # 최대 3개
            title = getattr(result, 'title', '제목 없음')
            content = getattr(result, 'content', '')
            formatted_results.append(f"**{title}**\n{content}\n")

        # 일반 검색 결과는 일부만 표시
        for result in other_results[:2]:  # 상위 2개
            title = getattr(result, 'title', '제목 없음')
            content = getattr(result, 'content', '')
            url = getattr(result, 'url', '')

            processed_content = self._process_content_for_display(content, max_length=800)
            citation_info = self._format_citation(url)

            formatted_results.append(f"**{title}**\n{processed_content}{citation_info}\n")

        return formatted_results

    def _create_analysis_summary(self, results: List[Any]) -> str:
        """분석 결과 요약 생성"""
        if not results:
            return ""

        logger.debug(f"[ResponseGenerator] Creating analysis summary from {len(results)} results")
        summary_lines = ["## 분석 결과"]
        found_insights = False

        for result in results:
            analysis_type = getattr(result, 'analysis_type', '분석')
            insights = getattr(result, 'insights', [])
            if not insights:
                continue
            found_insights = True

            summary_lines.append(f"### {analysis_type}")
            for insight in insights[:3]:  # 최대 3개의 인사이트
                summary_lines.append(f"- {insight}")

        if not found_insights:
            return ""
        return "\n".join(summary_lines)

    def _create_generation_summary(self, results: List[Any]) -> str:
        """생성 결과 요약 생성"""
        if not results:
            return ""

        summary_lines = ["## 생성 결과"]

        for result in results:
            content_type = getattr(result, 'content_type', '콘텐츠')
            content = getattr(result, 'content', '')

            summary_lines.append(f"### {content_type}")
            if content:
                # 생성된 콘텐츠가 길면 요약
                if len(content) > 500:
                    summary_lines.append(f"{content[:500]}...")
                else:
                    summary_lines.append(content)

        return "\n".join(summary_lines)

    def _categorize_results_by_topic(self, results: List[Any]) -> Dict[str, List[Any]]:
        """주제별 결과 분류"""
        from ..utils.content_processor import ContentProcessor
        processor = ContentProcessor()
        return processor.categorize_results_by_topic(results)

    def _process_content_for_display(self, content: str, max_length: int = 400) -> str:
        """표시용 콘텐츠 처리"""
        from ..utils.content_processor import ContentProcessor
        processor = ContentProcessor()
        return processor.process_content_for_display(content, max_length)

    def _format_citation(self, url: str) -> str:
        """인용 정보 포맷팅"""
        from ..utils.content_processor import ContentProcessor
        processor = ContentProcessor()
        return processor.format_citation(url)

    async def _refine_response_with_llm(
        self,
        query: str,
        response_parts: List[str],
        language: str,
        session_id: str = "",
        user_id: str = ""
    ) -> str:
        """Phase 3: LLM으로 응답 정제 - 에러 메시지 제거 및 일관성 개선

        부분 성공 케이스에서 호출되어 다음을 수행:
        1. 에러 메시지 패턴 제거
        2. 중복 정보 정리
        3. 일관성 있는 구조로 재구성
        4. 읽기 쉽게 개선

        Args:
            query: 사용자 쿼리
            response_parts: 응답 파트 리스트
            language: 응답 언어
            session_id: 세션 ID
            user_id: 사용자 ID

        Returns:
            정제된 최종 응답
        """
        combined = "\n\n".join(response_parts)

        prompt = self._get_refinement_prompt(query, combined, language)

        # LLM 호출 (재사용 가능한 LLM 객체)
        base_llm = self._get_llm(temperature=0.3, max_tokens=4000)

        llm = create_tracked_llm(
            llm=base_llm,
            session_id=session_id,
            user_id=user_id,
            workflow_step="response_refinement",
            agent_name="response_generator",
            tags=["response_refinement", f"language:{language}"],
            custom_metadata={
                "query": query,
                "purpose": "refine_final_response"
            }
        )

        response = await llm.ainvoke([HumanMessage(content=prompt)])
        refined = extract_text_from_response(response).strip()

        logger.debug(f"[ResponseGenerator] Response refined by LLM. Original: {len(combined)}, Refined: {len(refined)}")
        return refined

    def _get_refinement_prompt(self, query: str, combined_response: str, language: str) -> str:
        """응답 정제 프롬프트 생성"""
        prompts = {
            "ko": f"""다음은 사용자 질문에 대한 검색 결과를 기반으로 생성된 응답입니다.

사용자 질문: {query}

생성된 응답:
{combined_response}

위 응답을 다음 기준에 따라 정제해주세요:

1. **에러 메시지 제거**: "검색 결과 없음", "요약 실패", "No results found" 등의 모든 에러 메시지 제거
2. **중복 제거**: 반복되는 정보는 한 번만 언급
3. **일관성 개선**: 논리적 흐름으로 재구성
4. **가독성 향상**: 마크다운 형식으로 깔끔하게 정리
5. **완전성 유지**: 유용한 정보는 모두 보존

**중요**: 에러 메시지나 기술적 오류 내용은 절대 포함하지 마세요. 실제 유용한 정보만 남겨주세요.

정제된 응답:""",

            "en": f"""Here is a response generated based on search results for the user's question.

User Question: {query}

Generated Response:
{combined_response}

Please refine the response according to these criteria:

1. **Remove Error Messages**: Remove all error messages like "No results found", "Failed to", etc.
2. **Remove Duplicates**: Mention repeated information only once
3. **Improve Consistency**: Restructure with logical flow
4. **Enhance Readability**: Format cleanly in markdown
5. **Maintain Completeness**: Preserve all useful information

**Important**: Never include error messages or technical errors. Keep only actually useful information.

Refined Response:""",

            "ja": f"""以下は、ユーザーの質問に対する検索結果に基づいて生成された回答です。

ユーザーの質問: {query}

生成された回答:
{combined_response}

以下の基準に従って回答を精製してください:

1. **エラーメッセージの削除**: 「結果が見つかりません」「失敗しました」などのすべてのエラーメッセージを削除
2. **重複の削除**: 繰り返される情報は一度だけ言及
3. **一貫性の改善**: 論理的な流れで再構成
4. **可読性の向上**: マークダウン形式できれいに整理
5. **完全性の維持**: 有用な情報はすべて保持

**重要**: エラーメッセージや技術的エラーは絶対に含めないでください。実際に有用な情報のみを残してください。

精製された回答:""",

            "zh": f"""以下是根据用户问题的搜索结果生成的回答。

用户问题: {query}

生成的回答:
{combined_response}

请根据以下标准精炼回答:

1. **删除错误消息**: 删除所有"未找到结果"、"失败"等错误消息
2. **删除重复**: 重复的信息只提及一次
3. **改善一致性**: 以逻辑流程重组
4. **提高可读性**: 以markdown格式整洁地整理
5. **保持完整性**: 保留所有有用信息

**重要**: 绝不要包含错误消息或技术错误。只保留真正有用的信息。

精炼后的回答:"""
        }

        return prompts.get(language, prompts["en"])

    def _apply_citations(self, final_response: str, state: AgentState) -> str:
        """검색 결과에 대한 citation reference list를 응답에 추가합니다."""
        try:
            from neos.utils.citations import UniversalCitationTracker

            style = state.get("citation_style") or settings.CITATION_DEFAULT_STYLE
            tracker = UniversalCitationTracker(style=style)

            # SearchResult 객체에서 소스 정보 추출
            sources = []
            for result in state["search_results"]:
                url = getattr(result, "url", "") or ""
                title = getattr(result, "title", "") or ""
                if url and title:
                    sources.append({
                        "url": url,
                        "title": title,
                        "content": getattr(result, "content", "") or "",
                        "author": getattr(result, "author", None),
                        "published_date": getattr(result, "published_date", None),
                        "score": getattr(result, "score", 0.0),
                    })

            if not sources:
                return final_response

            tracker.register_sources(sources)

            if tracker.has_sources:
                only_cited = state.get("citation_only_cited", True)
                references = tracker.generate_reference_list(only_cited=only_cited)
                if references:
                    final_response = final_response + "\n\n---\n" + references

        except Exception as e:
            logger.debug(f"[ResponseGenerator] Citation application failed: {e}")

        return final_response

    def get_response_stats(self, state: AgentState) -> Dict[str, Any]:
        """응답 생성 통계"""
        final_response = state.get("final_response", "")
        metadata = state.get("response_metadata", {})

        return {
            "response_length": len(final_response),
            "word_count": len(final_response.split()) if final_response else 0,
            "execution_time_ms": metadata.get("execution_time_ms", 0),
            "total_sources": metadata.get("total_sources", 0),
            "quality_score": metadata.get("quality_score", 0.0),
            "has_search_results": metadata.get("total_sources", 0) > 0,
            "has_analysis": metadata.get("analysis_count", 0) > 0,
            "has_generation": metadata.get("generation_count", 0) > 0
        }
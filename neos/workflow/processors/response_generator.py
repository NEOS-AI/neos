"""응답 생성 모듈"""

from typing import Dict, Any, List
from datetime import datetime
from urllib.parse import urlparse

from ..state import AgentState


class ResponseGenerator:
    """최종 응답 생성"""

    def __init__(self):
        pass

    async def generate_response(self, state: AgentState) -> Dict[str, Any]:
        """최종 응답 생성"""
        print("[DEBUG] Starting response generation...")

        # 모든 결과를 종합하여 응답 생성
        response_parts = []

        # 검색 결과 요약
        if state["search_results"] and len(state["search_results"]) > 0:
            print(f"[DEBUG] Generating search summary from {len(state['search_results'])} results")
            search_summary = self._create_search_summary(state["search_results"])
            if search_summary and "검색된 고유한 결과가 없습니다" not in search_summary:
                response_parts.append(search_summary)
            else:
                print("[DEBUG] No unique search results found, skipping search summary")

        # 분석 결과 요약
        if state["analysis_results"] and len(state["analysis_results"]) > 0:
            print(f"[DEBUG] Generating analysis summary from {len(state['analysis_results'])} results")
            analysis_summary = self._create_analysis_summary(state["analysis_results"])
            if analysis_summary:
                response_parts.append(analysis_summary)

        # 생성 결과 요약
        if state["generation_results"] and len(state["generation_results"]) > 0:
            print(f"[DEBUG] Generating generation summary from {len(state['generation_results'])} results")
            generation_summary = self._create_generation_summary(state["generation_results"])
            if generation_summary:
                response_parts.append(generation_summary)

        # 최종 응답 구성 (언어 정보 전달)
        detected_language = state.get("detected_language", "ko")
        final_response = self._construct_final_response(response_parts, detected_language)

        # 실행 시간 계산
        execution_time = int((datetime.utcnow() - state["execution_start"]).total_seconds() * 1000)

        # 상태 업데이트
        state["final_response"] = final_response
        state["execution_time_ms"] = execution_time
        state["response_metadata"] = self._create_response_metadata(state)

        print(f"[DEBUG] Response generation completed. Length: {len(final_response)} characters")

        state["execution_steps"].append({
            "step": "response_generation",
            "result": "completed",
            "timestamp": datetime.utcnow().isoformat()
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

        print(f"[DEBUG] Creating analysis summary from {len(results)} results: ", results)
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
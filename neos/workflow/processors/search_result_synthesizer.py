"""검색 결과 종합 및 필터링 모듈 (LLM 기반)

Phase 2: LLM을 사용하여 부분 성공 케이스를 처리하고,
성공한 검색 결과만으로 의미 있는 응답을 생성합니다.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from langchain_core.messages import HumanMessage

from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm, extract_text_from_response
from neos.workflow.state import SearchResult
from neos.utils.logger import get_logger

logger = get_logger(__name__)


class SearchResultSynthesizer:
    """LLM 기반 검색 결과 종합 및 필터링"""

    def __init__(self):
        self.name = "search_result_synthesizer"

    async def synthesize_search_results(
        self,
        query: str,
        search_results: List[SearchResult],
        agent_errors: List[str],
        detected_language: str = "ko",
        session_id: str = "",
        user_id: str = ""
    ) -> Dict[str, Any]:
        """
        부분 성공 케이스 처리:
        1. 유효한 결과 필터링
        2. LLM으로 관련성 평가 및 종합
        3. 메타데이터 생성

        Args:
            query: 사용자 쿼리
            search_results: 검색 결과 리스트 (일부는 유효하지 않을 수 있음)
            agent_errors: 발생한 에러 리스트
            detected_language: 감지된 언어
            session_id: 세션 ID
            user_id: 사용자 ID

        Returns:
            종합된 결과 딕셔너리
        """
        logger.info(f"[SearchResultSynthesizer] Starting synthesis for query: {query[:50]}...")
        logger.info(f"[SearchResultSynthesizer] Total search results: {len(search_results)}, Errors: {len(agent_errors)}")

        # Phase 1: 유효한 결과 필터링
        valid_results = self._filter_valid_results(search_results)
        logger.info(f"[SearchResultSynthesizer] Valid results after filtering: {len(valid_results)}")

        # 모든 검색 실패 시
        if not valid_results:
            logger.warning("[SearchResultSynthesizer] No valid results found")
            return {
                "success": False,
                "results": [],
                "synthesis": None,  # 종합 요약 없음
                "sources_checked": len(search_results) + len(agent_errors),
                "sources_succeeded": 0,
                "partial_success": False,
                "synthesis_performed": False
            }

        # Phase 2: LLM 기반 관련성 평가 및 종합 (선택적)
        # 성능 최적화: 결과가 충분히 많으면 LLM 종합 생략
        synthesis = None
        synthesis_performed = False

        if len(valid_results) >= 3:
            # 충분한 결과가 있으면 LLM으로 종합
            try:
                synthesis = await self._llm_synthesize_results(
                    query=query,
                    results=valid_results,
                    language=detected_language,
                    session_id=session_id,
                    user_id=user_id
                )
                synthesis_performed = True
                logger.info("[SearchResultSynthesizer] LLM synthesis completed successfully")
            except Exception as e:
                logger.error(f"[SearchResultSynthesizer] LLM synthesis failed: {e}")
                synthesis = None
                synthesis_performed = False

        return {
            "success": True,
            "results": valid_results,
            "synthesis": synthesis,  # LLM으로 생성된 종합 요약 (있는 경우)
            "sources_checked": len(search_results) + len(agent_errors),
            "sources_succeeded": len(valid_results),
            "partial_success": len(agent_errors) > 0,  # 일부 에이전트 실패 여부
            "synthesis_performed": synthesis_performed
        }

    def _filter_valid_results(
        self,
        search_results: List[SearchResult]
    ) -> List[SearchResult]:
        """유효한 검색 결과만 필터링

        필터링 기준:
        1. 에러 메시지 패턴 제외
        2. 충분한 콘텐츠가 있는 결과만 포함
        3. 중복 제거
        """
        valid = []
        seen_content = set()

        for result in search_results:
            # 에러 메시지 패턴 필터링
            if self._is_error_message(result):
                logger.debug(f"[SearchResultSynthesizer] Filtered out error message: {result.title[:50]}")
                continue

            # 유효한 콘텐츠 확인 (최소 20자)
            if not result.content or len(result.content.strip()) < 20:
                logger.debug(f"[SearchResultSynthesizer] Filtered out short content: {result.title[:50]}")
                continue

            # 중복 제거 (제목 + 콘텐츠 일부로 해시)
            content_hash = hash(result.title + result.content[:200])
            if content_hash in seen_content:
                logger.debug(f"[SearchResultSynthesizer] Filtered out duplicate: {result.title[:50]}")
                continue

            seen_content.add(content_hash)
            valid.append(result)

        return valid

    def _is_error_message(self, result: SearchResult) -> bool:
        """에러 메시지 패턴 감지

        다국어 에러 패턴 감지:
        - 한국어: "검색 결과 없음", "검색된 결과가 없습니다", "요약 실패"
        - 영어: "No results found", "Failed to"
        - 일본어: "結果が見つかりません", "失敗しました"
        - 중국어: "未找到结果", "失败"
        """
        error_patterns = [
            # 한국어
            "검색 결과 없음",
            "검색된 결과가 없습니다",
            "결과를 찾지 못했습니다",
            "요약 실패",
            "요약 생성 실패",
            "시간 초과",

            # 영어
            "no results found",
            "failed to",
            "timed out",
            "error",

            # 일본어
            "結果が見つかりません",
            "失敗しました",
            "タイムアウト",

            # 중국어
            "未找到结果",
            "失败",
            "超时"
        ]

        content = (result.title + " " + result.content).lower()
        return any(pattern.lower() in content for pattern in error_patterns)

    async def _llm_synthesize_results(
        self,
        query: str,
        results: List[SearchResult],
        language: str,
        session_id: str = "",
        user_id: str = ""
    ) -> str:
        """LLM을 사용하여 검색 결과 종합

        Args:
            query: 사용자 쿼리
            results: 유효한 검색 결과
            language: 응답 언어
            session_id: 세션 ID
            user_id: 사용자 ID

        Returns:
            LLM이 생성한 종합 요약
        """
        # 검색 결과를 LLM에 전달할 형식으로 포맷
        results_context = self._format_results_for_llm(results)

        # 언어별 프롬프트 생성
        prompt = self._get_synthesis_prompt(query, results_context, language)

        # LLM 호출
        base_llm = create_llm(temperature=0.3, max_tokens=4000)

        llm = create_tracked_llm(
            llm=base_llm,
            session_id=session_id,
            user_id=user_id,
            workflow_step="search_synthesis",
            agent_name=self.name,
            tags=["search_result_synthesis", f"language:{language}"],
            custom_metadata={
                "query": query,
                "num_results": len(results),
                "purpose": "synthesize_search_results"
            }
        )

        response = await llm.ainvoke([HumanMessage(content=prompt)])
        synthesis = extract_text_from_response(response).strip()

        return synthesis

    def _format_results_for_llm(self, results: List[SearchResult]) -> str:
        """검색 결과를 LLM이 이해하기 쉬운 형식으로 포맷"""
        formatted = []

        for i, result in enumerate(results[:10], 1):  # 최대 10개 결과만 사용
            formatted.append(f"""
=== 검색 결과 {i} ===
출처: {result.source}
제목: {result.title}
URL: {result.url or 'N/A'}
점수: {result.score:.2f}
내용:
{result.content[:800]}  # 각 결과당 최대 800자
""")

        return "\n".join(formatted)

    def _get_synthesis_prompt(self, query: str, results_context: str, language: str) -> str:
        """언어별 종합 프롬프트 생성"""
        prompts = {
            "ko": f"""다음은 사용자 질문에 대한 여러 검색 결과입니다.

사용자 질문: {query}

검색 결과:
{results_context}

위 검색 결과들을 종합하여 다음 작업을 수행하세요:

1. **중복 제거**: 여러 결과에서 반복되는 정보는 한 번만 언급
2. **핵심 정보 추출**: 사용자 질문과 가장 관련성 높은 정보 위주로 정리
3. **출처 명시**: 중요한 정보는 어느 출처에서 왔는지 명시
4. **일관성 있는 구조화**: 읽기 쉽고 논리적인 순서로 정리

**중요**: "검색 결과 없음", "요약 실패" 등의 에러 메시지는 절대 포함하지 마세요.

종합 요약:""",

            "en": f"""Here are multiple search results for the user's question.

User Question: {query}

Search Results:
{results_context}

Please synthesize the search results above by performing the following tasks:

1. **Remove Duplicates**: Mention repeated information only once
2. **Extract Key Information**: Focus on information most relevant to the user's question
3. **Cite Sources**: Specify which source important information came from
4. **Structured Coherently**: Organize in a readable and logical order

**Important**: Never include error messages like "No results found" or "Failed to summarize".

Synthesis:""",

            "ja": f"""以下は、ユーザーの質問に対する複数の検索結果です。

ユーザーの質問: {query}

検索結果:
{results_context}

上記の検索結果を統合して、以下のタスクを実行してください:

1. **重複の削除**: 複数の結果で繰り返される情報は一度だけ言及
2. **主要情報の抽出**: ユーザーの質問に最も関連性の高い情報を中心に整理
3. **出典の明示**: 重要な情報がどの出典から来たかを明示
4. **一貫した構造化**: 読みやすく論理的な順序で整理

**重要**: 「結果が見つかりません」「要約失敗」などのエラーメッセージは絶対に含めないでください。

統合要約:""",

            "zh": f"""以下是用户问题的多个搜索结果。

用户问题: {query}

搜索结果:
{results_context}

请综合以上搜索结果，执行以下任务:

1. **去除重复**: 多个结果中重复的信息只提及一次
2. **提取关键信息**: 重点整理与用户问题最相关的信息
3. **标明来源**: 重要信息应标明来自哪个来源
4. **连贯结构化**: 以易读且符合逻辑的顺序整理

**重要**: 绝不要包含"未找到结果"、"摘要失败"等错误消息。

综合摘要:"""
        }

        return prompts.get(language, prompts["en"])

    def _get_no_results_message(self, language: str) -> str:
        """검색 결과가 전혀 없을 때의 메시지"""
        messages = {
            "ko": "죄송합니다. 요청하신 주제에 대한 검색 결과를 찾지 못했습니다. 다른 키워드로 다시 시도해 보시기 바랍니다.",
            "en": "Sorry, we couldn't find any search results for the requested topic. Please try again with different keywords.",
            "ja": "申し訳ございません。お探しのトピックに関する検索結果が見つかりませんでした。別のキーワードで再度お試しください。",
            "zh": "抱歉，我们未能找到有关所请求主题的搜索结果。请尝试使用不同的关键词重新搜索。"
        }
        return messages.get(language, messages["en"])

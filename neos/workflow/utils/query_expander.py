"""RAG Query Expansion (Phase 2.9)

검색 전 LLM으로 쿼리 변형 2-3개를 생성하여 검색 recall을 향상합니다.
각 변형으로 검색 후 결과를 병합하고 중복을 제거합니다.
"""

import logging
from typing import Dict, Any, List

from neos.config.settings import settings

logger = logging.getLogger(__name__)


class QueryExpander:
    """쿼리 변형 생성 및 결과 병합

    - 동의어 및 재표현
    - 다른 관점에서의 질문
    - 보다 구체적인 하위 쿼리
    """

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from neos.utils.llm_factory import create_llm

            model = getattr(settings, "QUERY_CLASSIFIER_LLM_MODEL", "claude-haiku-4-5-20251001")
            if "claude" in model or "haiku" in model:
                provider = "anthropic"
            elif "gemini" in model:
                provider = "gemini"
            else:
                provider = "openai"

            self._llm = create_llm(
                provider=provider,
                model=model,
                temperature=0.3,
                max_tokens=300,
                request_timeout=10,
            )
        return self._llm

    async def expand(
        self,
        query: str,
        classification: Dict[str, Any] = None,
        num_variations: int = None,
    ) -> List[str]:
        """쿼리 변형 생성

        Args:
            query: 원본 쿼리
            classification: 쿼리 분류 결과 (sub_topics 활용)
            num_variations: 생성할 변형 수 (기본: settings에서)

        Returns:
            [원본 쿼리, 변형1, 변형2, ...] 리스트
        """
        if not getattr(settings, "QUERY_EXPANSION_ENABLED", False):
            return [query]

        n = num_variations or getattr(settings, "QUERY_EXPANSION_VARIATIONS", 3)

        try:
            llm = self._get_llm()

            sub_topics_hint = ""
            if classification and classification.get("sub_topics"):
                sub_topics_hint = f"\nSub-topics identified: {', '.join(classification['sub_topics'][:5])}"

            prompt = f"""Generate {n - 1} alternative search queries for the following query.
Each variation should approach the topic from a different angle or use different keywords.

Original query: {query}{sub_topics_hint}

Return ONLY the alternative queries, one per line (without numbering or bullets):"""

            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            variations = [query]  # 원본 항상 포함
            for line in content.strip().split("\n"):
                line = line.strip().lstrip("0123456789.-) ")
                if line and line != query and len(line) > 5:
                    variations.append(line)

            # 최대 n개로 제한
            result = variations[:n]
            logger.info(f"Query expanded: {len(result)} variations (from '{query[:50]}')")
            return result

        except Exception as e:
            logger.warning(f"Query expansion failed: {e}")
            return [query]

    @staticmethod
    def merge_results(results_per_query: List[List], original_query: str = "") -> List:
        """여러 쿼리 변형의 검색 결과를 병합하고 중복 제거

        - URL 기반 중복 제거
        - 여러 변형에서 발견된 결과에 점수 boost
        """
        seen_urls = {}
        merged = []

        for query_results in results_per_query:
            for result in query_results:
                url = getattr(result, "url", None) or ""
                title = getattr(result, "title", "") or ""
                key = url if url else title

                if not key:
                    merged.append(result)
                    continue

                if key in seen_urls:
                    # 이미 본 결과: 점수 boost (다중 쿼리에서 발견됨 = 더 관련성 높음)
                    existing = seen_urls[key]
                    existing_score = getattr(existing, "score", 0.0)
                    new_score = getattr(result, "score", 0.0)
                    if new_score > existing_score:
                        existing.score = new_score
                    existing.score = min(existing.score * 1.1, 1.0)  # 10% boost
                else:
                    seen_urls[key] = result
                    merged.append(result)

        # 점수순 정렬
        merged.sort(key=lambda x: getattr(x, "score", 0.0), reverse=True)
        return merged


# 전역 인스턴스
query_expander = QueryExpander()

"""Search Quality Evaluator - 검색 결과 품질 평가

평가 기준:
1. 정보 완전성 (40% 가중치) - LLM 기반 쿼리 측면 분해 및 커버리지 평가
2. 신뢰도 (30% 가중치) - 도메인 권위, 메타데이터 완전성
3. 출처 다양성 (30% 가중치) - 고유 도메인, 단일 출처 집중도
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from urllib.parse import urlparse
from collections import Counter
import asyncio
import json
import re
import logging

from neos.workflow.state import SearchResult
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm
from neos.utils.cache import cache_manager
from neos.config.settings import settings
from langchain_core.messages import HumanMessage
from langchain_core.language_models.base import BaseLanguageModel

logger = logging.getLogger(__name__)


# ============================================================================
# 데이터 구조
# ============================================================================

@dataclass
class CompletenessResult:
    """완전성 평가 결과"""
    score: float  # 0.0-1.0
    aspects: List[Dict[str, str]] = field(default_factory=list)  # 쿼리 측면별 커버리지
    gaps: List[str] = field(default_factory=list)  # 누락된 정보
    reasoning: str = ""


@dataclass
class CredibilityResult:
    """신뢰도 평가 결과"""
    score: float  # 0.0-1.0
    source_scores: List[float] = field(default_factory=list)  # 각 소스의 신뢰도
    high_credibility_count: int = 0  # 높은 신뢰도 소스 수


@dataclass
class DiversityResult:
    """다양성 평가 결과"""
    score: float  # 0.0-1.0
    unique_domains: int = 0
    total_sources: int = 0
    domain_distribution: Dict[str, int] = field(default_factory=dict)


@dataclass
class QualityMetrics:
    """종합 품질 메트릭"""
    completeness_score: float  # 0.0-1.0
    credibility_score: float   # 0.0-1.0
    diversity_score: float     # 0.0-1.0
    overall_score: float       # 가중 평균
    gaps_identified: List[str] = field(default_factory=list)
    needs_more_exploration: bool = True
    evaluation_details: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# SearchQualityEvaluator
# ============================================================================

class SearchQualityEvaluator:
    """검색 결과 품질 평가기

    평가 차원:
    1. 완전성: 쿼리의 모든 측면이 답변되었는가
    2. 신뢰도: 출처가 신뢰할 수 있는가
    3. 다양성: 다양한 독립적 출처에서 정보를 수집했는가
    """

    def __init__(
        self,
        llm: Optional[BaseLanguageModel] = None,
        session_id: str = "",
        user_id: str = ""
    ):
        """초기화

        Args:
            llm: LLM 인스턴스 (None이면 자동 생성)
            session_id: 세션 ID (추적용)
            user_id: 사용자 ID (추적용)
        """
        self.base_llm = llm or create_llm(temperature=0.1, max_tokens=4000)
        self.session_id = session_id
        self.user_id = user_id

        # 가중치 (설정값 사용)
        self.completeness_weight = settings.QUALITY_EVALUATOR_COMPLETENESS_WEIGHT
        self.credibility_weight = settings.QUALITY_EVALUATOR_CREDIBILITY_WEIGHT
        self.diversity_weight = settings.QUALITY_EVALUATOR_DIVERSITY_WEIGHT

        logger.info("[QualityEvaluator] Initialized")

    async def evaluate_quality(
        self,
        query: str,
        results: List[SearchResult],
        context: Dict[str, Any] = None
    ) -> QualityMetrics:
        """종합 품질 평가

        Args:
            query: 검색 쿼리
            results: 검색 결과 리스트
            context: 추가 컨텍스트

        Returns:
            QualityMetrics
        """
        context = context or {}

        if not results:
            return QualityMetrics(
                completeness_score=0.0,
                credibility_score=0.0,
                diversity_score=0.0,
                overall_score=0.0,
                gaps_identified=["No results found"],
                needs_more_exploration=True
            )

        logger.info(f"[QualityEvaluator] Evaluating {len(results)} results for query: {query[:100]}")

        # 빠른 휴리스틱 평가 먼저
        credibility_result = await self._evaluate_credibility(results)
        diversity_result = await self._evaluate_diversity(results)

        # 조기 종료: 명백히 불충분한 경우 LLM 호출 스킵
        early_threshold = settings.QUALITY_EVALUATOR_EARLY_TERMINATION_THRESHOLD
        if credibility_result.score < early_threshold or diversity_result.score < early_threshold:
            logger.info(f"[QualityEvaluator] Early termination - low quality (credibility={credibility_result.score:.2f}, diversity={diversity_result.score:.2f})")

            overall = (
                0.0 * self.completeness_weight +
                credibility_result.score * self.credibility_weight +
                diversity_result.score * self.diversity_weight
            )

            return QualityMetrics(
                completeness_score=0.0,
                credibility_score=credibility_result.score,
                diversity_score=diversity_result.score,
                overall_score=overall,
                gaps_identified=["Insufficient source quality or diversity"],
                needs_more_exploration=True,
                evaluation_details={
                    "early_termination": True,
                    "reason": "low_credibility_or_diversity"
                }
            )

        # LLM 기반 완전성 평가 (캐싱)
        completeness_result = await self._evaluate_completeness_cached(
            query, results, context
        )

        # 전체 점수 계산
        overall = (
            completeness_result.score * self.completeness_weight +
            credibility_result.score * self.credibility_weight +
            diversity_result.score * self.diversity_weight
        )

        quality_threshold = context.get("quality_threshold", 0.75)
        needs_more = overall < quality_threshold

        logger.info(f"[QualityEvaluator] Scores - Overall: {overall:.2f}, "
                   f"Completeness: {completeness_result.score:.2f}, "
                   f"Credibility: {credibility_result.score:.2f}, "
                   f"Diversity: {diversity_result.score:.2f}")

        return QualityMetrics(
            completeness_score=completeness_result.score,
            credibility_score=credibility_result.score,
            diversity_score=diversity_result.score,
            overall_score=overall,
            gaps_identified=completeness_result.gaps,
            needs_more_exploration=needs_more,
            evaluation_details={
                "completeness_aspects": completeness_result.aspects,
                "completeness_reasoning": completeness_result.reasoning,
                "high_credibility_sources": credibility_result.high_credibility_count,
                "unique_domains": diversity_result.unique_domains,
                "domain_distribution": diversity_result.domain_distribution
            }
        )

    async def _evaluate_completeness_cached(
        self,
        query: str,
        results: List[SearchResult],
        context: Dict[str, Any]
    ) -> CompletenessResult:
        """캐시를 활용한 완전성 평가

        Args:
            query: 검색 쿼리
            results: 검색 결과
            context: 컨텍스트

        Returns:
            CompletenessResult
        """
        # 캐시 키 생성 (쿼리 + 상위 5개 URL)
        top_urls = [r.url for r in results[:5] if r.url]
        cache_key = cache_manager.make_key(
            "completeness_eval",
            hash(query.lower().strip()),
            hash(str(top_urls))
        )

        # 캐시 확인
        cached = await cache_manager.get(cache_key, deserialize="json")
        if cached:
            logger.info("[QualityEvaluator] Cache hit for completeness evaluation")
            return CompletenessResult(**cached)

        # LLM 평가 (캐시 미스)
        completeness = await self._evaluate_completeness(query, results, context)

        # 캐싱 (설정값 사용)
        from dataclasses import asdict
        await cache_manager.set(
            cache_key,
            asdict(completeness),
            ttl=settings.ITERATIVE_EXPLORER_COMPLETENESS_CACHE_TTL,
            serialize="json"
        )

        return completeness

    async def _evaluate_completeness(
        self,
        query: str,
        results: List[SearchResult],
        context: Dict[str, Any]
    ) -> CompletenessResult:
        """LLM 기반 완전성 평가

        쿼리를 핵심 측면으로 분해하고 각 측면의 커버리지를 평가

        Args:
            query: 검색 쿼리
            results: 검색 결과
            context: 컨텍스트

        Returns:
            CompletenessResult
        """
        try:
            # 추적 가능한 LLM 생성
            llm = create_tracked_llm(
                llm=self.base_llm,
                session_id=self.session_id,
                user_id=self.user_id,
                workflow_step="quality_evaluation_completeness",
                agent_name="quality_evaluator",
                tags=["completeness", "quality"]
            )

            # 결과 요약 (토큰 절약)
            results_summary = self._summarize_results(results)

            # 프롬프트 생성
            prompt = f"""You are a research quality evaluator. Analyze if the search results adequately cover the user's query.

Query: {query}

Search Results Summary:
{results_summary}

Tasks:
1. Identify 3-5 key aspects/questions in the query
2. For each aspect, rate coverage: FULL, PARTIAL, or MISSING
3. Identify specific information gaps
4. Provide completeness score (0.0-1.0)

Output JSON format:
{{
    "query_aspects": [
        {{"aspect": "aspect description", "coverage": "FULL/PARTIAL/MISSING", "notes": "brief explanation"}}
    ],
    "gaps": ["gap1", "gap2"],
    "completeness_score": 0.0-1.0,
    "reasoning": "brief reasoning for the score"
}}

Respond with ONLY the JSON, no additional text."""

            # LLM 호출
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            response_text = response.content.strip()

            # JSON 추출 (견고한 파싱)
            result_data = self._extract_json_from_response(response_text)

            if not result_data:
                logger.error(f"[QualityEvaluator] Failed to extract JSON from response")
                return self._completeness_fallback(results)

            return CompletenessResult(
                score=float(result_data.get("completeness_score", 0.5)),
                aspects=result_data.get("query_aspects", []),
                gaps=result_data.get("gaps", []),
                reasoning=result_data.get("reasoning", "")
            )

        except json.JSONDecodeError as e:
            logger.error(f"[QualityEvaluator] JSON parsing error: {e}")
            # 폴백: 간단한 휴리스틱
            return self._completeness_fallback(results)

        except Exception as e:
            logger.error(f"[QualityEvaluator] Completeness evaluation error: {e}")
            return self._completeness_fallback(results)

    def _completeness_fallback(self, results: List[SearchResult]) -> CompletenessResult:
        """완전성 평가 폴백 (LLM 실패 시)"""
        result_count = len(results)
        score = min(result_count / 15.0, 1.0)  # 15개 이상이면 1.0

        return CompletenessResult(
            score=score,
            aspects=[],
            gaps=["LLM evaluation unavailable"],
            reasoning="Fallback: based on result count"
        )

    def _extract_json_from_response(self, response_text: str) -> Optional[Dict[str, Any]]:
        """LLM 응답에서 JSON 추출 (견고한 파싱)

        시도 순서:
        1. 코드 블록 내 JSON 찾기 (```json ... ``` 또는 ``` ... ```)
        2. 첫 번째 { ... } 객체 찾기
        3. 전체 텍스트를 JSON으로 파싱

        Args:
            response_text: LLM 응답 텍스트

        Returns:
            파싱된 JSON dict 또는 None
        """
        # 1. 코드 블록 내 JSON 찾기
        # Pattern: ```json\n{...}\n``` or ```\n{...}\n```
        code_block_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
        match = re.search(code_block_pattern, response_text, re.DOTALL)

        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError as e:
                logger.warning(f"[QualityEvaluator] Code block JSON parse error: {e}")

        # 2. 첫 번째 { ... } 객체 찾기
        json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        match = re.search(json_pattern, response_text, re.DOTALL)

        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as e:
                logger.warning(f"[QualityEvaluator] Extracted JSON parse error: {e}")

        # 3. 전체 텍스트를 JSON으로 파싱 시도
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        # 4. 모든 방법 실패
        logger.error(f"[QualityEvaluator] Could not extract JSON from response: {response_text[:200]}")
        return None

    async def _evaluate_credibility(
        self,
        results: List[SearchResult]
    ) -> CredibilityResult:
        """휴리스틱 기반 신뢰도 평가

        평가 요소:
        - 도메인 권위 (.edu, .gov, .org 등)
        - 메타데이터 완전성 (저자, 날짜, 인용)
        - 콘텐츠 품질 지표

        Args:
            results: 검색 결과

        Returns:
            CredibilityResult
        """
        credibility_scores = []

        for result in results:
            score = 0.0

            # 1. 도메인 권위
            domain = urlparse(result.url).netloc.lower() if result.url else ""

            # 고신뢰 도메인
            if any(trusted in domain for trusted in [
                '.edu', '.gov', '.org',
                'wikipedia.org', 'reuters.com', 'bbc.com', 'nature.com',
                'arxiv.org', 'scholar.google', 'sciencedirect.com'
            ]):
                score += 0.4
            # 일반 신뢰 도메인
            elif any(reliable in domain for reliable in [
                '.com', '.net', 'medium.com', 'forbes.com', 'techcrunch.com'
            ]):
                score += 0.2

            # 2. 메타데이터 완전성
            if result.metadata:
                if result.metadata.get("author"):
                    score += 0.15
                if result.metadata.get("publish_date") or result.metadata.get("published_date"):
                    score += 0.1
                if result.metadata.get("citations") or result.metadata.get("references"):
                    score += 0.15

            # 3. 콘텐츠 품질 지표
            content = (result.content or "").lower()
            if any(indicator in content for indicator in [
                'study', 'research', 'according to', 'source:', 'reference',
                'published in', 'doi:', 'isbn:'
            ]):
                score += 0.1

            # 4. 제목 품질
            title = (result.title or "").lower()
            if len(title) > 20 and not any(spam in title for spam in ['click', 'buy', 'sale']):
                score += 0.1

            credibility_scores.append(min(score, 1.0))

        # 평균 신뢰도
        avg_credibility = sum(credibility_scores) / len(credibility_scores) if credibility_scores else 0.0

        # 높은 신뢰도 소스 수 (설정값 사용)
        high_cred_threshold = settings.QUALITY_EVALUATOR_HIGH_CREDIBILITY_THRESHOLD
        high_cred_count = sum(1 for s in credibility_scores if s > high_cred_threshold)

        return CredibilityResult(
            score=avg_credibility,
            source_scores=credibility_scores,
            high_credibility_count=high_cred_count
        )

    async def _evaluate_diversity(
        self,
        results: List[SearchResult]
    ) -> DiversityResult:
        """수학적 다양성 평가

        평가 요소:
        - 고유 도메인 수
        - 도메인 분포 (단일 출처 집중도)

        Args:
            results: 검색 결과

        Returns:
            DiversityResult
        """
        # 도메인 추출
        domains = []
        for result in results:
            if result.url:
                domain = urlparse(result.url).netloc
                if domain:
                    domains.append(domain)

        total_results = len(results)
        unique_domains = len(set(domains))

        # 다양성 점수 계산
        if total_results == 0:
            diversity_score = 0.0
        elif total_results == 1:
            diversity_score = 0.3  # 하나의 결과만 있으면 낮은 점수
        else:
            # 이상적: 각 결과가 다른 도메인
            diversity_score = min(unique_domains / total_results, 1.0)

        # 단일 출처 집중도 페널티
        domain_counts = Counter(domains)
        if domain_counts:
            max_domain_count = max(domain_counts.values())
            dominance_ratio = max_domain_count / total_results

            # 설정값 이상이 하나의 도메인에서 온 경우 페널티
            dominance_threshold = settings.QUALITY_EVALUATOR_DOMINANCE_THRESHOLD
            if dominance_ratio > dominance_threshold:
                penalty = (dominance_ratio - dominance_threshold) * 0.4  # 최대 0.2 페널티
                diversity_score = max(diversity_score - penalty, 0.0)

        return DiversityResult(
            score=diversity_score,
            unique_domains=unique_domains,
            total_sources=total_results,
            domain_distribution=dict(domain_counts)
        )

    def _summarize_results(self, results: List[SearchResult], max_results: int = 10) -> str:
        """결과 요약 (토큰 절약)

        Args:
            results: 검색 결과
            max_results: 최대 결과 수

        Returns:
            요약 텍스트
        """
        summary_parts = []

        for i, result in enumerate(results[:max_results], 1):
            # 콘텐츠 요약 (최대 200자)
            content_preview = (result.content or "")[:200]
            if len(result.content or "") > 200:
                content_preview += "..."

            summary_parts.append(f"""
Result {i}:
- Title: {result.title or 'Untitled'}
- URL: {result.url or 'N/A'}
- Content preview: {content_preview}
""")

        return "\n".join(summary_parts)

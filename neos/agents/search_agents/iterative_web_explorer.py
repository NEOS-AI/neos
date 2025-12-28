"""Iterative Web Explorer Agent - 반복적 웹 탐색 에이전트

인간처럼 웹을 탐색하는 에이전트:
- 검색 결과를 상위부터 확인
- 페이지 내 링크를 추출하고 관련성 평가
- 품질이 충분할 때까지 반복적으로 탐색
"""

from typing import Dict, Any, List, Set, Optional, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse, urljoin
import asyncio
import aiohttp
from bs4 import BeautifulSoup
import logging
import time

from neos.agents.base import SearchAgent
from neos.workflow.state import SearchResult
from neos.config.settings import settings
from neos.utils.cache import cache_manager
from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm
from langchain_core.messages import HumanMessage

# Lazy import to avoid circular dependency
if TYPE_CHECKING:
    from .quality_evaluator import SearchQualityEvaluator, QualityMetrics

logger = logging.getLogger(__name__)


# ============================================================================
# 데이터 구조
# ============================================================================

@dataclass
class LinkCandidate:
    """탐색할 링크 후보"""
    url: str
    source_url: str
    anchor_text: str
    context: str  # 주변 텍스트
    relevance_score: float
    depth: int


@dataclass
class ExplorationState:
    """탐색 상태 추적"""
    current_depth: int = 0
    pages_visited: int = 0
    visited_urls: Set[str] = field(default_factory=set)
    pending_links: List[LinkCandidate] = field(default_factory=list)
    collected_sources: List[SearchResult] = field(default_factory=list)
    quality_metrics: Optional["QualityMetrics"] = None  # Forward reference for lazy import
    domain_diversity: Set[str] = field(default_factory=set)
    iteration_count: int = 0


# ============================================================================
# IterativeWebExplorerAgent
# ============================================================================

class IterativeWebExplorerAgent(SearchAgent):
    """반복적 웹 탐색 에이전트

    Features:
    - Progressive link exploration (max depth: 5, max pages: 20)
    - Quality evaluation at each iteration
    - Intelligent link prioritization
    - Source diversity tracking
    """

    def __init__(self):
        super().__init__(
            name="iterative_web_explorer",
            search_type="iterative_web_exploration",
            role="Iterative Web Explorer",
            goal="Explore web progressively following links until quality threshold is met",
            backstory="You specialize in thorough web research by following relevant links iteratively."
        )

        # 설정
        self.max_depth = settings.ITERATIVE_EXPLORER_MAX_DEPTH
        self.max_pages = settings.ITERATIVE_EXPLORER_MAX_PAGES
        self.min_quality = settings.ITERATIVE_EXPLORER_MIN_QUALITY
        self.max_concurrent = settings.ITERATIVE_EXPLORER_CONCURRENT_FETCHES

        # HTTP 클라이언트 (세션별로 생성)
        self.session = None

        # 품질 평가기 (세션별로 생성)
        self.quality_evaluator = None

        # STEP 5: Domain-level rate limiting
        self.domain_last_request_time: Dict[str, float] = {}
        self.min_request_interval = 1.0  # 같은 도메인에 최소 1초 간격

        logger.info(f"[{self.name}] Initialized with max_depth={self.max_depth}, max_pages={self.max_pages}")

    async def execute(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """메인 실행 루프

        Args:
            query: 검색 쿼리
            context: 실행 컨텍스트

        Returns:
            실행 결과 (SearchResult 리스트 포함)
        """
        if not self.validate_input(query, context):
            return {"success": False, "error": "Invalid input", "agent": self.name}

        logger.info(f"[{self.name}] Starting iterative exploration for: {query[:100]}")

        # 컨텍스트에서 메타정보 추출
        session_id = context.get("session_id", "") if context else ""
        user_id = context.get("user_id", "") if context else ""
        detected_language = context.get("detected_language", "ko") if context else "ko"

        # 설정 오버라이드 (컨텍스트에서)
        max_depth = context.get("max_depth", self.max_depth) if context else self.max_depth
        max_pages = context.get("max_pages", self.max_pages) if context else self.max_pages
        quality_threshold = context.get("quality_threshold", self.min_quality) if context else self.min_quality

        # 캐시 확인 (STEP 5: Performance Optimization)
        cached_result = await self._check_exploration_cache(
            query, max_depth, max_pages, quality_threshold
        )
        if cached_result:
            logger.info(f"[{self.name}] Cache hit for exploration")
            return cached_result

        try:
            # 품질 평가기 초기화 (lazy import)
            from .quality_evaluator import SearchQualityEvaluator

            self.quality_evaluator = SearchQualityEvaluator(
                session_id=session_id,
                user_id=user_id
            )

            # 탐색 상태 초기화
            state = ExplorationState()

            # 1. 초기 검색 (시드 URL)
            logger.info(f"[{self.name}] Phase 1: Initial search")
            initial_results = await self._perform_initial_search(query, session_id, user_id, detected_language)

            if not initial_results:
                return {"success": False, "error": "No initial results found", "agent": self.name}

            state.collected_sources.extend(initial_results)
            state.pages_visited += len(initial_results)

            # 방문 URL 추적
            for result in initial_results:
                if result.url:
                    state.visited_urls.add(result.url)
                    domain = urlparse(result.url).netloc
                    if domain:
                        state.domain_diversity.add(domain)

            logger.info(f"[{self.name}] Initial search: {len(initial_results)} results, {len(state.domain_diversity)} domains")

            # 2. 반복적 탐색 루프
            while (state.current_depth < max_depth and
                   state.pages_visited < max_pages and
                   state.iteration_count < 10):  # 최대 반복 제한

                state.iteration_count += 1
                logger.info(f"[{self.name}] Iteration {state.iteration_count}: depth={state.current_depth}, pages={state.pages_visited}")

                # 품질 평가 (SearchQualityEvaluator 사용)
                eval_context = {
                    "quality_threshold": quality_threshold,
                    "session_id": session_id,
                    "user_id": user_id
                }
                quality = await self.quality_evaluator.evaluate_quality(
                    query=query,
                    results=state.collected_sources,
                    context=eval_context
                )
                state.quality_metrics = quality

                logger.info(f"[{self.name}] Quality: overall={quality.overall_score:.2f}, "
                           f"completeness={quality.completeness_score:.2f}, "
                           f"credibility={quality.credibility_score:.2f}, "
                           f"diversity={quality.diversity_score:.2f}")

                # 품질이 충분하면 종료
                if quality.overall_score >= quality_threshold:
                    logger.info(f"[{self.name}] Quality threshold met ({quality.overall_score:.2f} >= {quality_threshold})")
                    break

                # 페이지 제한에 가까우면 종료
                if state.pages_visited >= max_pages * 0.9:
                    logger.info(f"[{self.name}] Approaching page limit ({state.pages_visited}/{max_pages})")
                    break

                # 링크 추출 및 우선순위화
                new_links = await self._extract_and_prioritize_links(
                    state.collected_sources[-5:],  # 최근 5개 결과에서만 추출
                    query,
                    state
                )

                if not new_links:
                    logger.info(f"[{self.name}] No more links to explore")
                    break

                # 다음 배치 가져오기
                remaining_pages = max_pages - state.pages_visited
                batch_size = min(len(new_links), remaining_pages, self.max_concurrent)

                logger.info(f"[{self.name}] Fetching {batch_size} links (depth {state.current_depth + 1})")

                new_results = await self._fetch_and_process_links(
                    new_links[:batch_size],
                    query,
                    session_id,
                    user_id,
                    detected_language
                )

                if new_results:
                    state.collected_sources.extend(new_results)
                    state.pages_visited += len(new_results)

                    # URL 추적
                    for result in new_results:
                        if result.url:
                            state.visited_urls.add(result.url)
                            domain = urlparse(result.url).netloc
                            if domain:
                                state.domain_diversity.add(domain)

                    logger.info(f"[{self.name}] Added {len(new_results)} new results")
                else:
                    logger.info(f"[{self.name}] No new results from link fetching")
                    break

                # 깊이 증가
                state.current_depth += 1

            # 3. 최종 결과 반환
            logger.info(f"[{self.name}] Exploration complete: {len(state.collected_sources)} total sources, "
                       f"{len(state.domain_diversity)} domains, {state.iteration_count} iterations")

            metadata = {
                "search_type": "iterative_web_exploration",
                "total_sources": len(state.collected_sources),
                "depth_reached": state.current_depth,
                "pages_visited": state.pages_visited,
                "domain_diversity": len(state.domain_diversity),
                "iterations": state.iteration_count,
                "final_quality_score": state.quality_metrics.overall_score if state.quality_metrics else 0.0
            }

            # 결과 캐싱 (STEP 5: Performance Optimization)
            final_result = self.format_output(state.collected_sources, metadata)
            await self._cache_exploration_results(
                query, max_depth, max_pages, quality_threshold, final_result
            )

            return final_result

        except Exception as e:
            logger.error(f"[{self.name}] Execution failed: {e}", exc_info=True)
            return {"success": False, "error": str(e), "agent": self.name}

    async def _perform_initial_search(
        self,
        query: str,
        session_id: str,
        user_id: str,
        language: str
    ) -> List[SearchResult]:
        """초기 검색 실행 (시드 URL)

        Tavily API를 사용하여 초기 검색 수행
        """
        try:
            # Tavily 검색 (설정에서 API 키 확인)
            if not settings.TAVILY_API_KEY:
                logger.warning(f"[{self.name}] Tavily API key not configured")
                return []

            from tavily import TavilyClient

            client = TavilyClient(api_key=settings.TAVILY_API_KEY)

            # 검색 실행 (timeout 30초)
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.search,
                        query=query,
                        max_results=10,
                        search_depth="advanced"
                    ),
                    timeout=settings.ITERATIVE_EXPLORER_TAVILY_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error(f"[{self.name}] Tavily search timeout for query: {query}")
                return []

            # 결과 변환
            results = []
            for item in response.get("results", []):
                result = SearchResult(
                    source="tavily_initial_search",
                    title=item.get("title", ""),
                    content=item.get("content", ""),
                    url=item.get("url", ""),
                    score=item.get("score", 0.5),
                    metadata={
                        "search_type": "initial",
                        "depth": 0
                    }
                )
                results.append(result)

            return results

        except Exception as e:
            logger.error(f"[{self.name}] Initial search failed: {e}")
            return []

    async def _extract_and_prioritize_links(
        self,
        results: List[SearchResult],
        query: str,
        state: ExplorationState
    ) -> List[LinkCandidate]:
        """결과에서 링크 추출 및 우선순위화

        간단한 휴리스틱 기반 링크 추출
        (추후 Link Following Tool과 통합)
        """
        candidates = []

        for result in results:
            if not result.content or not result.url:
                continue

            # 간단한 링크 추출 (실제로는 Link Following Tool 사용 예정)
            # 여기서는 프로토타입이므로 도메인 기반으로 관련 페이지 추측
            source_domain = urlparse(result.url).netloc

            # 같은 도메인의 하위 페이지를 후보로 추가 (시뮬레이션)
            # 실제 구현에서는 HTML 파싱하여 실제 링크 추출
            potential_paths = ["/about", "/resources", "/documentation", "/blog"]

            for path in potential_paths:
                candidate_url = f"https://{source_domain}{path}"

                # 이미 방문한 URL은 스킵
                if candidate_url in state.visited_urls:
                    continue

                # 같은 도메인이 많으면 다양성을 위해 점수 낮춤
                domain_count = sum(1 for r in state.collected_sources
                                  if r.url and urlparse(r.url).netloc == source_domain)
                diversity_penalty = min(domain_count * 0.1, 0.5)

                candidate = LinkCandidate(
                    url=candidate_url,
                    source_url=result.url,
                    anchor_text=path,
                    context=result.title,
                    relevance_score=0.7 - diversity_penalty,  # 기본 점수
                    depth=state.current_depth + 1
                )
                candidates.append(candidate)

        # 관련성 점수로 정렬
        candidates.sort(key=lambda x: x.relevance_score, reverse=True)

        return candidates[:20]  # 상위 20개만

    async def _fetch_and_process_links(
        self,
        links: List[LinkCandidate],
        query: str,
        session_id: str,
        user_id: str,
        language: str
    ) -> List[SearchResult]:
        """병렬로 링크 fetch 및 처리 (STEP 5: Domain-level rate limiting)"""
        if not links:
            return []

        # Semaphore로 동시 요청 제한
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def fetch_with_limit(link: LinkCandidate):
            async with semaphore:
                try:
                    # STEP 5: Domain-level rate limiting
                    domain = urlparse(link.url).netloc
                    if domain:
                        # 마지막 요청 이후 충분한 시간이 지났는지 확인
                        last_request = self.domain_last_request_time.get(domain, 0)
                        elapsed = time.time() - last_request

                        if elapsed < self.min_request_interval:
                            # 대기 시간 계산
                            wait_time = self.min_request_interval - elapsed
                            logger.debug(f"[{self.name}] Rate limiting {domain}: waiting {wait_time:.2f}s")
                            await asyncio.sleep(wait_time)

                        # 요청 시간 기록
                        self.domain_last_request_time[domain] = time.time()

                    # 실제 페이지 fetch
                    return await asyncio.wait_for(
                        self._fetch_single_link(link),
                        timeout=15  # 페이지당 15초
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"[{self.name}] Timeout fetching: {link.url}")
                    return None
                except Exception as e:
                    logger.error(f"[{self.name}] Error fetching {link.url}: {e}")
                    return None

        # 병렬 실행
        tasks = [fetch_with_limit(link) for link in links]
        fetch_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 성공한 결과만 필터링
        results = []
        for result in fetch_results:
            if result and not isinstance(result, Exception):
                results.append(result)

        return results

    async def _fetch_single_link(self, link: LinkCandidate) -> Optional[SearchResult]:
        """단일 링크 페칭

        프로토타입: 실제 HTTP 요청 없이 시뮬레이션
        (추후 WebLookUpAgent 통합)
        """
        # 프로토타입에서는 시뮬레이션
        # 실제 구현 시 WebLookUpAgent 또는 aiohttp 사용

        logger.debug(f"[{self.name}] Fetching (simulated): {link.url}")

        # 시뮬레이션: 간단한 SearchResult 생성
        result = SearchResult(
            source="iterative_link_following",
            title=f"Content from {link.anchor_text}",
            content=f"Simulated content from {link.url}. Context: {link.context}",
            url=link.url,
            score=link.relevance_score,
            metadata={
                "search_type": "link_following",
                "depth": link.depth,
                "source_url": link.source_url
            }
        )

        return result

    # _evaluate_quality_simple 메서드는 SearchQualityEvaluator로 대체되었습니다.
    # 품질 평가는 이제 quality_evaluator.evaluate_quality()를 통해 수행됩니다.

    # ============================================================================
    # STEP 5: Performance Optimization - Caching
    # ============================================================================

    async def _check_exploration_cache(
        self,
        query: str,
        max_depth: int,
        max_pages: int,
        quality_threshold: float
    ) -> Optional[Dict[str, Any]]:
        """탐색 결과 캐시 확인

        캐시 키: iterative_exploration:{query_hash}:d{depth}_p{pages}_q{threshold}

        Args:
            query: 검색 쿼리
            max_depth: 최대 깊이
            max_pages: 최대 페이지 수
            quality_threshold: 품질 임계값

        Returns:
            캐시된 결과 또는 None
        """
        try:
            # 캐시 키 생성
            query_normalized = query.lower().strip()
            query_hash = hash(query_normalized)
            cache_key = cache_manager.make_key(
                "iterative_exploration",
                query_hash,
                f"d{max_depth}_p{max_pages}_q{int(quality_threshold * 100)}"
            )

            # 캐시 조회 (TTL: 1시간)
            cached = await cache_manager.get(cache_key, deserialize="pickle")

            if cached:
                logger.info(f"[{self.name}] Cache hit - returning cached exploration results")
                return cached

            return None

        except Exception as e:
            logger.warning(f"[{self.name}] Cache check failed: {e}")
            return None

    async def _cache_exploration_results(
        self,
        query: str,
        max_depth: int,
        max_pages: int,
        quality_threshold: float,
        result: Dict[str, Any]
    ) -> None:
        """탐색 결과 캐싱

        Args:
            query: 검색 쿼리
            max_depth: 최대 깊이
            max_pages: 최대 페이지 수
            quality_threshold: 품질 임계값
            result: 탐색 결과
        """
        try:
            # 성공한 결과만 캐싱
            if not result.get("success"):
                return

            # 캐시 키 생성 (동일한 로직)
            query_normalized = query.lower().strip()
            query_hash = hash(query_normalized)
            cache_key = cache_manager.make_key(
                "iterative_exploration",
                query_hash,
                f"d{max_depth}_p{max_pages}_q{int(quality_threshold * 100)}"
            )

            # 캐싱 (TTL: 1시간)
            await cache_manager.set(
                cache_key,
                result,
                ttl=3600,  # 1 hour
                serialize="pickle"
            )

            logger.info(f"[{self.name}] Cached exploration results for query: {query[:50]}")

        except Exception as e:
            logger.warning(f"[{self.name}] Cache save failed: {e}")

"""Iterative Web Explorer Agent - 반복적 웹 탐색 에이전트

인간처럼 웹을 탐색하는 에이전트:
- 검색 결과를 상위부터 확인
- 페이지 내 링크를 추출하고 관련성 평가
- 품질이 충분할 때까지 반복적으로 탐색
"""

from typing import Dict, Any, List, Set, Optional, TYPE_CHECKING
from dataclasses import dataclass, field
from urllib.parse import urlparse
from collections import defaultdict
import asyncio
import logging
import time

from neos.agents.base import SearchAgent
from neos.workflow.state import SearchResult
from neos.config.settings import settings
from neos.utils.cache import cache_manager

# Lazy import to avoid circular dependency
if TYPE_CHECKING:
    from .quality_evaluator import QualityMetrics

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

        # 도구 초기화 (lazy loading)
        self.link_follower = None
        self.web_lookup_agent = None

        # HTTP 클라이언트 (세션별로 생성, fallback용)
        self.session = None

        # 품질 평가기 (세션별로 생성)
        self.quality_evaluator = None

        # STEP 5: Domain-level rate limiting
        self.domain_last_request_time: Dict[str, float] = {}
        self.domain_locks: defaultdict = defaultdict(asyncio.Lock)  # Domain별 Lock (자동 생성)
        self.min_request_interval = 1.0  # 같은 도메인에 최소 1초 간격

        logger.info(f"[{self.name}] Initialized with max_depth={self.max_depth}, max_pages={self.max_pages}")

    async def _initialize_tools(self):
        """도구 초기화 (LinkFollower, WebLookup)

        Returns:
            bool: 초기화 성공 여부
        """
        try:
            # LinkFollowerMCPTool 초기화
            from neos.tools.tools import LinkFollowerMCPTool
            self.link_follower = LinkFollowerMCPTool()
            await self.link_follower.initialize()
            logger.info(f"[{self.name}] LinkFollowerMCPTool initialized")
        except Exception as e:
            logger.warning(f"[{self.name}] LinkFollower init failed: {e}")
            self.link_follower = None

        try:
            # WebLookUpAgent 초기화
            from neos.agents.search_agents.web_lookup import WebLookUpAgent
            self.web_lookup_agent = WebLookUpAgent()
            logger.info(f"[{self.name}] WebLookUpAgent initialized")
        except Exception as e:
            logger.warning(f"[{self.name}] WebLookUpAgent init failed: {e}")
            self.web_lookup_agent = None

        # 최소한 하나라도 성공하면 True
        return self.link_follower is not None or self.web_lookup_agent is not None

    def _cleanup_old_rate_limit_entries(self):
        """오래된 rate limit 항목 정리 (메모리 누수 방지)

        1시간 이상 사용되지 않은 도메인 정보 삭제
        """
        current_time = time.time()
        ttl = 3600  # 1시간

        # 딕셔너리 복사본에서 반복하여 동시 수정 문제 방지
        old_domains = [
            domain for domain, last_time in list(self.domain_last_request_time.items())
            if current_time - last_time > ttl
        ]

        for domain in old_domains:
            # 안전하게 삭제 (KeyError 방지)
            self.domain_last_request_time.pop(domain, None)
            self.domain_locks.pop(domain, None)

        if old_domains:
            logger.debug(f"[{self.name}] Cleaned up {len(old_domains)} old rate limit entries")


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

        # 오래된 rate limit 항목 정리
        self._cleanup_old_rate_limit_entries()

        # 도구 초기화 (처음 실행 시)
        if not self.link_follower and not self.web_lookup_agent:
            initialized = await self._initialize_tools()
            if not initialized:
                logger.warning(f"[{self.name}] Tools not available, using fallback methods")

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
            max_iterations = settings.ITERATIVE_EXPLORER_MAX_ITERATIONS
            while (state.current_depth < max_depth and
                   state.pages_visited < max_pages and
                   state.iteration_count < max_iterations):  # 최대 반복 제한

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
                if state.pages_visited >= max_pages * settings.ITERATIVE_EXPLORER_PAGE_LIMIT_THRESHOLD:
                    logger.info(f"[{self.name}] Approaching page limit ({state.pages_visited}/{max_pages})")
                    break

                # 링크 추출 및 우선순위화
                recent_window = settings.ITERATIVE_EXPLORER_RECENT_RESULTS_WINDOW
                new_links = await self._extract_and_prioritize_links(
                    state.collected_sources[-recent_window:],  # 최근 N개 결과에서만 추출
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
                        max_results=settings.ITERATIVE_EXPLORER_INITIAL_SEARCH_RESULTS,
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

        LinkFollowerMCPTool을 사용한 실제 구현
        """
        if not self.link_follower:
            logger.warning(f"[{self.name}] LinkFollower not available, using fallback")
            return await self._extract_links_fallback(results, query, state)

        candidates = []

        for result in results:
            if not result.content or not result.url:
                continue

            try:
                # LinkFollowerMCPTool 사용하여 실제 링크 추출
                link_result = await self.link_follower.execute({
                    "source_url": result.url,
                    "max_links": settings.LINK_FOLLOWER_MAX_LINKS,
                    "min_relevance": settings.LINK_FOLLOWER_MIN_RELEVANCE,
                    "query_context": query,
                    "same_domain_only": False
                })

                if not link_result.success:
                    logger.warning(f"[{self.name}] Link extraction failed for {result.url}: {link_result.error}")
                    continue

                # 추출된 링크를 LinkCandidate로 변환
                for link_data in link_result.data.get("links", []):
                    link_url = link_data["url"]

                    # 이미 방문한 URL은 스킵
                    if link_url in state.visited_urls:
                        continue

                    # 다양성 페널티 계산
                    link_domain = urlparse(link_url).netloc
                    domain_count = sum(1 for r in state.collected_sources
                                      if r.url and urlparse(r.url).netloc == link_domain)
                    diversity_penalty = min(domain_count * 0.1, 0.5)

                    candidate = LinkCandidate(
                        url=link_url,
                        source_url=result.url,
                        anchor_text=link_data.get("anchor_text", ""),
                        context=link_data.get("context", ""),
                        relevance_score=link_data.get("relevance_score", 0.5) - diversity_penalty,
                        depth=state.current_depth + 1
                    )
                    candidates.append(candidate)

            except Exception as e:
                logger.error(f"[{self.name}] Error extracting links from {result.url}: {e}")
                continue

        # 관련성 점수로 정렬
        candidates.sort(key=lambda x: x.relevance_score, reverse=True)

        return candidates[:20]  # 상위 20개만

    async def _extract_links_fallback(
        self,
        results: List[SearchResult],
        query: str,
        state: ExplorationState
    ) -> List[LinkCandidate]:
        """링크 추출 폴백 (LinkFollower 사용 불가 시)

        간단한 휴리스틱 기반 추측
        """
        candidates = []

        for result in results:
            if not result.url:
                continue

            source_domain = urlparse(result.url).netloc
            potential_paths = ["/about", "/resources", "/documentation", "/blog"]

            for path in potential_paths:
                candidate_url = f"https://{source_domain}{path}"

                if candidate_url in state.visited_urls:
                    continue

                candidate = LinkCandidate(
                    url=candidate_url,
                    source_url=result.url,
                    anchor_text=path,
                    context=result.title or "",
                    relevance_score=0.5,
                    depth=state.current_depth + 1
                )
                candidates.append(candidate)

        return candidates[:10]

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
                    # STEP 5: Domain-level rate limiting with Lock
                    domain = urlparse(link.url).netloc
                    if domain:
                        # 도메인별 Lock 가져오기 (defaultdict로 자동 생성)
                        domain_lock = self.domain_locks[domain]

                        # Lock으로 보호하여 race condition 방지
                        async with domain_lock:
                            # 마지막 요청 시간 확인
                            last_request = self.domain_last_request_time.get(domain, 0)
                            elapsed = time.time() - last_request

                            if elapsed < self.min_request_interval:
                                # 대기 시간 계산
                                wait_time = self.min_request_interval - elapsed
                                logger.debug(f"[{self.name}] Rate limiting {domain}: waiting {wait_time:.2f}s")
                                await asyncio.sleep(wait_time)

                            # 요청 시간 기록 (Lock 안에서)
                            self.domain_last_request_time[domain] = time.time()

                    # Lock 해제 후 실제 페이지 fetch
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

        WebLookUpAgent를 사용한 실제 구현
        """
        if not self.web_lookup_agent:
            logger.warning(f"[{self.name}] WebLookUpAgent not available, using fallback")
            return await self._fetch_link_fallback(link)

        try:
            logger.debug(f"[{self.name}] Fetching: {link.url}")

            # WebLookUpAgent 사용하여 실제 페이지 콘텐츠 가져오기
            context = {
                "max_content_length": 2000,  # 콘텐츠 길이 제한
                "extract_metadata": True
            }

            fetch_result = await self.web_lookup_agent.execute(link.url, context)

            if not fetch_result.get("success"):
                logger.warning(f"[{self.name}] Failed to fetch {link.url}: {fetch_result.get('error')}")
                return None

            # WebLookUpAgent는 format_output을 사용하므로 result 키에 SearchResult 리스트가 있음
            page_results = fetch_result.get("result", [])
            if not page_results or len(page_results) == 0:
                logger.warning(f"[{self.name}] No results from WebLookUpAgent for {link.url}")
                return None

            # 첫 번째 결과 사용
            page_data = page_results[0]

            # 타입 검증
            if not isinstance(page_data, (SearchResult, dict)):
                logger.error(f"[{self.name}] Unexpected result type from WebLookUpAgent: {type(page_data)}")
                return None

            # SearchResult로 변환 (이미 SearchResult 객체일 수 있음)
            if isinstance(page_data, SearchResult):
                # 메타데이터 업데이트
                page_data.metadata.update({
                    "search_type": "link_following",
                    "depth": link.depth,
                    "source_url": link.source_url,
                    "anchor_text": link.anchor_text,
                    "context": link.context
                })
                return page_data
            else:
                # dict인 경우 SearchResult 생성
                result = SearchResult(
                    source="iterative_link_following",
                    title=page_data.get("title", link.anchor_text),
                    content=page_data.get("content", ""),
                    url=link.url,
                    score=link.relevance_score,
                    metadata={
                        "search_type": "link_following",
                        "depth": link.depth,
                        "source_url": link.source_url,
                        "anchor_text": link.anchor_text,
                        "context": link.context
                    }
                )
                return result

        except Exception as e:
            logger.error(f"[{self.name}] Error fetching {link.url}: {e}")
            return None

    async def _fetch_link_fallback(self, link: LinkCandidate) -> Optional[SearchResult]:
        """링크 페칭 폴백 (WebLookUpAgent 사용 불가 시)

        기본적인 aiohttp 사용
        """
        try:
            import aiohttp
            from bs4 import BeautifulSoup

            if not self.session:
                timeout = aiohttp.ClientTimeout(total=30)
                self.session = aiohttp.ClientSession(timeout=timeout)

            async with self.session.get(link.url) as response:
                if response.status != 200:
                    return None

                html = await response.text()

                # 간단한 HTML 파싱
                soup = BeautifulSoup(html, 'html.parser')

                title = soup.find('title')
                title_text = title.get_text() if title else link.anchor_text

                # 본문 추출 (간단하게)
                paragraphs = soup.find_all('p')
                content = ' '.join([p.get_text() for p in paragraphs[:5]])

                return SearchResult(
                    source="iterative_link_following_fallback",
                    title=title_text,
                    content=content[:2000],
                    url=link.url,
                    score=link.relevance_score,
                    metadata={
                        "search_type": "link_following",
                        "depth": link.depth,
                        "source_url": link.source_url
                    }
                )

        except Exception as e:
            logger.error(f"[{self.name}] Fallback fetch failed for {link.url}: {e}")
            return None

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

            # 캐싱 (TTL: 설정값 사용)
            await cache_manager.set(
                cache_key,
                result,
                ttl=settings.ITERATIVE_EXPLORER_CACHE_TTL,
                serialize="pickle"
            )

            logger.info(f"[{self.name}] Cached exploration results for query: {query[:50]}")

        except Exception as e:
            logger.warning(f"[{self.name}] Cache save failed: {e}")

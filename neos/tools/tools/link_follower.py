"""Link Follower MCP Tool - 웹 페이지 링크 추출 및 팔로잉

Features:
- HTML 파싱으로 링크 추출
- 링크 관련성 점수 계산
- 메타데이터 추출 (제목, 설명, 컨텍스트)
- URL 정규화 및 검증
- 보안 검증
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from urllib.parse import urlparse, urljoin
import logging
import aiohttp
from bs4 import BeautifulSoup
import re

from neos.tools.base import MCPTool, MCPToolResult, MCPToolType

logger = logging.getLogger(__name__)


class LinkFollowerMCPTool(MCPTool):
    """링크 팔로잉 및 추출 도구

    Capabilities:
    - link_extraction: HTML에서 링크 추출
    - relevance_scoring: 링크 관련성 점수 계산
    - metadata_extraction: 제목, 설명, 컨텍스트 추출
    - url_normalization: URL 정규화
    """

    def __init__(self):
        super().__init__(
            name="link_follower",
            tool_type=MCPToolType.WEB_SEARCH,
            description="Extract and score links from web pages for iterative exploration",
            capabilities=[
                "link_extraction",
                "relevance_scoring",
                "metadata_extraction",
                "url_normalization"
            ]
        )
        self.client: Optional[aiohttp.ClientSession] = None

        # 허용된 도메인 (빈 리스트면 모든 도메인 허용)
        self.allowed_domains: List[str] = []

        # 차단된 도메인
        self.blocked_domains: List[str] = [
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "*.local"
        ]

    async def initialize(self) -> bool:
        """HTTP 클라이언트 초기화"""
        try:
            # aiohttp 클라이언트 생성
            timeout = aiohttp.ClientTimeout(total=30)
            connector = aiohttp.TCPConnector(limit=10)

            self.client = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; NeosBot/1.0)'
                }
            )

            self.is_available = True
            logger.info(f"[{self.name}] Initialized successfully")
            return True

        except Exception as e:
            logger.error(f"[{self.name}] Initialization failed: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> MCPToolResult:
        """링크 팔로잉 실행

        Args:
            params: {
                "source_url": str (필수) - 링크를 추출할 소스 URL
                "max_links": int (선택, 기본값 10) - 최대 추출 링크 수
                "min_relevance": float (선택, 기본값 0.5) - 최소 관련성 점수
                "query_context": str (선택) - 관련성 평가를 위한 쿼리 컨텍스트
                "same_domain_only": bool (선택, 기본값 False) - 같은 도메인만 허용
            }

        Returns:
            MCPToolResult with extracted links
        """
        start_time = datetime.now()

        try:
            # HTTP 세션 확인 및 초기화
            if not self.client or self.client.closed:
                logger.warning(f"[{self.name}] HTTP client not initialized, initializing now")
                initialized = await self.initialize()
                if not initialized:
                    return MCPToolResult.from_error(
                        error="Failed to initialize HTTP client",
                        tool_name=self.name,
                        execution_time_ms=0
                    )

            # 1. 파라미터 추출 및 검증
            source_url = params.get("source_url")
            if not source_url:
                return MCPToolResult.from_error(
                    error="source_url parameter is required",
                    tool_name=self.name
                )

            max_links = params.get("max_links", 10)
            min_relevance = params.get("min_relevance", 0.5)
            query_context = params.get("query_context", "")
            same_domain_only = params.get("same_domain_only", False)

            # URL 안전성 검증
            if not self._is_safe_url(source_url):
                return MCPToolResult.from_error(
                    error=f"Unsafe or invalid URL: {source_url}",
                    tool_name=self.name
                )

            # 2. HTML 페칭
            html = await self._fetch_html(source_url)
            if not html:
                return MCPToolResult.from_error(
                    error=f"Failed to fetch HTML from: {source_url}",
                    tool_name=self.name
                )

            # 3. 링크 추출
            links = await self._extract_links(
                html=html,
                source_url=source_url,
                query_context=query_context,
                min_relevance=min_relevance,
                same_domain_only=same_domain_only
            )

            # 4. 결과 제한
            top_links = links[:max_links]

            execution_time = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )

            # 5. 성공 결과 반환
            return MCPToolResult.from_success(
                data={
                    "source_url": source_url,
                    "links_found": len(links),
                    "links_returned": len(top_links),
                    "links": [
                        {
                            "url": link["url"],
                            "anchor_text": link["anchor_text"],
                            "context": link["context"],
                            "relevance_score": link["relevance_score"]
                        }
                        for link in top_links
                    ]
                },
                tool_name=self.name,
                execution_time_ms=execution_time,
                metadata={
                    "source_domain": urlparse(source_url).netloc,
                    "same_domain_only": same_domain_only
                }
            )

        except Exception as e:
            execution_time = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )
            logger.error(f"[{self.name}] Execution error: {e}", exc_info=True)
            return MCPToolResult.from_error(
                error=str(e),
                tool_name=self.name,
                execution_time_ms=execution_time
            )

    async def cleanup(self) -> None:
        """HTTP 클라이언트 정리"""
        if self.client:
            try:
                await self.client.close()
                logger.info(f"[{self.name}] Cleaned up successfully")
            except Exception as e:
                logger.error(f"[{self.name}] Cleanup error: {e}")

    # ========================================================================
    # Private Methods
    # ========================================================================

    def _is_safe_url(self, url: str) -> bool:
        """URL 안전성 검증

        Args:
            url: 검증할 URL

        Returns:
            안전하면 True, 아니면 False
        """
        try:
            parsed = urlparse(url)

            # 스킴 검증 (http, https만 허용)
            if parsed.scheme not in ["http", "https"]:
                logger.warning(f"[{self.name}] Invalid scheme: {parsed.scheme}")
                return False

            # 도메인 검증
            netloc = parsed.netloc.lower()

            # 차단된 도메인 확인
            for blocked in self.blocked_domains:
                if blocked.startswith("*."):
                    # 와일드카드 패턴
                    suffix = blocked[2:]
                    if netloc.endswith(suffix):
                        logger.warning(f"[{self.name}] Blocked domain: {netloc}")
                        return False
                elif blocked in netloc:
                    logger.warning(f"[{self.name}] Blocked domain: {netloc}")
                    return False

            # 허용된 도메인 확인 (설정된 경우)
            if self.allowed_domains:
                allowed = any(domain in netloc for domain in self.allowed_domains)
                if not allowed:
                    logger.warning(f"[{self.name}] Not in allowed domains: {netloc}")
                    return False

            return True

        except Exception as e:
            logger.error(f"[{self.name}] URL validation error: {e}")
            return False

    async def _fetch_html(self, url: str) -> Optional[str]:
        """URL에서 HTML 페칭

        Args:
            url: 페칭할 URL

        Returns:
            HTML 문자열 또는 None
        """
        try:
            async with self.client.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    logger.warning(f"[{self.name}] HTTP {response.status} for {url}")
                    return None

                content_type = response.headers.get('Content-Type', '')

                # HTML 콘텐츠만 처리
                if 'text/html' not in content_type:
                    logger.warning(f"[{self.name}] Non-HTML content: {content_type}")
                    return None

                html = await response.text()
                return html

        except aiohttp.ClientError as e:
            logger.error(f"[{self.name}] HTTP error fetching {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"[{self.name}] Unexpected error fetching {url}: {e}")
            return None

    async def _extract_links(
        self,
        html: str,
        source_url: str,
        query_context: str,
        min_relevance: float,
        same_domain_only: bool
    ) -> List[Dict[str, Any]]:
        """HTML에서 링크 추출 및 점수 계산

        Args:
            html: HTML 문자열
            source_url: 소스 URL
            query_context: 쿼리 컨텍스트
            min_relevance: 최소 관련성 점수
            same_domain_only: 같은 도메인만 허용

        Returns:
            추출된 링크 리스트 (관련성 점수로 정렬)
        """
        soup = BeautifulSoup(html, 'html.parser')
        source_domain = urlparse(source_url).netloc

        candidates = []
        seen_urls = set()

        # <a> 태그에서 링크 추출
        for anchor in soup.find_all('a', href=True):
            href = anchor['href']

            # 앵커 텍스트
            anchor_text = anchor.get_text(strip=True)
            if not anchor_text:
                anchor_text = anchor.get('title', anchor.get('aria-label', ''))

            # URL 정규화
            absolute_url = urljoin(source_url, href)

            # 중복 제거
            if absolute_url in seen_urls:
                continue
            seen_urls.add(absolute_url)

            # 프래그먼트 제거 (#section)
            absolute_url = absolute_url.split('#')[0]

            # 같은 도메인 필터링
            link_domain = urlparse(absolute_url).netloc
            if same_domain_only and link_domain != source_domain:
                continue

            # 안전성 검증
            if not self._is_safe_url(absolute_url):
                continue

            # 주변 컨텍스트 추출
            context = self._extract_context(anchor)

            # 관련성 점수 계산
            relevance = self._score_link_relevance(
                anchor_text=anchor_text,
                context=context,
                query_context=query_context,
                url=absolute_url
            )

            # 최소 점수 필터링
            if relevance < min_relevance:
                continue

            candidates.append({
                "url": absolute_url,
                "anchor_text": anchor_text,
                "context": context,
                "relevance_score": relevance,
                "domain": link_domain
            })

        # 관련성 점수로 정렬
        candidates.sort(key=lambda x: x["relevance_score"], reverse=True)

        return candidates

    def _extract_context(self, anchor) -> str:
        """앵커 주변 컨텍스트 추출

        Args:
            anchor: BeautifulSoup anchor 태그

        Returns:
            주변 텍스트 (최대 200자)
        """
        try:
            # 부모 요소에서 텍스트 추출
            parent = anchor.parent
            if parent:
                text = parent.get_text(strip=True)
                # 앵커 텍스트 전후로 100자씩
                anchor_text = anchor.get_text(strip=True)
                idx = text.find(anchor_text)
                if idx >= 0:
                    start = max(0, idx - 100)
                    end = min(len(text), idx + len(anchor_text) + 100)
                    context = text[start:end]
                    return context[:200]

            return ""

        except Exception as e:
            logger.warning(f"[{self.name}] Context extraction error: {e}")
            return ""

    def _score_link_relevance(
        self,
        anchor_text: str,
        context: str,
        query_context: str,
        url: str
    ) -> float:
        """링크 관련성 점수 계산 (휴리스틱 기반)

        Args:
            anchor_text: 앵커 텍스트
            context: 주변 컨텍스트
            query_context: 쿼리 컨텍스트
            url: URL

        Returns:
            관련성 점수 (0.0-1.0)
        """
        score = 0.0

        # 1. 앵커 텍스트 길이 (적절한 길이 선호)
        anchor_len = len(anchor_text)
        if 10 <= anchor_len <= 100:
            score += 0.2
        elif anchor_len > 0:
            score += 0.1

        # 2. 쿼리 컨텍스트와의 키워드 매칭
        if query_context:
            query_keywords = set(re.findall(r'\w+', query_context.lower()))
            text_keywords = set(re.findall(r'\w+', (anchor_text + " " + context).lower()))

            if query_keywords:
                overlap = len(query_keywords & text_keywords)
                score += min(overlap / len(query_keywords), 0.4)

        # 3. URL 경로 품질 (너무 깊지 않은 경로 선호)
        parsed = urlparse(url)
        path_depth = len([p for p in parsed.path.split('/') if p])
        if path_depth <= 3:
            score += 0.2
        elif path_depth <= 5:
            score += 0.1

        # 4. 유용한 키워드 포함 여부
        useful_keywords = [
            'article', 'documentation', 'guide', 'tutorial', 'resource',
            'about', 'detail', 'information', 'content'
        ]
        text_lower = (anchor_text + " " + context + " " + url).lower()
        if any(keyword in text_lower for keyword in useful_keywords):
            score += 0.2

        # 5. 제외할 패턴 (로그인, 광고 등)
        exclude_patterns = [
            'login', 'signin', 'logout', 'signup', 'register',
            'cart', 'checkout', 'payment',
            'privacy', 'terms', 'cookie',
            'ad', 'advertisement'
        ]
        if any(pattern in text_lower for pattern in exclude_patterns):
            score *= 0.5

        # 점수 정규화 (0.0-1.0)
        return min(score, 1.0)

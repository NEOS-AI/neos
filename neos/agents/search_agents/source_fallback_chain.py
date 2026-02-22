"""
External Search Source Fallback Chain

검색 소스의 circuit breaker가 open되거나 에러 발생 시
자동으로 다음 소스로 라우팅합니다.

각 소스에 per-source circuit breaker를 적용하여
지속적으로 실패하는 소스를 자동으로 격리합니다.

Usage:
    chain = SourceFallbackChain(chain_type="web")
    result = await chain.execute(
        query="search query",
        source_callables={"tavily": tavily_search, "duckduckgo": ddg_search},
        context={"max_results": 10},
    )
"""

import logging
from typing import Dict, Any, List, Optional, Callable, Awaitable, Protocol, runtime_checkable
from dataclasses import dataclass, field
from enum import Enum

from neos.config.settings import settings

logger = logging.getLogger(__name__)


@runtime_checkable
class SourceCallable(Protocol):
    """검색 소스 callable의 시그니처를 정의합니다.

    모든 소스 callable은 (query, context) 형태로 호출됩니다.
    """
    async def __call__(self, query: str, context: Dict[str, Any]) -> Any: ...


class SourceType(str, Enum):
    """검색 소스 타입"""
    TAVILY = "tavily"
    DUCKDUCKGO = "duckduckgo"
    BING = "bing"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    ARXIV = "arxiv"
    NEWS_API = "news_api"
    PUBMED = "pubmed"
    WIKIPEDIA = "wikipedia"


# Intent별 fallback chain 정의
FALLBACK_CHAINS: Dict[str, List[SourceType]] = {
    "web": [SourceType.TAVILY, SourceType.DUCKDUCKGO, SourceType.BING],
    "academic": [SourceType.SEMANTIC_SCHOLAR, SourceType.ARXIV, SourceType.PUBMED],
    "news": [SourceType.NEWS_API, SourceType.TAVILY, SourceType.DUCKDUCKGO],
    "reference": [SourceType.WIKIPEDIA, SourceType.TAVILY],
    "default": [SourceType.TAVILY, SourceType.DUCKDUCKGO],
}


@dataclass
class FallbackResult:
    """Fallback chain 실행 결과"""
    success: bool
    source_used: Optional[str] = None
    data: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    fallback_triggered: bool = False
    sources_tried: List[str] = field(default_factory=list)


class SourceFallbackChain:
    """검색 소스 fallback chain.

    각 소스에 per-source circuit breaker를 적용하여
    실패하는 소스를 자동 격리하고 다음 소스로 전환합니다.
    """

    def __init__(self, chain_type: str = "default"):
        self.chain = FALLBACK_CHAINS.get(chain_type, FALLBACK_CHAINS["default"])
        self.chain_type = chain_type

    async def execute(
        self,
        query: str,
        source_callables: Dict[str, SourceCallable],
        context: Optional[Dict[str, Any]] = None,
    ) -> FallbackResult:
        """Fallback chain을 통해 쿼리를 실행합니다.

        첫 번째 성공한 소스의 결과를 반환합니다.

        Args:
            query: 검색 쿼리
            source_callables: 소스 이름 → async callable 매핑
            context: 각 callable에 전달할 추가 컨텍스트

        Returns:
            FallbackResult
        """
        if not settings.SEARCH_FALLBACK_ENABLED:
            # Fallback 비활성화 시 첫 번째 callable만 시도
            return await self._try_first_available(query, source_callables, context)

        sources_tried = []

        for i, source in enumerate(self.chain):
            callable_fn = source_callables.get(source.value)
            if callable_fn is None:
                logger.debug(f"[FallbackChain] No callable for {source.value}, skipping")
                continue

            sources_tried.append(source.value)

            # Per-source circuit breaker
            from neos.utils.circuit_breaker import _get_async_breaker
            breaker = _get_async_breaker(f"source_{source.value}")

            try:
                result = await breaker.call(callable_fn, query, context or {})

                # 결과를 리스트로 정규화
                if isinstance(result, list):
                    data = result
                elif isinstance(result, dict):
                    data = result.get("results", result.get("data", [result]))
                else:
                    data = []

                logger.info(
                    f"[FallbackChain] Source {source.value} succeeded "
                    f"({len(data)} results)"
                )
                return FallbackResult(
                    success=True,
                    source_used=source.value,
                    data=data,
                    fallback_triggered=(i > 0),
                    sources_tried=sources_tried,
                )

            except Exception as e:
                logger.warning(
                    f"[FallbackChain] Source {source.value} failed: {e}, "
                    f"trying next source"
                )
                continue

        logger.error(
            f"[FallbackChain] All sources exhausted for chain '{self.chain_type}'. "
            f"Tried: {sources_tried}"
        )
        return FallbackResult(
            success=False,
            source_used=None,
            error="All sources in fallback chain exhausted",
            sources_tried=sources_tried,
        )

    async def _try_first_available(
        self,
        query: str,
        source_callables: Dict[str, SourceCallable],
        context: Optional[Dict[str, Any]],
    ) -> FallbackResult:
        """Fallback 비활성화 시 첫 번째 사용 가능한 소스만 시도"""
        for source in self.chain:
            callable_fn = source_callables.get(source.value)
            if callable_fn is None:
                continue
            try:
                result = await callable_fn(query, context or {})
                data = result if isinstance(result, list) else []
                return FallbackResult(
                    success=True,
                    source_used=source.value,
                    data=data,
                    sources_tried=[source.value],
                )
            except Exception as e:
                return FallbackResult(
                    success=False,
                    error=str(e),
                    sources_tried=[source.value],
                )
        return FallbackResult(success=False, error="No callable sources available")

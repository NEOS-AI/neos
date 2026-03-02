"""
Universal Citation System for NEOS

HyperDeepResearch에 격리되어 있던 CitationTracker를 모든 워크플로우 응답에서
사용할 수 있도록 공용 래퍼를 제공합니다.

기존 CitationTracker를 lazy import로 위임하여:
1. 코드 중복 없이 단일 진실점(Single Source of Truth) 유지
2. Circular import 방지 (hyper_deep_research 패키지의 무거운 의존성)

Usage:
    tracker = UniversalCitationTracker(style="numbered")
    tracker.register_sources([
        {"url": "https://...", "title": "...", "content": "..."},
    ])
    references = tracker.generate_reference_list()
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class UniversalCitationTracker:
    """모든 워크플로우 응답에 citation을 적용하는 공용 래퍼.

    내부적으로 HyperDeepResearch의 CitationTracker를 lazy import하여 위임합니다.

    Supported styles: "numbered", "apa", "mla", "chicago", "vancouver"
    """

    def __init__(self, style: str = "numbered"):
        self.style = style
        self._tracker = None

    def _get_tracker(self):
        """Lazy-init CitationTracker to avoid circular imports."""
        if self._tracker is None:
            try:
                from neos.agents.search_agents.hyper_deep_research.utils.citation_tracker import (
                    CitationTracker,
                )
                self._tracker = CitationTracker()
            except ImportError:
                logger.error("[Citations] Failed to import CitationTracker")
                raise
        return self._tracker

    def register_sources(self, sources: List[Dict[str, Any]]) -> int:
        """소스를 등록하고 citation 번호를 할당합니다.

        Args:
            sources: 소스 딕셔너리 리스트. 각 항목에 최소 'url', 'title' 필요.
                     선택적: 'content', 'author', 'published_date', 'score'

        Returns:
            등록된 소스 개수
        """
        tracker = self._get_tracker()
        return tracker.register_sources(sources)

    def generate_reference_list(
        self,
        style: Optional[str] = None,
        only_cited: bool = False,
    ) -> str:
        """Reference list를 생성합니다.

        Args:
            style: Citation 스타일 (None이면 초기화 시 설정한 style 사용)
            only_cited: True면 인용된 소스만, False면 모든 등록된 소스

        Returns:
            Markdown 형식의 reference list
        """
        tracker = self._get_tracker()
        return tracker.generate_reference_list(
            style=style or self.style,
            only_cited=only_cited,
        )

    def get_source_list_for_prompt(self, max_sources: int = 100) -> str:
        """LLM 프롬프트에 포함할 소스 목록을 생성합니다."""
        tracker = self._get_tracker()
        return tracker.get_source_list_for_prompt(max_sources=max_sources)

    def validate_citations(self, text: str) -> Dict[str, Any]:
        """텍스트의 citation이 유효한지 검증합니다."""
        tracker = self._get_tracker()
        return tracker.validate_citations(text)

    @property
    def has_sources(self) -> bool:
        """등록된 소스가 있는지 확인합니다."""
        if self._tracker is None:
            return False
        return self._tracker.source_count > 0

    @property
    def source_count(self) -> int:
        """등록된 소스 개수를 반환합니다."""
        if self._tracker is None:
            return 0
        return self._tracker.source_count

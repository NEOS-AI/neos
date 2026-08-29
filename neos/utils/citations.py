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
import re
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


# ---------------------------------------------------------------------------
# 출처 절 조립 (D-6, 2026-08-29)
#
# 세 곳이 각자 하던 일 하나를 여기로 모은다: **번호를 매긴 출처 줄을 본문 끝에
# 붙이되 제목을 중복시키지 않는 것.** `deep_analysis/citation.py` 는 정규식으로,
# markdown exporter 는 무조건 붙이는 방식으로 따로 구현하고 있었다.
#
# ⚠️ **모은 것은 렌더뿐이다.** `deep_analysis` 의 `[C:id]` → 원장 대조와
# orphan 의미론(D10 -- orphan 은 조립 재시도를 유발한다)은 그 모듈에 남는다.
# 그것은 서지 렌더링이 아니라 검증된 클레임의 주소 해석이고, 여기로 끌어오면
# 재시도 계약이 서지 포맷터에 섞인다. §11.2 의 정정 상자 참조.
# ---------------------------------------------------------------------------

#: deep_analysis 리포트가 쓰는 출처 절 제목.
SOURCE_HEADING_KO = "## 출처"


def numbered_source_lines(entries: list[str]) -> list[str]:
    """`[1] ...` 꼴로 1부터 조밀하게 번호를 매긴다.

    번호를 건너뛰지 않는 것이 계약이다 -- 배달된 리포트의 `[1][3][4]` 는
    독자에게 누락으로 보인다. 건너뛸 항목은 **호출자가 미리 걸러서** 넘긴다
    (deep_analysis 의 orphan 처리가 그렇게 한다).
    """
    return [f"[{i}] {entry}" for i, entry in enumerate(entries, 1)]


def attach_source_section(
    body: str,
    lines: list[str],
    *,
    heading: str,
) -> str:
    """본문 끝에 출처 절을 붙인다. 이미 제목이 있으면 그 아래에 잇는다.

    줄이 하나도 없으면 **본문을 그대로 돌려준다** -- 빈 제목만 남기면
    "출처를 못 찾았다" 가 아니라 "출처 절이 있다" 로 읽힌다.
    """
    if not lines:
        return body

    block = "\n".join(lines)
    trimmed = body.rstrip()
    if re.search(rf"(?m)^{re.escape(heading)}\s*$", trimmed):
        return f"{trimmed}\n{block}\n"
    return f"{trimmed}\n\n{heading}\n{block}\n"

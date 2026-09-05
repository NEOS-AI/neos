"""Base exporter classes and data models"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime


class ExportFormat(str, Enum):
    MARKDOWN = "markdown"
    HTML = "html"
    PDF = "pdf"
    CANVAS = "canvas"


@dataclass
class ResearchReport:
    """구조화된 연구 리포트 데이터"""
    session_id: str
    query: str
    response: str
    search_results: List[Dict[str, Any]] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    quality_score: Optional[float] = None
    fact_check_result: Optional[Dict[str, Any]] = None


class BaseExporter(ABC):
    """리포트 exporter 기본 클래스"""

    @abstractmethod
    async def export(
        self,
        report: ResearchReport,
        output_path: Optional[str] = None,
        **options,
    ) -> bytes:
        """리포트를 bytes로 export (output_path 제공 시 파일로도 저장)"""
        pass

    @abstractmethod
    def get_mime_type(self) -> str:
        pass

    @abstractmethod
    def get_file_extension(self) -> str:
        pass


def escape_html(text: str) -> str:
    """HTML 텍스트 노드용 최소 이스케이프."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def safe_url(url: str) -> str:
    """http/https 만 허용하고 이스케이프한다. 그 외 스킴은 `#` 으로 대체.

    citations 의 `url` 은 웹 검색 결과에서 오는 **외부 데이터**다. 그대로
    `href` 에 넣으면 두 가지가 통과한다: `javascript:` URI (열어 본 사람의
    브라우저에서 실행), 그리고 따옴표가 살아 나가 속성을 닫고 `onmouseover=`
    같은 새 속성을 붙이는 것.

    이 함수는 `canvas_exporter._safe_url` 에 있던 것을 옮긴 것이다 (주석이
    `CR-P6-02: javascript: URI 차단` 이라고 적던 그 수정). **그 수정이 canvas
    한 곳에만 도착해 있었고 html 은 여전히 뚫려 있었다** -- 사본을 셋으로
    늘리지 않으려고 공용 자리로 올린다.
    """
    stripped = url.strip()
    if stripped.startswith(("http://", "https://")):
        return escape_html(stripped)
    return "#"

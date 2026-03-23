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

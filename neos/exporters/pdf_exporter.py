"""PDF Exporter using WeasyPrint"""

import logging
from typing import Optional

from .base import BaseExporter, ResearchReport
from .html_exporter import HTMLExporter

logger = logging.getLogger(__name__)


class PDFExporter(BaseExporter):
    """연구 리포트를 PDF로 export (WeasyPrint 기반)

    내부적으로 HTMLExporter로 HTML을 생성한 후 WeasyPrint로 PDF 변환.
    WeasyPrint가 설치되지 않은 경우 ImportError 발생.
    """

    def __init__(self):
        self.html_exporter = HTMLExporter()

    async def export(
        self,
        report: ResearchReport,
        output_path: Optional[str] = None,
        **options,
    ) -> bytes:
        try:
            from weasyprint import HTML as WeasyHTML
        except ImportError:
            raise ImportError(
                "WeasyPrint is required for PDF export. "
                "Install with: pip install weasyprint"
            )

        # HTML 생성
        html_content = await self.html_exporter.export(report)

        # PDF 변환
        html = WeasyHTML(string=html_content.decode("utf-8"))
        pdf_bytes = html.write_pdf()

        if output_path:
            with open(output_path, "wb") as f:
                f.write(pdf_bytes)

        return pdf_bytes

    def get_mime_type(self) -> str:
        return "application/pdf"

    def get_file_extension(self) -> str:
        return "pdf"

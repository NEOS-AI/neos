"""PDF Skill implementation"""

from typing import Dict, Any, List, Optional
import logging
from pathlib import Path

from neos.skills.base import BaseSkill, SkillResult, SkillType


logger = logging.getLogger(__name__)


class PdfSkill(BaseSkill):
    """PDF 문서 처리 스킬"""

    def __init__(self, **kwargs):
        super().__init__(
            name="pdf",
            skill_type=SkillType.DOCUMENT,
            description="PDF 문서 읽기, 텍스트 추출, 생성",
            capabilities=[
                "document_reading",
                "text_extraction",
                "pdf_parsing",
                "document_creation",
            ],
            version="1.0.0",
            **kwargs
        )
        self.pypdf2_available = False
        self.reportlab_available = False

    async def initialize(self) -> bool:
        """PDF 라이브러리 초기화"""
        try:
            # PyPDF2 임포트 시도
            import PyPDF2
            self.pypdf2_available = True

            # reportlab 임포트 시도
            try:
                from reportlab.pdfgen import canvas
                self.reportlab_available = True
            except ImportError:
                logger.warning(
                    "reportlab not available - PDF creation disabled"
                )

            self.is_available = True
            logger.info(
                f"PDF skill initialized successfully "
                f"(read: {self.pypdf2_available}, "
                f"create: {self.reportlab_available})"
            )
            return True

        except ImportError:
            logger.warning(
                "PDF skill not available: PyPDF2 package not installed"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to initialize PDF skill: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """PDF 작업 실행

        Args:
            params: {
                "action": str,  # "read", "extract_text", "create"
                "file_path": str,  # 파일 경로
                "page_numbers": list (optional),  # 페이지 번호
                "content": str (optional),  # PDF 내용
            }

        Returns:
            작업 실행 결과
        """
        if not self.is_available:
            return SkillResult.error_result(
                error="PDF skill not initialized",
                skill_name=self.name,
            )

        action = params.get("action")
        if not action:
            return SkillResult.error_result(
                error="Action parameter is required",
                skill_name=self.name,
            )

        if action == "read" or action == "extract_text":
            return await self._extract_text(params)
        elif action == "create":
            return await self._create_pdf(params)
        else:
            return SkillResult.error_result(
                error=f"Unknown action: {action}",
                skill_name=self.name,
            )

    async def _extract_text(self, params: Dict[str, Any]) -> SkillResult:
        """PDF에서 텍스트 추출"""
        import PyPDF2

        file_path = params.get("file_path")
        page_numbers = params.get("page_numbers")

        if not file_path:
            return SkillResult.error_result(
                error="file_path parameter is required",
                skill_name=self.name,
            )

        try:
            with open(file_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                num_pages = len(pdf_reader.pages)

                # 메타데이터 추출
                metadata = pdf_reader.metadata
                metadata_dict = {}
                if metadata:
                    metadata_dict = {
                        "title": metadata.get("/Title"),
                        "author": metadata.get("/Author"),
                        "subject": metadata.get("/Subject"),
                        "creator": metadata.get("/Creator"),
                    }

                # 페이지별 텍스트 추출
                pages_data = []
                pages_to_extract = (
                    page_numbers if page_numbers else range(num_pages)
                )

                for page_num in pages_to_extract:
                    if 0 <= page_num < num_pages:
                        page = pdf_reader.pages[page_num]
                        text = page.extract_text()
                        pages_data.append({
                            "page_number": page_num,
                            "text": text,
                            "text_length": len(text),
                        })

                # 전체 텍스트
                full_text = "\n\n".join(
                    [p["text"] for p in pages_data]
                )

                return SkillResult.success_result(
                    data={
                        "pages": pages_data,
                        "full_text": full_text,
                        "num_pages": num_pages,
                        "metadata": metadata_dict,
                    },
                    skill_name=self.name,
                    metadata={
                        "file_path": file_path,
                        "pages_extracted": len(pages_data),
                    },
                )

        except Exception as e:
            logger.error(f"Failed to extract text from PDF: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def _create_pdf(self, params: Dict[str, Any]) -> SkillResult:
        """새 PDF 파일 생성"""
        if not self.reportlab_available:
            return SkillResult.error_result(
                error="PDF creation not available (reportlab not installed)",
                skill_name=self.name,
            )

        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter

        file_path = params.get("file_path")
        content = params.get("content", "")

        if not file_path:
            return SkillResult.error_result(
                error="file_path parameter is required",
                skill_name=self.name,
            )

        try:
            c = canvas.Canvas(file_path, pagesize=letter)
            width, height = letter

            # 간단한 텍스트 추가
            text_object = c.beginText(40, height - 40)
            text_object.setFont("Helvetica", 12)

            # 줄바꿈 처리
            for line in content.split("\n"):
                text_object.textLine(line)

            c.drawText(text_object)
            c.save()

            return SkillResult.success_result(
                data={
                    "file_path": file_path,
                    "message": "PDF created successfully",
                },
                skill_name=self.name,
                metadata={"action": "create"},
            )

        except Exception as e:
            logger.error(f"Failed to create PDF: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def cleanup(self) -> None:
        """리소스 정리"""
        self.is_available = False
        logger.info("PDF skill cleaned up")

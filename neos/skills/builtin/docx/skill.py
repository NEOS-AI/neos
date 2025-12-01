"""DOCX Skill implementation"""

from typing import Dict, Any
import logging
from pathlib import Path

from neos.skills.base import BaseSkill, SkillResult, SkillType


logger = logging.getLogger(__name__)


class DocxSkill(BaseSkill):
    """Microsoft Word 문서 처리 스킬"""

    def __init__(self, **kwargs):
        super().__init__(
            name="docx",
            skill_type=SkillType.DOCUMENT,
            description="Microsoft Word 문서 읽기, 생성, 편집",
            capabilities=[
                "document_reading",
                "document_creation",
                "document_editing",
                "text_extraction",
            ],
            version="1.0.0",
            **kwargs
        )
        self.docx_available = False

    async def initialize(self) -> bool:
        """DOCX 라이브러리 초기화"""
        try:
            # python-docx 임포트 시도
            import docx

            self.docx_available = True
            self.is_available = True
            logger.info("DOCX skill initialized successfully")
            return True

        except ImportError:
            logger.warning(
                "DOCX skill not available: "
                "python-docx package not installed"
            )
            return False
        except Exception as e:
            logger.error(f"Failed to initialize DOCX skill: {e}")
            return False

    async def execute(self, params: Dict[str, Any]) -> SkillResult:
        """DOCX 작업 실행

        Args:
            params: {
                "action": str,  # "read", "create", "update"
                "file_path": str,  # 파일 경로
                "content": str (optional),  # 내용
                "options": dict (optional),  # 추가 옵션
            }

        Returns:
            작업 실행 결과
        """
        if not self.is_available:
            return SkillResult.error_result(
                error="DOCX skill not initialized",
                skill_name=self.name,
            )

        action = params.get("action")
        if not action:
            return SkillResult.error_result(
                error="Action parameter is required",
                skill_name=self.name,
            )

        if action == "read":
            return await self._read_docx(params)
        elif action == "create":
            return await self._create_docx(params)
        elif action == "update":
            return await self._update_docx(params)
        else:
            return SkillResult.error_result(
                error=f"Unknown action: {action}",
                skill_name=self.name,
            )

    async def _read_docx(self, params: Dict[str, Any]) -> SkillResult:
        """DOCX 파일 읽기"""
        from docx import Document

        file_path = params.get("file_path")
        if not file_path:
            return SkillResult.error_result(
                error="file_path parameter is required",
                skill_name=self.name,
            )

        try:
            doc = Document(file_path)

            # 텍스트 추출
            paragraphs = []
            for para in doc.paragraphs:
                if para.text.strip():
                    paragraphs.append({
                        "text": para.text,
                        "style": para.style.name
                    })

            # 표 추출
            tables = []
            for table in doc.tables:
                table_data = []
                for row in table.rows:
                    row_data = [cell.text for cell in row.cells]
                    table_data.append(row_data)
                tables.append(table_data)

            return SkillResult.success_result(
                data={
                    "paragraphs": paragraphs,
                    "tables": tables,
                    "num_paragraphs": len(paragraphs),
                    "num_tables": len(tables),
                },
                skill_name=self.name,
                metadata={"file_path": file_path},
            )

        except Exception as e:
            logger.error(f"Failed to read DOCX file: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def _create_docx(self, params: Dict[str, Any]) -> SkillResult:
        """새 DOCX 파일 생성"""
        from docx import Document

        file_path = params.get("file_path")
        content = params.get("content", "")
        options = params.get("options", {})

        if not file_path:
            return SkillResult.error_result(
                error="file_path parameter is required",
                skill_name=self.name,
            )

        try:
            doc = Document()

            # 제목 추가
            if "heading" in options:
                doc.add_heading(options["heading"], level=1)

            # 내용 추가
            if content:
                doc.add_paragraph(content)

            # 파일 저장
            doc.save(file_path)

            return SkillResult.success_result(
                data={
                    "file_path": file_path,
                    "message": "Document created successfully",
                },
                skill_name=self.name,
                metadata={"action": "create"},
            )

        except Exception as e:
            logger.error(f"Failed to create DOCX file: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def _update_docx(self, params: Dict[str, Any]) -> SkillResult:
        """기존 DOCX 파일 업데이트"""
        from docx import Document

        file_path = params.get("file_path")
        content = params.get("content", "")

        if not file_path:
            return SkillResult.error_result(
                error="file_path parameter is required",
                skill_name=self.name,
            )

        try:
            doc = Document(file_path)

            # 내용 추가
            if content:
                doc.add_paragraph(content)

            # 파일 저장
            doc.save(file_path)

            return SkillResult.success_result(
                data={
                    "file_path": file_path,
                    "message": "Document updated successfully",
                },
                skill_name=self.name,
                metadata={"action": "update"},
            )

        except Exception as e:
            logger.error(f"Failed to update DOCX file: {e}")
            return SkillResult.error_result(
                error=str(e),
                skill_name=self.name,
            )

    async def cleanup(self) -> None:
        """리소스 정리"""
        self.is_available = False
        logger.info("DOCX skill cleaned up")

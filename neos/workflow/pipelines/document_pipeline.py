"""
문서 처리 파이프라인

PDF, DOCX, PPT, XLS 등 다양한 문서 파일을 처리합니다.
"""

from typing import Dict, Any
from pathlib import Path

from .base import (
    BasePipeline,
    InputType,
    PipelineContext,
    PipelineResult,
    ProcessingStage,
    FileInput
)
from .pdf_parser import PDFParser


class DocumentPipeline(BasePipeline):
    """
    문서 처리 파이프라인

    다양한 문서 포맷을 파싱하고 텍스트와 메타데이터를 추출합니다.
    """

    # 지원하는 문서 포맷
    SUPPORTED_FORMATS = {
        ".pdf": "pdf",
        ".doc": "word",
        ".docx": "word",
        ".xls": "excel",
        ".xlsx": "excel",
        ".ppt": "powerpoint",
        ".pptx": "powerpoint",
        ".csv": "csv",
        ".txt": "text",
        ".md": "markdown",
    }

    # 최대 파일 크기 (바이트)
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

    def __init__(self):
        super().__init__(name="DocumentPipeline", input_type=InputType.DOCUMENT)
        self.pdf_parser = PDFParser()

    async def validate(self, context: PipelineContext) -> bool:
        """문서 입력 검증"""
        if not context.files or len(context.files) == 0:
            return False

        file = context.files[0]

        # 파일 크기 확인
        if file.file_size and file.file_size > self.MAX_FILE_SIZE:
            return False

        # 파일 포맷 확인
        if file.filename:
            ext = Path(file.filename).suffix.lower()
            if ext not in self.SUPPORTED_FORMATS:
                return False

        return True

    async def preprocess(self, context: PipelineContext) -> PipelineContext:
        """문서 전처리"""
        file = context.files[0]

        # 문서 타입 결정
        ext = Path(file.filename).suffix.lower()
        doc_type = self.SUPPORTED_FORMATS.get(ext, "unknown")

        context.additional_context["document_type"] = doc_type
        context.additional_context["file_extension"] = ext

        return context

    async def extract(self, context: PipelineContext) -> PipelineResult:
        """문서에서 정보 추출"""
        file = context.files[0]
        doc_type = context.additional_context.get("document_type")

        # 문서 타입별 추출 로직
        if doc_type == "pdf":
            extracted_data = await self._extract_pdf(file, context)
        elif doc_type == "word":
            extracted_data = await self._extract_word(file, context)
        elif doc_type == "excel":
            extracted_data = await self._extract_excel(file, context)
        elif doc_type == "powerpoint":
            extracted_data = await self._extract_powerpoint(file, context)
        elif doc_type == "csv":
            extracted_data = await self._extract_csv(file, context)
        elif doc_type in ("text", "markdown"):
            extracted_data = await self._extract_text(file, context)
        else:
            extracted_data = {"error": "Unsupported document type"}

        # 결과 생성
        result = PipelineResult(
            success=True,
            input_type=InputType.DOCUMENT,
            stage=ProcessingStage.EXTRACTION,
            extracted_text=extracted_data.get("text", ""),
            extracted_data=extracted_data,
            metadata={
                "filename": file.filename,
                "mime_type": file.mime_type,
                "file_size": file.file_size,
                "document_type": doc_type,
                "page_count": extracted_data.get("page_count"),
                "has_images": extracted_data.get("has_images", False),
                "has_tables": extracted_data.get("has_tables", False),
            }
        )

        return result

    async def analyze(self, result: PipelineResult, context: PipelineContext) -> PipelineResult:
        """문서 분석"""
        doc_type = context.additional_context.get("document_type")

        # 분석 정보
        analysis = {
            "document_type": doc_type,
            "text_length": len(result.extracted_text) if result.extracted_text else 0,
            "structure": self._analyze_structure(result.extracted_data),
            "complexity": self._assess_complexity(result.extracted_data),
        }

        result.analysis = analysis

        # 인사이트 생성
        insights = []
        insights.append(f"Document type: {doc_type}")

        if result.metadata.get("page_count"):
            insights.append(f"Total pages: {result.metadata['page_count']}")

        if result.metadata.get("has_tables"):
            insights.append("Contains tables - structured data extraction available")

        if result.metadata.get("has_images"):
            insights.append("Contains images - vision model analysis recommended")

        result.insights = insights

        # 통합 컨텍스트 생성
        text_preview = result.extracted_text[:500] if result.extracted_text else "No text extracted"

        result.unified_context = f"""
**Document Analysis Request**

**Query**: {context.query}

**Document Metadata**:
- Filename: {result.metadata.get('filename')}
- Type: {doc_type}
- Size: {result.metadata.get('file_size')} bytes
- Pages: {result.metadata.get('page_count', 'N/A')}

**Extracted Text Preview**:
{text_preview}...

**Additional Info**:
- Has Tables: {result.metadata.get('has_tables', False)}
- Has Images: {result.metadata.get('has_images', False)}
"""

        return result

    async def _extract_pdf(self, file: FileInput, context: PipelineContext) -> Dict[str, Any]:
        """
        PDF 문서 추출

        PyPDF2를 사용하여 PDF에서 텍스트와 메타데이터를 추출합니다.
        """
        # PDF 파서 사용 가능 여부 확인
        if not self.pdf_parser.is_available():
            return {
                "text": "PyPDF2 is not installed. Install it with: pip install PyPDF2",
                "page_count": 0,
                "has_images": False,
                "has_tables": False,
                "error": "PyPDF2 not installed",
                "installation_command": "pip install PyPDF2"
            }

        try:
            # PDF 파싱 실행
            result = await self.pdf_parser.parse(
                file_content=file.file_content,
                file_path=file.file_path
            )

            # 결과 반환
            return {
                "text": result.get("text", ""),
                "page_count": result.get("page_count", 0),
                "has_images": result.get("has_images", False),
                "has_tables": result.get("has_tables", False),
                "metadata": result.get("metadata", {}),
                "pages": result.get("pages", []),
                "char_count": result.get("char_count", 0),
                "word_count": result.get("word_count", 0),
                "is_encrypted": result.get("is_encrypted", False),
                "extraction_method": "PyPDF2",
            }

        except Exception as e:
            return {
                "text": "",
                "page_count": 0,
                "has_images": False,
                "has_tables": False,
                "error": f"PDF extraction failed: {str(e)}",
                "extraction_method": "PyPDF2",
            }

    async def _extract_word(self, file: FileInput, context: PipelineContext) -> Dict[str, Any]:
        """
        Word 문서 추출

        TODO: python-docx 통합
        """
        return {
            "text": "Word document extraction not yet implemented",
            "page_count": None,
            "has_images": False,
            "has_tables": False,
            "implementation_needed": "python-docx"
        }

    async def _extract_excel(self, file: FileInput, context: PipelineContext) -> Dict[str, Any]:
        """
        Excel 문서 추출

        TODO: openpyxl or pandas 통합
        """
        return {
            "text": "Excel extraction not yet implemented",
            "sheet_count": None,
            "has_charts": False,
            "implementation_needed": "openpyxl or pandas"
        }

    async def _extract_powerpoint(self, file: FileInput, context: PipelineContext) -> Dict[str, Any]:
        """
        PowerPoint 문서 추출

        TODO: python-pptx 통합
        """
        return {
            "text": "PowerPoint extraction not yet implemented",
            "slide_count": None,
            "has_images": False,
            "implementation_needed": "python-pptx"
        }

    async def _extract_csv(self, file: FileInput, context: PipelineContext) -> Dict[str, Any]:
        """
        CSV 파일 추출

        TODO: pandas 통합
        """
        return {
            "text": "CSV extraction not yet implemented",
            "row_count": None,
            "column_count": None,
            "implementation_needed": "pandas"
        }

    async def _extract_text(self, file: FileInput, context: PipelineContext) -> Dict[str, Any]:
        """텍스트 파일 추출 (간단 구현)"""
        try:
            if file.file_content:
                text = file.file_content.decode("utf-8")
            elif file.file_path:
                with open(file.file_path, "r", encoding="utf-8") as f:
                    text = f.read()
            else:
                return {"error": "No file content or path"}

            return {
                "text": text,
                "line_count": len(text.split("\n")),
                "char_count": len(text),
            }
        except Exception as e:
            return {"error": str(e)}

    def _analyze_structure(self, extracted_data: Dict[str, Any]) -> str:
        """문서 구조 분석"""
        if extracted_data.get("has_tables"):
            return "structured"
        elif extracted_data.get("page_count"):
            return "multi-page"
        else:
            return "simple"

    def _assess_complexity(self, extracted_data: Dict[str, Any]) -> str:
        """문서 복잡도 평가"""
        complexity_score = 0

        if extracted_data.get("has_tables"):
            complexity_score += 2
        if extracted_data.get("has_images"):
            complexity_score += 1
        if extracted_data.get("page_count", 0) > 10:
            complexity_score += 2

        if complexity_score >= 4:
            return "high"
        elif complexity_score >= 2:
            return "medium"
        else:
            return "low"

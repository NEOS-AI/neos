"""
문서 처리 파이프라인

PDF, DOCX, PPT, XLS 등 다양한 문서 파일을 처리합니다.
"""

from typing import Dict, Any, List
from pathlib import Path
import base64

from .base import (
    BasePipeline,
    InputType,
    PipelineContext,
    PipelineResult,
    ProcessingStage,
    FileInput
)
from .pdf_parser import PDFParser
from .word_parser import WordParser
from .excel_parser import ExcelParser
from .csv_parser import CSVParser
from .ppt_parser import PPTParser
from .vision.vision_factory import VisionModelFactory, VisionProvider


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
        self.word_parser = WordParser()
        self.excel_parser = ExcelParser()
        self.csv_parser = CSVParser()
        self.ppt_parser = PPTParser()
        self.vision_enabled = True  # Vision 분석 활성화 여부

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
        if not doc_type or doc_type not in self.SUPPORTED_FORMATS.values():
            return PipelineResult(
                success=False,
                input_type=InputType.DOCUMENT,
                stage=ProcessingStage.EXTRACTION,
                error="Unsupported or unknown document type"
            )

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
            vision_analysis = result.extracted_data.get("vision_analysis", [])
            if vision_analysis:
                insights.append(f"Contains {len(vision_analysis)} analyzed image(s) - Vision analysis completed")
            else:
                insights.append("Contains images - Vision model analysis available")

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

            # 이미지가 있으면 Vision 모델로 분석
            vision_results = []
            images = result.get("images", [])
            if images:
                vision_results = await self._analyze_images_with_vision(images, context)

            # 결과 반환
            return {
                "text": result.get("text", ""),
                "page_count": result.get("page_count", 0),
                "has_images": result.get("has_images", False),
                "has_tables": result.get("has_tables", False),
                "metadata": result.get("metadata", {}),
                "pages": result.get("pages", []),
                "tables": result.get("tables", []),
                "images": images,
                "vision_analysis": vision_results,
                "char_count": result.get("char_count", 0),
                "word_count": result.get("word_count", 0),
                "is_encrypted": result.get("is_encrypted", False),
                "extraction_method": result.get("extraction_method", "PyPDF2"),
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

        python-docx를 사용하여 Word 문서에서 텍스트, 테이블, 스타일 정보를 추출합니다.
        """
        # Word 파서 사용 가능 여부 확인
        if not self.word_parser.is_available():
            return {
                "text": "python-docx is not installed. Install it with: pip install python-docx",
                "paragraph_count": 0,
                "has_images": False,
                "has_tables": False,
                "error": "python-docx not installed",
                "installation_command": "pip install python-docx"
            }

        try:
            # Word 파싱 실행
            result = await self.word_parser.parse(
                file_content=file.file_content,
                file_path=file.file_path
            )

            # 이미지가 있으면 Vision 모델로 분석
            vision_results = []
            images = result.get("images", [])
            if images:
                vision_results = await self._analyze_images_with_vision(images, context)

            # 결과 반환
            return {
                "text": result.get("text", ""),
                "paragraph_count": result.get("paragraph_count", 0),
                "char_count": result.get("char_count", 0),
                "word_count": result.get("word_count", 0),
                "has_images": result.get("has_images", False),
                "has_tables": result.get("has_tables", False),
                "table_count": result.get("table_count", 0),
                "tables": result.get("tables", []),
                "images": images,
                "vision_analysis": vision_results,
                "metadata": result.get("metadata", {}),
                "styles": result.get("styles", {}),
                "extraction_method": "python-docx",
            }

        except Exception as e:
            return {
                "text": "",
                "paragraph_count": 0,
                "has_images": False,
                "has_tables": False,
                "error": f"Word extraction failed: {str(e)}",
                "extraction_method": "python-docx",
            }

    async def _extract_excel(self, file: FileInput, context: PipelineContext) -> Dict[str, Any]:
        """
        Excel 문서 추출

        openpyxl을 사용하여 Excel 파일에서 데이터, 수식, 차트 정보를 추출합니다.
        """
        # Excel 파서 사용 가능 여부 확인
        if not self.excel_parser.is_available():
            return {
                "text": "openpyxl is not installed. Install it with: pip install openpyxl",
                "sheet_count": 0,
                "has_charts": False,
                "has_tables": False,
                "error": "openpyxl not installed",
                "installation_command": "pip install openpyxl"
            }

        try:
            # Excel 파싱 실행
            result = await self.excel_parser.parse(
                file_content=file.file_content,
                file_path=file.file_path
            )

            # 결과 반환
            return {
                "text": result.get("text", ""),
                "sheet_count": result.get("sheet_count", 0),
                "sheet_names": result.get("sheet_names", []),
                "sheets": result.get("sheets", []),
                "has_formulas": result.get("has_formulas", False),
                "has_charts": result.get("has_charts", False),
                "has_tables": result.get("sheet_count", 0) > 0,  # Excel 시트는 테이블로 간주
                "metadata": result.get("metadata", {}),
                "total_rows": result.get("total_rows", 0),
                "total_cols": result.get("total_cols", 0),
                "extraction_method": "openpyxl",
            }

        except Exception as e:
            return {
                "text": "",
                "sheet_count": 0,
                "has_charts": False,
                "has_tables": False,
                "error": f"Excel extraction failed: {str(e)}",
                "extraction_method": "openpyxl",
            }

    async def _extract_powerpoint(self, file: FileInput, context: PipelineContext) -> Dict[str, Any]:
        """
        PowerPoint 문서 추출

        python-pptx를 사용하여 PowerPoint 파일에서 텍스트, 이미지, 노트를 추출합니다.
        """
        # PPT 파서 사용 가능 여부 확인
        if not self.ppt_parser.is_available():
            return {
                "text": "python-pptx is not installed. Install it with: pip install python-pptx",
                "slide_count": 0,
                "has_images": False,
                "has_tables": False,
                "error": "python-pptx not installed",
                "installation_command": "pip install python-pptx"
            }

        try:
            # PPT 파싱 실행
            result = await self.ppt_parser.parse(
                file_content=file.file_content,
                file_path=file.file_path
            )

            # 이미지가 있으면 Vision 모델로 분석
            vision_results = []
            images = result.get("images", [])
            if images:
                vision_results = await self._analyze_images_with_vision(images, context)

            # 결과 반환
            return {
                "text": result.get("text", ""),
                "slide_count": result.get("slide_count", 0),
                "slides": result.get("slides", []),
                "images": images,
                "vision_analysis": vision_results,
                "has_images": result.get("has_images", False),
                "has_tables": result.get("has_tables", False),
                "has_notes": result.get("has_notes", False),
                "metadata": result.get("metadata", {}),
                "total_shapes": result.get("total_shapes", 0),
                "extraction_method": "python-pptx",
            }

        except Exception as e:
            return {
                "text": "",
                "slide_count": 0,
                "has_images": False,
                "has_tables": False,
                "error": f"PowerPoint extraction failed: {str(e)}",
                "extraction_method": "python-pptx",
            }

    async def _extract_csv(self, file: FileInput, context: PipelineContext) -> Dict[str, Any]:
        """
        CSV 파일 추출

        pandas를 사용하여 CSV 파일에서 데이터와 통계 정보를 추출합니다.
        """
        # CSV 파서 사용 가능 여부 확인
        if not self.csv_parser.is_available():
            return {
                "text": "pandas is not installed. Install it with: pip install pandas",
                "row_count": 0,
                "column_count": 0,
                "has_tables": False,
                "error": "pandas not installed",
                "installation_command": "pip install pandas"
            }

        try:
            # CSV 파싱 실행
            result = await self.csv_parser.parse(
                file_content=file.file_content,
                file_path=file.file_path
            )

            # 결과 반환
            return {
                "text": result.get("text", ""),
                "row_count": result.get("row_count", 0),
                "column_count": result.get("column_count", 0),
                "columns": result.get("columns", []),
                "data_preview": result.get("data_preview", []),
                "statistics": result.get("statistics", {}),
                "missing_values": result.get("missing_values", {}),
                "data_types": result.get("data_types", {}),
                "has_tables": True,  # CSV는 항상 테이블 형태
                "memory_usage": result.get("memory_usage", 0),
                "extraction_method": "pandas",
            }

        except Exception as e:
            return {
                "text": "",
                "row_count": 0,
                "column_count": 0,
                "has_tables": False,
                "error": f"CSV extraction failed: {str(e)}",
                "extraction_method": "pandas",
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

    async def _analyze_images_with_vision(
        self,
        images: List[Dict[str, Any]],
        context: PipelineContext,
        max_images: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Vision 모델을 사용하여 이미지 분석

        Args:
            images: 이미지 데이터 리스트 (image_bytes 포함)
            context: 파이프라인 컨텍스트
            max_images: 최대 분석할 이미지 수

        Returns:
            Vision 분석 결과 리스트
        """
        if not self.vision_enabled or not images:
            return []

        vision_results = []

        try:
            # Vision 모델 생성
            vision_model = VisionModelFactory.create(VisionProvider.AUTO)

            # 최대 이미지 수 제한
            images_to_analyze = images[:max_images]

            for img_data in images_to_analyze:
                try:
                    # 이미지 바이트를 base64로 인코딩
                    image_bytes = img_data.get("image_bytes")
                    if not image_bytes:
                        continue

                    image_base64 = base64.b64encode(image_bytes).decode("utf-8")

                    # Vision 모델로 이미지 분석
                    prompt = f"이 이미지를 분석하고 설명해주세요. 문서: {context.query}"

                    analysis = await vision_model.analyze_image(
                        image_data=image_base64,
                        prompt=prompt,
                        max_tokens=500,
                        filename=f"image.{img_data.get('ext', 'jpg')}",
                        mime_type=img_data.get('content_type', 'image/jpeg')
                    )

                    # 결과에 원본 이미지 정보 추가
                    result = {
                        "image_index": img_data.get("image_index", 0),
                        "page_number": img_data.get("page_number"),
                        "slide_number": img_data.get("slide_number"),
                        "size": img_data.get("size"),
                        "ext": img_data.get("ext"),
                        "vision_analysis": analysis,
                    }
                    vision_results.append(result)

                except Exception as e:
                    # 개별 이미지 분석 실패는 건너뜀
                    print(f"[Vision Analysis] Failed to analyze image: {str(e)}")
                    continue

        except Exception as e:
            # Vision 모델 초기화 실패 등
            print(f"[Vision Analysis] Vision model not available: {str(e)}")
            return []

        return vision_results

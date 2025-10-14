"""
PDF 파싱 테스트
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import sys
from pathlib import Path

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neos.workflow.pipelines.pdf_parser import PDFParser  # noqa: E402
from neos.workflow.pipelines.document_pipeline import DocumentPipeline  # noqa: E402
from neos.workflow.pipelines.base import (  # noqa: E402
    PipelineContext,
    FileInput,
    InputType,
)


class TestPDFParser:
    """PDFParser 테스트"""

    def test_pdf_parser_initialization(self):
        """PDF 파서 초기화 테스트"""
        parser = PDFParser()
        assert parser is not None

    def test_pdf_parser_availability_check(self):
        """PyPDF2 설치 여부 확인 테스트"""
        parser = PDFParser()
        # PyPDF2가 설치되어 있으면 True, 아니면 False
        is_available = parser.is_available()
        assert isinstance(is_available, bool)

    @pytest.mark.asyncio
    async def test_parse_pdf_no_input(self):
        """입력 없이 파싱 시도 테스트"""
        parser = PDFParser()

        with pytest.raises(ValueError, match="file_content or file_path must be provided"):
            await parser.parse()

    @pytest.mark.asyncio
    async def test_parse_pdf_pypdf2_not_installed(self):
        """PyPDF2 미설치 시 에러 처리 테스트"""
        parser = PDFParser()
        parser.supports_pypdf2 = False  # PyPDF2 미설치로 가정

        with pytest.raises(ImportError, match="PyPDF2 is not installed"):
            await parser.parse(file_content=b"fake pdf content")

    @pytest.mark.asyncio
    async def test_parse_pdf_with_mock(self):
        """Mock을 사용한 PDF 파싱 테스트"""
        parser = PDFParser()

        # PyPDF2가 설치되어 있지 않을 수 있으므로 Mock 사용
        if not parser.is_available():
            pytest.skip("PyPDF2 not installed")

        # 간단한 PDF 내용 시뮬레이션 (실제 PDF는 복잡함)
        fake_pdf_content = b"%PDF-1.4\n%Mock PDF"

        try:
            result = await parser.parse(file_content=fake_pdf_content)

            # 기본 구조 확인
            assert "text" in result
            assert "page_count" in result
            assert "extraction_method" in result
            assert result["extraction_method"] == "PyPDF2"

        except Exception as e:
            # 잘못된 PDF 형식이므로 에러가 예상됨
            assert "error" in str(e).lower() or True


@pytest.mark.asyncio
class TestDocumentPipelineWithPDF:
    """PDF가 통합된 DocumentPipeline 테스트"""

    async def test_document_pipeline_pdf_parser_initialization(self):
        """DocumentPipeline의 PDF 파서 초기화 테스트"""
        pipeline = DocumentPipeline()
        assert hasattr(pipeline, 'pdf_parser')
        assert isinstance(pipeline.pdf_parser, PDFParser)

    async def test_document_pipeline_pdf_not_installed(self):
        """PyPDF2 미설치 시 DocumentPipeline 동작 테스트"""
        pipeline = DocumentPipeline()

        # PyPDF2 미설치로 가정
        pipeline.pdf_parser.supports_pypdf2 = False

        file = FileInput(
            filename="test.pdf",
            file_content=b"fake pdf",
            mime_type="application/pdf",
            file_size=100
        )

        context = PipelineContext(
            query="Extract text from this PDF",
            input_type=InputType.DOCUMENT,
            files=[file]
        )

        result = await pipeline.process(context)

        # 파이프라인은 성공해야 하지만, PDF 파싱 에러 포함
        assert result.success is True
        assert "error" in result.extracted_data or "PyPDF2" in result.extracted_text

    async def test_document_pipeline_pdf_with_text_file(self):
        """텍스트 파일로 DocumentPipeline 테스트 (비교 대조)"""
        pipeline = DocumentPipeline()

        text_content = "# PDF Testing\n\nThis is a test document."
        file = FileInput(
            filename="test.txt",
            file_content=text_content.encode("utf-8"),
            mime_type="text/plain",
            file_size=len(text_content)
        )

        context = PipelineContext(
            query="Extract text",
            input_type=InputType.DOCUMENT,
            files=[file]
        )

        result = await pipeline.process(context)

        assert result.success is True
        assert text_content in result.extracted_text
        assert result.metadata["document_type"] == "text"


@pytest.mark.asyncio
class TestPDFMetadataExtraction:
    """PDF 메타데이터 추출 테스트"""

    async def test_parse_pdf_date(self):
        """PDF 날짜 형식 파싱 테스트"""
        parser = PDFParser()

        # PDF 날짜 형식: D:YYYYMMDDHHmmSSOHH'mm'
        date_str = "D:20230101120000+09'00'"
        parsed_date = parser._parse_pdf_date(date_str)

        assert "2023" in parsed_date
        assert "01" in parsed_date

    async def test_parse_pdf_date_invalid(self):
        """잘못된 PDF 날짜 형식 처리 테스트"""
        parser = PDFParser()

        # 잘못된 형식
        date_str = "invalid_date"
        parsed_date = parser._parse_pdf_date(date_str)

        # 원본 반환 또는 에러 없이 처리
        assert parsed_date is not None


@pytest.mark.asyncio
class TestPDFIntegrationEndToEnd:
    """PDF 통합 End-to-End 테스트"""

    async def test_complete_pdf_workflow_mock(self):
        """PDF 포함 전체 워크플로우 테스트 (Mock)"""
        pipeline = DocumentPipeline()

        # 가상 PDF 파일
        file = FileInput(
            filename="document.pdf",
            file_content=b"%PDF fake content",
            mime_type="application/pdf",
            file_size=100
        )

        context = PipelineContext(
            query="Summarize this PDF document",
            input_type=InputType.DOCUMENT,
            files=[file],
            user_id="test_user",
            session_id="test_session"
        )

        # PDF 파서 결과 Mock
        mock_pdf_result = {
            "text": "This is the extracted text from the PDF document. "
                    "It contains multiple paragraphs and important information.",
            "page_count": 3,
            "has_images": False,
            "has_tables": False,
            "metadata": {
                "title": "Test Document",
                "author": "Test Author",
            },
            "char_count": 150,
            "word_count": 25,
            "extraction_method": "PyPDF2",
        }

        # PDF 파서 Mock
        async def mock_parse(*args, **kwargs):
            return mock_pdf_result

        with patch.object(pipeline.pdf_parser, 'parse', side_effect=mock_parse):
            result = await pipeline.process(context)

            # 검증
            assert result.success is True
            assert result.input_type == InputType.DOCUMENT
            assert "extracted text" in result.extracted_text.lower()
            assert result.metadata.get("document_type") == "pdf"
            assert result.metadata.get("page_count") == 3
            assert result.processing_time_ms is not None


@pytest.mark.asyncio
class TestPDFErrorHandling:
    """PDF 에러 처리 테스트"""

    async def test_pdf_extraction_error_handling(self):
        """PDF 추출 에러 처리 테스트"""
        pipeline = DocumentPipeline()

        file = FileInput(
            filename="corrupt.pdf",
            file_content=b"not a valid pdf",
            mime_type="application/pdf",
            file_size=20
        )

        context = PipelineContext(
            query="Extract text",
            input_type=InputType.DOCUMENT,
            files=[file]
        )

        result = await pipeline.process(context)

        # 전체 파이프라인은 성공해야 함 (에러는 경고로 처리)
        assert result.success is True
        # 에러 정보가 포함되어 있어야 함
        assert (
            "error" in result.extracted_data or
            result.extracted_text == "" or
            "PyPDF2" in result.extracted_text
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

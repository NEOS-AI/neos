"""
파이프라인 시스템 테스트
"""

import pytest
from pathlib import Path
import io
from PIL import Image
import sys

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neos.workflow.pipelines import (  # noqa: E402
    InputRouter,
    TextPipeline,
    ImagePipeline,
    DocumentPipeline,
    AudioPipeline,
    MultiModalPipeline,
    UnifiedContextLayer,
    PipelineContext,
    FileInput,
    InputType,
    PipelineRegistry,
)


class TestInputRouter:
    """InputRouter 테스트"""

    def test_text_classification(self):
        """텍스트 입력 분류 테스트"""
        router = InputRouter()
        input_type = router.classify_input("Hello, how are you?", files=None)
        assert input_type == InputType.TEXT

    def test_image_classification(self):
        """이미지 파일 분류 테스트"""
        router = InputRouter()

        file = FileInput(
            filename="test.jpg",
            mime_type="image/jpeg",
            file_size=1024
        )

        input_type = router.classify_input("Analyze this image", files=[file])
        assert input_type == InputType.IMAGE

    def test_document_classification(self):
        """문서 파일 분류 테스트"""
        router = InputRouter()

        file = FileInput(
            filename="document.pdf",
            mime_type="application/pdf",
            file_size=2048
        )

        input_type = router.classify_input("Summarize this document", files=[file])
        assert input_type == InputType.DOCUMENT

    def test_multimodal_classification(self):
        """멀티모달 입력 분류 테스트"""
        router = InputRouter()

        files = [
            FileInput(filename="image.jpg", mime_type="image/jpeg"),
            FileInput(filename="document.pdf", mime_type="application/pdf"),
        ]

        input_type = router.classify_input("Analyze these files", files=files)
        assert input_type == InputType.MULTIMODAL


@pytest.mark.asyncio
class TestTextPipeline:
    """TextPipeline 테스트"""

    async def test_text_processing(self):
        """텍스트 처리 테스트"""
        pipeline = TextPipeline()

        context = PipelineContext(
            query="What is AI?",
            input_type=InputType.TEXT,
        )

        result = await pipeline.process(context)

        assert result.success is True
        assert result.extracted_text == "What is AI?"
        assert result.metadata["word_count"] == 3
        assert "language" in result.metadata

    async def test_text_validation(self):
        """텍스트 검증 테스트"""
        pipeline = TextPipeline()

        # 빈 쿼리
        context = PipelineContext(query="", input_type=InputType.TEXT)
        is_valid = await pipeline.validate(context)
        assert is_valid is False

        # 정상 쿼리
        context = PipelineContext(query="Hello", input_type=InputType.TEXT)
        is_valid = await pipeline.validate(context)
        assert is_valid is True


@pytest.mark.asyncio
class TestImagePipeline:
    """ImagePipeline 테스트"""

    async def test_image_processing(self):
        """이미지 처리 테스트"""
        pipeline = ImagePipeline()

        # 테스트 이미지 생성
        img = Image.new("RGB", (100, 100), color="red")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes = img_bytes.getvalue()

        file = FileInput(
            filename="test.png",
            file_content=img_bytes,
            mime_type="image/png",
            file_size=len(img_bytes)
        )

        context = PipelineContext(
            query="What's in this image?",
            input_type=InputType.IMAGE,
            files=[file]
        )

        result = await pipeline.process(context)

        assert result.success is True
        assert result.metadata.get("filename") == "test.png"
        assert result.metadata.get("original_size") == (100, 100)
        assert result.metadata.get("format") == "PNG"


@pytest.mark.asyncio
class TestDocumentPipeline:
    """DocumentPipeline 테스트"""

    async def test_text_file_processing(self):
        """텍스트 파일 처리 테스트"""
        pipeline = DocumentPipeline()

        text_content = "This is a test document.\nWith multiple lines."
        file = FileInput(
            filename="test.txt",
            file_content=text_content.encode("utf-8"),
            mime_type="text/plain",
            file_size=len(text_content)
        )

        context = PipelineContext(
            query="Summarize this document",
            input_type=InputType.DOCUMENT,
            files=[file]
        )

        result = await pipeline.process(context)

        assert result.success is True
        assert text_content in result.extracted_text


@pytest.mark.asyncio
class TestUnifiedContextLayer:
    """UnifiedContextLayer 테스트"""

    async def test_context_unification(self):
        """컨텍스트 통합 테스트"""
        layer = UnifiedContextLayer()

        # 텍스트 파이프라인 결과 생성
        pipeline = TextPipeline()
        context = PipelineContext(
            query="Test query",
            input_type=InputType.TEXT,
            user_id="user123",
            session_id="session456"
        )
        result = await pipeline.process(context)

        # 통합
        unified = layer.unify(result, context)

        assert unified["original_query"] == "Test query"
        assert unified["user_id"] == "user123"
        assert unified["session_id"] == "session456"
        assert unified["pipeline_metadata"]["input_type"] == "text"
        assert unified["pipeline_metadata"]["success"] is True

    async def test_workflow_state_creation(self):
        """워크플로우 상태 생성 테스트"""
        layer = UnifiedContextLayer()

        # 텍스트 파이프라인 결과 생성
        pipeline = TextPipeline()
        context = PipelineContext(
            query="Test query",
            input_type=InputType.TEXT,
            user_id="user123",
            session_id="session456"
        )
        result = await pipeline.process(context)

        # 통합 및 워크플로우 상태 생성
        unified = layer.unify(result, context)
        workflow_state = layer.create_workflow_state(unified)

        assert workflow_state["user_id"] == "user123"
        assert workflow_state["session_id"] == "session456"
        assert workflow_state["original_query"] == "Test query"
        assert "pipeline_context" in workflow_state


@pytest.mark.asyncio
class TestPipelineRegistry:
    """PipelineRegistry 테스트"""

    def test_pipeline_registration(self):
        """파이프라인 등록 테스트"""
        registry = PipelineRegistry()

        text_pipeline = TextPipeline()
        registry.register(InputType.TEXT, text_pipeline)

        retrieved = registry.get(InputType.TEXT)
        assert retrieved is text_pipeline

    def test_get_all_pipelines(self):
        """모든 파이프라인 조회 테스트"""
        registry = PipelineRegistry()

        registry.register(InputType.TEXT, TextPipeline())
        registry.register(InputType.IMAGE, ImagePipeline())

        all_pipelines = registry.get_all()
        assert len(all_pipelines) >= 2
        assert InputType.TEXT in all_pipelines
        assert InputType.IMAGE in all_pipelines


@pytest.mark.asyncio
class TestMultiModalPipeline:
    """MultiModalPipeline 테스트"""

    async def test_multimodal_grouping(self):
        """파일 타입별 그룹핑 테스트"""
        pipeline = MultiModalPipeline()

        files = [
            FileInput(filename="image.jpg", mime_type="image/jpeg"),
            FileInput(filename="doc.pdf", mime_type="application/pdf"),
            FileInput(filename="audio.mp3", mime_type="audio/mpeg"),
        ]

        grouped = pipeline._group_files_by_type(files)

        assert InputType.IMAGE in grouped
        assert InputType.DOCUMENT in grouped
        assert InputType.AUDIO in grouped


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

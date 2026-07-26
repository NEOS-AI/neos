"""
Vision 모델 통합 테스트
"""

import pytest
import io
from PIL import Image
from unittest.mock import AsyncMock, patch, MagicMock

from neos.workflow.pipelines import (
    ImagePipeline,
    VisionProvider,
    GPT4oVision,
    ClaudeVision,
    VisionModelFactory,
    PipelineContext,
    FileInput,
    InputType,
)


@pytest.mark.asyncio
class TestVisionModels:
    """Vision 모델 테스트"""

    async def test_gpt4o_vision_initialization(self):
        """GPT-4o Vision 초기화 테스트"""
        vision = GPT4oVision(api_key="test_key")
        assert vision.model == "gpt-4o"
        assert vision.api_key == "test_key"
        assert vision.is_available() is True

    async def test_claude_vision_initialization(self):
        """Claude Vision 초기화 테스트"""
        vision = ClaudeVision(api_key="test_key")
        # neos/config/models.yaml의 vision_models.claude 값
        assert vision.model == "claude-sonnet-5"
        assert vision.api_key == "test_key"
        assert vision.is_available() is True

    async def test_vision_model_factory_gpt4o(self):
        """VisionModelFactory GPT-4o 생성 테스트"""
        with patch("neos.config.settings.settings.OPENAI_API_KEY", "test_key"):
            model = VisionModelFactory.create(VisionProvider.GPT4O)
            assert isinstance(model, GPT4oVision)

    async def test_vision_model_factory_claude(self):
        """VisionModelFactory Claude 생성 테스트"""
        with patch("neos.config.settings.settings.ANTHROPIC_API_KEY", "test_key"):
            model = VisionModelFactory.create(VisionProvider.CLAUDE)
            assert isinstance(model, ClaudeVision)

    async def test_vision_model_factory_no_key(self):
        """VisionModelFactory API 키 없을 때 테스트"""
        # GPT4o는 Claude -> Gemini 순으로 폴백하므로 세 키를 모두 비워야
        # "사용 가능한 모델 없음" 경로에 도달한다. (개발 환경에 GOOGLE_API_KEY가
        # 설정돼 있으면 Gemini로 폴백해 예외가 발생하지 않는다.)
        with patch("neos.config.settings.settings.OPENAI_API_KEY", ""):
            with patch("neos.config.settings.settings.ANTHROPIC_API_KEY", None):
                with patch("neos.config.settings.settings.GOOGLE_API_KEY", ""):
                    with pytest.raises(ValueError):
                        VisionModelFactory.create(VisionProvider.GPT4O)


@pytest.mark.asyncio
class TestImagePipelineWithVision:
    """Vision 통합된 ImagePipeline 테스트"""

    async def test_image_pipeline_vision_disabled(self):
        """Vision 비활성화 시 ImagePipeline 테스트"""
        pipeline = ImagePipeline(enable_vision=False)

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
        assert result.analysis["vision_enabled"] is False
        assert "Vision model analysis disabled" in result.insights

    async def test_image_pipeline_vision_enabled_mock(self):
        """Vision 활성화 시 ImagePipeline 테스트 (Mock)"""
        pipeline = ImagePipeline(
            vision_provider=VisionProvider.GPT4O,
            enable_vision=True
        )

        # 테스트 이미지 생성
        img = Image.new("RGB", (100, 100), color="blue")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes = img_bytes.getvalue()

        file = FileInput(
            filename="test_image.png",
            file_content=img_bytes,
            mime_type="image/png",
            file_size=len(img_bytes)
        )

        context = PipelineContext(
            query="이 이미지에서 무엇이 보이나요?",
            input_type=InputType.IMAGE,
            files=[file],
            language="ko"
        )

        # Vision 모델 Mock
        mock_vision_result = {
            "description": "파란색 사각형이 보입니다.",
            "objects": [{"name": "rectangle", "confidence": 0.9}],
            "text": "",
            "metadata": {"provider": "gpt4o", "tokens_used": 150},
            "confidence": 0.85
        }

        with patch.object(pipeline, "_analyze_with_vision", return_value=mock_vision_result):
            result = await pipeline.process(context)

            assert result.success is True
            assert result.analysis["vision_enabled"] is True
            assert result.analysis["vision_provider"] == "gpt4o"
            assert result.extracted_text == "파란색 사각형이 보입니다."
            assert "Vision analysis completed" in result.insights[0]

    async def test_image_pipeline_vision_error_handling(self):
        """Vision 에러 처리 테스트"""
        pipeline = ImagePipeline(enable_vision=True)

        # 테스트 이미지 생성
        img = Image.new("RGB", (50, 50), color="green")
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
            query="Analyze",
            input_type=InputType.IMAGE,
            files=[file]
        )

        # Vision 모델이 에러를 발생시키도록 Mock
        async def mock_vision_error(*args, **kwargs):
            raise ValueError("API key not configured")

        with patch.object(pipeline, "_analyze_with_vision", side_effect=mock_vision_error):
            result = await pipeline.process(context)

            # 전체 파이프라인은 성공해야 함 (Vision 에러는 경고로 처리)
            assert result.success is True
            assert "vision_error" in result.analysis
            assert len(result.warnings) > 0
            assert "Vision analysis failed" in result.insights[0]


@pytest.mark.asyncio
class TestVisionPromptGeneration:
    """Vision 프롬프트 생성 테스트"""

    async def test_vision_prompt_korean(self):
        """한국어 프롬프트 생성 테스트"""
        pipeline = ImagePipeline()

        context = PipelineContext(
            query="이 사진 분석해줘",
            input_type=InputType.IMAGE,
            language="ko"
        )

        prompt = pipeline._create_vision_prompt("이 사진 분석해줘", context)

        assert "이미지를 분석하고" in prompt
        assert "이 사진 분석해줘" in prompt
        assert "상세히 설명" in prompt

    async def test_vision_prompt_english(self):
        """영어 프롬프트 생성 테스트"""
        pipeline = ImagePipeline()

        context = PipelineContext(
            query="Analyze this photo",
            input_type=InputType.IMAGE,
            language="en"
        )

        prompt = pipeline._create_vision_prompt("Analyze this photo", context)

        assert "Analyze this image" in prompt
        assert "Analyze this photo" in prompt
        assert "Detailed description" in prompt


@pytest.mark.asyncio
class TestVisionIntegrationEndToEnd:
    """Vision 통합 End-to-End 테스트"""

    async def test_complete_workflow_with_vision(self):
        """Vision 포함 전체 워크플로우 테스트"""
        pipeline = ImagePipeline(
            vision_provider=VisionProvider.GPT4O,
            enable_vision=True
        )

        # 실제 사용 시나리오 시뮬레이션
        img = Image.new("RGB", (200, 200), color="red")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        img_bytes = img_bytes.getvalue()

        file = FileInput(
            filename="red_square.jpg",
            file_content=img_bytes,
            mime_type="image/jpeg",
            file_size=len(img_bytes)
        )

        context = PipelineContext(
            query="What color is this image?",
            input_type=InputType.IMAGE,
            files=[file],
            user_id="test_user",
            session_id="test_session"
        )

        # Vision 응답 Mock
        mock_vision_result = {
            "description": "This is a solid red square image.",
            "objects": [{"name": "red_rectangle", "confidence": 0.95}],
            "text": "",
            "metadata": {"provider": "gpt4o", "tokens_used": 100},
            "confidence": 0.9
        }

        with patch.object(pipeline, "_analyze_with_vision", return_value=mock_vision_result):
            result = await pipeline.process(context)

            # 검증
            assert result.success is True
            assert result.input_type == InputType.IMAGE
            assert result.extracted_text == "This is a solid red square image."
            assert result.unified_context is not None
            assert "Vision Analysis" in result.unified_context
            assert result.processing_time_ms is not None
            assert result.processing_time_ms > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

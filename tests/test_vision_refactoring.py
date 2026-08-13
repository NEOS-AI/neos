"""
Vision 모듈 리팩토링 테스트
"""

import pytest
import base64
from io import BytesIO
from PIL import Image


class TestVisionRefactoring:
    """Vision 모듈 리팩토링 테스트"""

    def test_old_import_still_works(self):
        """기존 import가 여전히 작동하는지 테스트 (하위 호환성)"""
        # 경고를 무시하고 import
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)

            from neos.workflow.pipelines.vision import VisionProvider

            assert VisionProvider.GPT4O.value == "gpt4o"
            assert VisionProvider.CLAUDE.value == "claude"

    def test_new_import_works(self):
        """새로운 import가 작동하는지 테스트"""
        from neos.workflow.pipelines.vision import VisionProvider

        assert VisionProvider.GPT4O.value == "gpt4o"
        assert VisionProvider.CLAUDE.value == "claude"

    def test_detect_image_media_type_from_filename(self):
        """파일명으로 미디어 타입 감지 테스트"""
        from neos.workflow.pipelines.vision import detect_image_media_type

        assert detect_image_media_type(filename="photo.jpg") == "image/jpeg"
        assert detect_image_media_type(filename="image.png") == "image/png"
        assert detect_image_media_type(filename="pic.webp") == "image/webp"
        assert detect_image_media_type(filename="graphic.gif") == "image/gif"
        assert detect_image_media_type(filename="icon.bmp") == "image/bmp"

    def test_detect_image_media_type_from_mime(self):
        """MIME 타입으로 미디어 타입 감지 테스트"""
        from neos.workflow.pipelines.vision import detect_image_media_type

        assert detect_image_media_type(mime_type="image/jpeg") == "image/jpeg"
        assert detect_image_media_type(mime_type="image/png") == "image/png"
        assert detect_image_media_type(mime_type="image/webp") == "image/webp"

    def test_detect_image_media_type_from_base64_jpeg(self):
        """Base64 데이터로 JPEG 감지 테스트"""
        from neos.workflow.pipelines.vision import detect_image_media_type

        # JPEG 이미지 생성
        img = Image.new('RGB', (100, 100), color='red')
        buffer = BytesIO()
        img.save(buffer, format='JPEG')
        image_bytes = buffer.getvalue()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        detected = detect_image_media_type(image_data=image_base64)
        assert detected == "image/jpeg"

    def test_detect_image_media_type_from_base64_png(self):
        """Base64 데이터로 PNG 감지 테스트"""
        from neos.workflow.pipelines.vision import detect_image_media_type

        # PNG 이미지 생성
        img = Image.new('RGB', (100, 100), color='blue')
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        image_bytes = buffer.getvalue()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        detected = detect_image_media_type(image_data=image_base64)
        assert detected == "image/png"

    def test_detect_image_media_type_priority(self):
        """미디어 타입 감지 우선순위 테스트"""
        from neos.workflow.pipelines.vision import detect_image_media_type

        # MIME 타입이 가장 높은 우선순위
        detected = detect_image_media_type(
            mime_type="image/webp",
            filename="photo.jpg"
        )
        assert detected == "image/webp"

        # 파일명이 두 번째 우선순위
        detected = detect_image_media_type(filename="photo.png")
        assert detected == "image/png"

    def test_detect_image_media_type_default(self):
        """기본값 테스트"""
        from neos.workflow.pipelines.vision import detect_image_media_type

        # 아무 정보도 없으면 JPEG가 기본
        detected = detect_image_media_type()
        assert detected == "image/jpeg"

    @pytest.mark.parametrize(
        ("llm_provider", "expected"),
        [
            ("openai", "GPT4oVision"),
            ("anthropic", "ClaudeVision"),
            ("gemini", "GeminiVision"),
        ],
    )
    def test_vision_factory_auto_follows_the_configured_provider(
        self, monkeypatch, llm_provider, expected
    ):
        """AUTO 는 `settings.LLM_PROVIDER` 를 따른다.

        이 테스트는 환경을 **읽지 않고 정한다**. 예전 판은
        `VisionModelFactory.create(AUTO)` 를 그대로 부르고 결과가 GPT4o 나
        Claude 이기를 단언했는데, 그것은 코드가 아니라 **어떤 API 키가 그
        기계에 있는가**를 검사한 것이다. `.env` 가 있는 개발 기계에서는
        통과하고 CI 에서는 `GeminiVision` 이 나와 실패한다 -- 실제로
        2026-08-12 에 그렇게 확인됐다(S5).
        """
        from neos.config.settings import settings
        from neos.workflow.pipelines.vision import (
            VisionModelFactory,
            VisionProvider,
        )

        monkeypatch.setattr(settings, "LLM_PROVIDER", llm_provider)
        # 세 모델 다 사용 가능해야 fallback 이 선택을 덮어쓰지 않는다.
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.setattr(settings, key, "test-key", raising=False)

        model = VisionModelFactory.create(VisionProvider.AUTO)

        assert type(model).__name__ == expected

    def test_vision_factory_auto_falls_back_to_whichever_key_exists(
        self, monkeypatch
    ):
        """프로바이더가 셋 중 아무것도 아니면 있는 키 순서대로 고른다."""
        from neos.config.settings import settings
        from neos.workflow.pipelines.vision import (
            VisionModelFactory,
            VisionProvider,
        )

        monkeypatch.setattr(settings, "LLM_PROVIDER", "unknown-provider")
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "", raising=False)
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "", raising=False)
        monkeypatch.setattr(settings, "GOOGLE_API_KEY", "test-key", raising=False)

        model = VisionModelFactory.create(VisionProvider.AUTO)

        assert type(model).__name__ == "GeminiVision"

    def test_vision_factory_auto_raises_when_no_key_is_configured(
        self, monkeypatch
    ):
        """키가 하나도 없으면 조용히 고르지 말고 말해야 한다."""
        from neos.config.settings import settings
        from neos.workflow.pipelines.vision import (
            VisionModelFactory,
            VisionProvider,
        )

        monkeypatch.setattr(settings, "LLM_PROVIDER", "unknown-provider")
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.setattr(settings, key, "", raising=False)

        with pytest.raises(ValueError, match="API key"):
            VisionModelFactory.create(VisionProvider.AUTO)

    def test_gpt4o_vision_initialization(self):
        """GPT4oVision 초기화 테스트"""
        from neos.workflow.pipelines.vision import GPT4oVision

        model = GPT4oVision()
        assert model.model == "gpt-4o"

    def test_claude_vision_initialization(self):
        """ClaudeVision 초기화 테스트"""
        from neos.workflow.pipelines.vision import ClaudeVision

        model = ClaudeVision()
        # neos/config/models.yaml의 vision_models.claude 값
        assert model.model == "claude-sonnet-5"


class TestVisionModuleStructure:
    """Vision 모듈 구조 테스트"""

    def test_vision_package_exists(self):
        """vision 패키지가 존재하는지 테스트"""
        import neos.workflow.pipelines.vision as vision_pkg
        assert vision_pkg is not None

    def test_vision_base_module_exists(self):
        """vision_base 모듈이 존재하는지 테스트"""
        from neos.workflow.pipelines.vision import vision_base
        assert vision_base is not None

    def test_vision_gpt4o_module_exists(self):
        """vision_gpt4o 모듈이 존재하는지 테스트"""
        from neos.workflow.pipelines.vision import vision_gpt4o
        assert vision_gpt4o is not None

    def test_vision_claude_module_exists(self):
        """vision_claude 모듈이 존재하는지 테스트"""
        from neos.workflow.pipelines.vision import vision_claude
        assert vision_claude is not None

    def test_vision_factory_module_exists(self):
        """vision_factory 모듈이 존재하는지 테스트"""
        from neos.workflow.pipelines.vision import vision_factory
        assert vision_factory is not None

    def test_all_exports_available(self):
        """모든 export가 사용 가능한지 테스트"""
        from neos.workflow.pipelines.vision import (
            VisionModel,
            VisionProvider,
            VisionResult,
            detect_image_media_type,
            GPT4oVision,
            ClaudeVision,
            VisionModelFactory,
            analyze_image_with_vision,
        )

        assert VisionModel is not None
        assert VisionProvider is not None
        assert VisionResult is not None
        assert detect_image_media_type is not None
        assert GPT4oVision is not None
        assert ClaudeVision is not None
        assert VisionModelFactory is not None
        assert analyze_image_with_vision is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

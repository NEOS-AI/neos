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

    def test_vision_factory_auto_selection(self):
        """Vision Factory AUTO 선택 테스트"""
        from neos.workflow.pipelines.vision import VisionModelFactory, VisionProvider

        try:
            model = VisionModelFactory.create(VisionProvider.AUTO)
            assert model is not None
            # GPT4oVision 또는 ClaudeVision이어야 함
            assert type(model).__name__ in ["GPT4oVision", "ClaudeVision"]
        except ValueError as e:
            # API 키가 없으면 예상된 에러
            assert "API key" in str(e)

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

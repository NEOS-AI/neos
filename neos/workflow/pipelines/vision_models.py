"""
Vision 모델 통합 (DEPRECATED)

이 모듈은 하위 호환성을 위해 유지됩니다.
새로운 코드는 neos.workflow.pipelines.vision 패키지를 사용하세요.

Deprecated:
    이 모듈은 리팩토링되어 vision/ 패키지로 이동되었습니다.
    - vision_base.py: 기본 클래스 및 유틸리티
    - vision_gpt4o.py: GPT-4o Vision 구현
    - vision_claude.py: Claude Vision 구현
    - vision_factory.py: 팩토리 클래스

Usage:
    >>> from neos.workflow.pipelines.vision import (
    ...     VisionModel,
    ...     VisionProvider,
    ...     GPT4oVision,
    ...     ClaudeVision,
    ...     VisionModelFactory,
    ...     analyze_image_with_vision,
    ... )
"""

import warnings

# 하위 호환성을 위한 import
from .vision import (
    VisionModel,
    VisionProvider,
    VisionResult,
    detect_image_media_type,
    GPT4oVision,
    ClaudeVision,
    VisionModelFactory,
    analyze_image_with_vision,
)

# Deprecation 경고
warnings.warn(
    "vision_models.py is deprecated. Use 'from neos.workflow.pipelines.vision import ...' instead.",
    DeprecationWarning,
    stacklevel=2
)

__all__ = [
    "VisionModel",
    "VisionProvider",
    "VisionResult",
    "detect_image_media_type",
    "GPT4oVision",
    "ClaudeVision",
    "VisionModelFactory",
    "analyze_image_with_vision",
]

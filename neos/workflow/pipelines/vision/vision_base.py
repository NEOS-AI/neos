"""
Vision 모델 기본 클래스 및 유틸리티
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass
import base64
from pathlib import Path


class VisionProvider(Enum):
    """Vision 모델 프로바이더"""
    GPT4O = "gpt4o"
    CLAUDE = "claude"
    AUTO = "auto"  # 자동 선택 (설정 기반)


@dataclass
class VisionResult:
    """Vision 분석 결과"""
    description: str
    objects: list[str]
    text: str  # OCR 추출 텍스트
    metadata: Dict[str, Any]
    confidence: float


def detect_image_media_type(
    image_data: str = None,
    filename: str = None,
    mime_type: str = None
) -> str:
    """
    이미지의 미디어 타입 감지

    Args:
        image_data: Base64 인코딩된 이미지 데이터 (선택)
        filename: 파일명 (선택)
        mime_type: MIME 타입 (선택)

    Returns:
        감지된 미디어 타입 (예: "image/jpeg", "image/png")

    Examples:
        >>> detect_image_media_type(filename="photo.png")
        'image/png'
        >>> detect_image_media_type(mime_type="image/webp")
        'image/webp'
    """
    # 1. MIME 타입이 제공된 경우 우선 사용
    if mime_type:
        if mime_type.startswith("image/"):
            return mime_type

    # 2. 파일명 확장자로 추론
    if filename:
        extension = Path(filename).suffix.lower()
        extension_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
        }
        if extension in extension_map:
            return extension_map[extension]

    # 3. Base64 데이터의 매직 바이트로 감지
    if image_data:
        try:
            # Base64 디코딩하여 첫 바이트 확인
            decoded = base64.b64decode(image_data[:100])  # 첫 100자만 디코드

            # 매직 넘버로 이미지 타입 판별
            if decoded.startswith(b'\xff\xd8\xff'):
                return "image/jpeg"
            elif decoded.startswith(b'\x89PNG\r\n\x1a\n'):
                return "image/png"
            elif decoded.startswith(b'GIF87a') or decoded.startswith(b'GIF89a'):
                return "image/gif"
            elif decoded.startswith(b'RIFF') and b'WEBP' in decoded[:20]:
                return "image/webp"
            elif decoded.startswith(b'BM'):
                return "image/bmp"
            elif decoded.startswith(b'II\x2a\x00') or decoded.startswith(b'MM\x00\x2a'):
                return "image/tiff"
        except Exception:
            pass

    # 4. 기본값 (JPEG)
    return "image/jpeg"


class VisionModel(ABC):
    """
    Vision 모델 추상 베이스 클래스

    모든 Vision 모델이 구현해야 하는 공통 인터페이스입니다.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    @abstractmethod
    async def analyze_image(
        self,
        image_data: str,
        prompt: str,
        max_tokens: int = 1000,
        **kwargs
    ) -> Dict[str, Any]:
        """
        이미지 분석

        Args:
            image_data: Base64 인코딩된 이미지 데이터
            prompt: 분석 요청 프롬프트
            max_tokens: 최대 응답 토큰 수
            **kwargs: 추가 파라미터
                - filename: 파일명 (미디어 타입 감지용)
                - mime_type: MIME 타입
                - temperature: 샘플링 온도
                - detail: 이미지 상세도 (GPT-4o only)

        Returns:
            분석 결과 딕셔너리
            {
                "description": str,
                "objects": List[str],
                "text": str,
                "metadata": Dict[str, Any],
                "confidence": float
            }
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """API 키가 설정되어 있는지 확인"""
        pass

    def _create_result(
        self,
        description: str,
        objects: Optional[list] = None,
        text: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        confidence: float = 0.0
    ) -> Dict[str, Any]:
        """
        표준화된 결과 생성

        Args:
            description: 이미지 설명
            objects: 감지된 객체 리스트
            text: OCR 추출 텍스트
            metadata: 메타데이터
            confidence: 신뢰도 (0.0 ~ 1.0)

        Returns:
            표준화된 결과 딕셔너리
        """
        return {
            "description": description,
            "objects": objects or [],
            "text": text or "",
            "metadata": metadata or {},
            "confidence": confidence,
        }

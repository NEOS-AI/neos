"""
Google Gemini Vision 모델 구현
"""

from typing import Dict, Any, Optional
import base64
import asyncio

from neos.config.settings import settings
from neos.config.model_config import get_vision_model_id

from .vision_base import VisionModel, detect_image_media_type


class GeminiVision(VisionModel):
    """
    Google Gemini Vision 모델

    Google의 Gemini를 사용한 이미지 분석
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key or settings.GOOGLE_API_KEY)
        # 설정 파일에서 모델 ID 로드 (하드코딩 제거)
        self.model = get_vision_model_id('gemini')

    async def analyze_image(
        self,
        image_data: str,
        prompt: str,
        max_tokens: int = 1000,
        **kwargs
    ) -> Dict[str, Any]:
        """Gemini Vision으로 이미지 분석"""
        if not self.is_available():
            raise ValueError("Google API key not configured")

        try:
            import google.generativeai as genai

            # API 키 설정
            genai.configure(api_key=self.api_key)

            # 이미지 미디어 타입 감지
            media_type = detect_image_media_type(
                image_data=image_data,
                filename=kwargs.get("filename"),
                mime_type=kwargs.get("mime_type")
            )

            print(f"[GeminiVision] Using model: {self.model}")
            print(f"[GeminiVision] Detected media type: {media_type}")
            print(f"[GeminiVision] Image data length: {len(image_data)} chars")

            # Base64 디코딩
            image_bytes = base64.b64decode(image_data)

            # 이미지 파트 생성
            image_part = {
                "mime_type": media_type,
                "data": image_bytes
            }

            # Gemini 모델 생성
            model = genai.GenerativeModel(self.model)

            # 동기 API를 executor로 래핑하여 비동기로 실행
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: model.generate_content(
                    [prompt, image_part],
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=max_tokens,
                        temperature=kwargs.get("temperature", 0.1)
                    )
                )
            )

            print("[GeminiVision] API call successful")

            # 응답 파싱
            content = response.text if response.text else ""

            result = self._parse_response(content)

            # 메타데이터 추가
            result["metadata"].update({
                "provider": "gemini",
                "model": self.model,
                "media_type": media_type,
                "finish_reason": response.candidates[0].finish_reason.name if response.candidates else None
            })

            # 토큰 사용량 (있는 경우)
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                result["metadata"]["tokens_used"] = response.usage_metadata.total_token_count

            return result

        except ImportError:
            raise ImportError("google-generativeai package not installed. Run: pip install google-generativeai")
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"[GeminiVision] Error: {str(e)}")
            print(f"[GeminiVision] Full traceback:\n{error_detail}")
            return {
                "description": f"Error analyzing image with Gemini: {str(e)}",
                "objects": [],
                "text": "",
                "metadata": {
                    "error": str(e),
                    "provider": "gemini",
                    "error_type": type(e).__name__,
                    "traceback": error_detail
                },
                "confidence": 0.0
            }

    def is_available(self) -> bool:
        """Google API 키 확인"""
        return bool(self.api_key and self.api_key.strip())

    def _parse_response(self, content: str) -> Dict[str, Any]:
        """
        Gemini 응답 파싱

        간단한 파싱으로 객체, 텍스트 등을 추출합니다.
        """
        return self._create_result(
            description=content,
            confidence=0.88  # Gemini는 높은 신뢰도
        )

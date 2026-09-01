"""
Claude Vision 모델 구현
"""

from typing import Dict, Any, Optional

from neos.config.settings import settings
from neos.config.model_config import get_vision_model_id

from .vision_base import VisionModel, detect_image_media_type


class ClaudeVision(VisionModel):
    """
    Claude Vision 모델

    Anthropic의 Claude를 사용한 이미지 분석
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key or settings.ANTHROPIC_API_KEY)
        # 설정 파일에서 모델 ID 로드 (하드코딩 제거)
        self.model = get_vision_model_id('claude')

    async def analyze_image(
        self,
        image_data: str,
        prompt: str,
        max_tokens: int = 1000,
        **kwargs
    ) -> Dict[str, Any]:
        """Claude Vision으로 이미지 분석"""
        if not self.is_available():
            raise ValueError("Anthropic API key not configured")

        try:
            from neos.utils.anthropic_client import build_async_anthropic

            client = build_async_anthropic(api_key=self.api_key)

            # 이미지 미디어 타입 감지
            media_type = detect_image_media_type(
                image_data=image_data,
                filename=kwargs.get("filename"),
                mime_type=kwargs.get("mime_type")
            )

            print(f"[ClaudeVision] Using model: {self.model}")
            print(f"[ClaudeVision] Detected media type: {media_type}")
            print(f"[ClaudeVision] Image data length: {len(image_data)} chars")

            # Claude Vision API 호출
            response = await client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data,
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
                temperature=kwargs.get("temperature", 0.1)
            )

            print("[ClaudeVision] API call successful")

            # 응답 파싱
            content = response.content[0].text if response.content else ""

            result = self._parse_response(content)

            # 메타데이터 추가
            result["metadata"].update({
                "provider": "claude",
                "model": self.model,
                "media_type": media_type,
                "tokens_used": response.usage.input_tokens + response.usage.output_tokens if response.usage else 0,
                "stop_reason": response.stop_reason
            })

            return result

        except ImportError:
            raise ImportError("anthropic package not installed. Run: pip install anthropic")
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"[ClaudeVision] Error: {str(e)}")
            print(f"[ClaudeVision] Full traceback:\n{error_detail}")
            return {
                "description": f"Error analyzing image with Claude: {str(e)}",
                "objects": [],
                "text": "",
                "metadata": {
                    "error": str(e),
                    "provider": "claude",
                    "error_type": type(e).__name__,
                    "traceback": error_detail
                },
                "confidence": 0.0
            }

    def is_available(self) -> bool:
        """Anthropic API 키 확인"""
        return bool(self.api_key and self.api_key.strip())

    def _parse_response(self, content: str) -> Dict[str, Any]:
        """
        Claude 응답 파싱

        간단한 파싱으로 객체, 텍스트 등을 추출합니다.
        """
        return self._create_result(
            description=content,
            confidence=0.85  # Claude는 매우 높은 신뢰도
        )

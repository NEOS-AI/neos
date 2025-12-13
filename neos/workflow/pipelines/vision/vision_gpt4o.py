"""
GPT-4o Vision 모델 구현
"""

from typing import Dict, Any, Optional

from neos.config.settings import settings

from .vision_base import VisionModel, detect_image_media_type


class GPT4oVision(VisionModel):
    """
    GPT-4o Vision 모델

    OpenAI의 GPT-4o를 사용한 이미지 분석
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key or settings.OPENAI_API_KEY)
        self.model = "gpt-4o"  # GPT-4o 모델

    async def analyze_image(
        self,
        image_data: str,
        prompt: str,
        max_tokens: int = 1000,
        **kwargs
    ) -> Dict[str, Any]:
        """GPT-4o로 이미지 분석"""
        if not self.is_available():
            raise ValueError("OpenAI API key not configured")

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self.api_key)

            # 이미지 미디어 타입 감지
            media_type = detect_image_media_type(
                image_data=image_data,
                filename=kwargs.get("filename"),
                mime_type=kwargs.get("mime_type")
            )

            # GPT-4o Vision API 호출
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media_type};base64,{image_data}",
                                    "detail": kwargs.get("detail", "auto")  # auto, low, high
                                }
                            }
                        ]
                    }
                ],
                max_tokens=max_tokens,
                temperature=kwargs.get("temperature", 0.1)
            )

            # 응답 파싱
            content = response.choices[0].message.content if response.choices else ""

            result = self._parse_response(content)

            # 메타데이터 추가
            result["metadata"].update({
                "provider": "gpt4o",
                "model": self.model,
                "media_type": media_type,
                "tokens_used": response.usage.total_tokens if response.usage else 0,
                "finish_reason": response.choices[0].finish_reason if response.choices else None
            })

            return result

        except ImportError:
            raise ImportError("openai package not installed. Run: pip install openai")
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            print(f"[GPT4oVision] Error: {str(e)}")
            print(f"[GPT4oVision] Full traceback:\n{error_detail}")
            return {
                "description": f"Error analyzing image with GPT-4o: {str(e)}",
                "objects": [],
                "text": "",
                "metadata": {
                    "error": str(e),
                    "provider": "gpt4o",
                    "error_type": type(e).__name__,
                    "traceback": error_detail
                },
                "confidence": 0.0
            }

    def is_available(self) -> bool:
        """OpenAI API 키 확인"""
        return bool(self.api_key and self.api_key.strip())

    def _parse_response(self, content: str) -> Dict[str, Any]:
        """
        GPT-4o 응답 파싱

        간단한 파싱으로 객체, 텍스트 등을 추출합니다.
        """
        return self._create_result(
            description=content,
            confidence=0.9  # GPT-4o는 높은 신뢰도
        )

"""
이미지 처리 파이프라인

이미지 파일을 분석하고 Vision 모델로 이해합니다.
"""

from typing import Dict, Any, Optional
import base64
from pathlib import Path
from PIL import Image
import io

from .base import (
    BasePipeline,
    InputType,
    PipelineContext,
    PipelineResult,
    ProcessingStage,
    FileInput
)
from .vision_models import VisionModelFactory, VisionProvider


class ImagePipeline(BasePipeline):
    """
    이미지 처리 파이프라인

    이미지를 전처리하고 Vision 모델로 분석합니다.
    """

    # 지원하는 이미지 포맷
    SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

    # 최대 이미지 크기 (픽셀)
    MAX_IMAGE_SIZE = (4096, 4096)

    # 최대 파일 크기 (바이트)
    MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

    def __init__(self, vision_provider: VisionProvider = VisionProvider.AUTO, enable_vision: bool = True):
        super().__init__(name="ImagePipeline", input_type=InputType.IMAGE)
        self.vision_provider = vision_provider
        self.enable_vision = enable_vision

    async def validate(self, context: PipelineContext) -> bool:
        """이미지 입력 검증"""
        if not context.files or len(context.files) == 0:
            return False

        file = context.files[0]

        # 파일 크기 확인
        if file.file_size and file.file_size > self.MAX_FILE_SIZE:
            return False

        # 파일 포맷 확인
        if file.filename:
            ext = Path(file.filename).suffix.lower()
            if ext not in self.SUPPORTED_FORMATS:
                return False

        return True

    async def preprocess(self, context: PipelineContext) -> PipelineContext:
        """이미지 전처리"""
        file = context.files[0]

        # 이미지 로드
        if file.file_content:
            image = Image.open(io.BytesIO(file.file_content))
        elif file.file_path:
            image = Image.open(file.file_path)
        else:
            raise ValueError("No image content or path provided")

        # 이미지 정보 저장
        context.additional_context["original_size"] = image.size
        context.additional_context["original_format"] = image.format
        context.additional_context["original_mode"] = image.mode

        # 크기 조정 (필요시)
        if image.size[0] > self.MAX_IMAGE_SIZE[0] or image.size[1] > self.MAX_IMAGE_SIZE[1]:
            image.thumbnail(self.MAX_IMAGE_SIZE, Image.Resampling.LANCZOS)
            context.additional_context["resized"] = True
            context.additional_context["new_size"] = image.size

        # RGB로 변환 (필요시)
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")

        # 전처리된 이미지를 바이트로 저장
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        context.additional_context["preprocessed_image"] = buffer.getvalue()

        return context

    async def extract(self, context: PipelineContext) -> PipelineResult:
        """이미지에서 정보 추출"""
        file = context.files[0]

        # 메타데이터 추출
        metadata = {
            "filename": file.filename,
            "mime_type": file.mime_type,
            "file_size": file.file_size,
            "original_size": context.additional_context.get("original_size"),
            "format": context.additional_context.get("original_format"),
            "mode": context.additional_context.get("original_mode"),
            "resized": context.additional_context.get("resized", False),
        }

        # 이미지를 base64로 인코딩 (Vision 모델 입력용)
        preprocessed_image = context.additional_context.get("preprocessed_image")
        if preprocessed_image:
            image_base64 = base64.b64encode(preprocessed_image).decode("utf-8")
            metadata["image_base64"] = image_base64

        result = PipelineResult(
            success=True,
            input_type=InputType.IMAGE,
            stage=ProcessingStage.EXTRACTION,
            metadata=metadata
        )

        return result

    async def analyze(self, result: PipelineResult, context: PipelineContext) -> PipelineResult:
        """
        이미지 분석 (Vision 모델 호출)

        실제 Vision 모델(GPT-4o 또는 Claude)을 사용하여 이미지를 분석합니다.
        """
        # 기본 분석
        analysis = {
            "has_image": True,
            "image_quality": self._assess_quality(result.metadata),
            "vision_enabled": self.enable_vision,
        }

        insights = []
        vision_description = None

        # Vision 모델 분석 (활성화된 경우)
        if self.enable_vision:
            try:
                image_base64 = result.metadata.get("image_base64")
                if image_base64:
                    # Vision 모델로 분석
                    vision_result = await self._analyze_with_vision(
                        image_base64=image_base64,
                        query=context.query,
                        context=context
                    )

                    # Vision 분석 결과 추가
                    analysis.update({
                        "vision_analysis": vision_result,
                        "vision_provider": vision_result.get("metadata", {}).get("provider"),
                        "vision_confidence": vision_result.get("confidence", 0.0)
                    })

                    vision_description = vision_result.get("description", "")
                    result.extracted_text = vision_description  # 추출된 텍스트로 설정

                    # 인사이트 생성
                    insights.append(f"Vision analysis completed with {vision_result.get('metadata', {}).get('provider', 'unknown')}")

                    if vision_result.get("text"):
                        insights.append(f"OCR detected text: {len(vision_result['text'])} characters")

                    if vision_result.get("objects"):
                        insights.append(f"Detected {len(vision_result['objects'])} objects")

                else:
                    insights.append("No base64 image data available for Vision analysis")

            except Exception as e:
                # Vision 분석 실패 시 경고로 처리 (전체 파이프라인은 계속)
                analysis["vision_error"] = str(e)
                insights.append(f"Vision analysis failed: {str(e)}")
                result.warnings.append(f"Vision model error: {str(e)}")

        else:
            insights.append("Vision model analysis disabled")

        # 이미지 크기 조정 여부 확인
        if result.metadata.get("resized"):
            insights.append("Image was resized for processing")

        result.analysis = analysis
        result.insights = insights

        # 통합 컨텍스트 생성
        result.unified_context = self._create_unified_context(
            context=context,
            result=result,
            vision_description=vision_description
        )

        return result

    async def _analyze_with_vision(
        self,
        image_base64: str,
        query: str,
        context: PipelineContext
    ) -> Dict[str, Any]:
        """
        Vision 모델로 이미지 분석

        Args:
            image_base64: Base64 인코딩된 이미지
            query: 사용자 쿼리
            context: 파이프라인 컨텍스트

        Returns:
            Vision 분석 결과
        """
        # Vision 모델 생성
        vision_model = VisionModelFactory.create(self.vision_provider)

        # 분석 프롬프트 생성
        prompt = self._create_vision_prompt(query, context)

        # Vision 모델 호출
        result = await vision_model.analyze_image(
            image_data=image_base64,
            prompt=prompt,
            max_tokens=context.preferences.get("max_tokens", 1000)
        )

        return result

    def _create_vision_prompt(self, query: str, context: PipelineContext) -> str:
        """
        Vision 모델용 프롬프트 생성

        사용자 쿼리를 Vision 모델에 적합한 형태로 변환합니다.
        """
        # 언어 감지
        language = context.language or "en"

        if language == "ko":
            base_prompt = f"""이미지를 분석하고 다음 질문에 답변해주세요:

{query}

다음 내용을 포함해주세요:
1. 이미지에 무엇이 보이는지 상세히 설명
2. 주요 객체나 사물 식별
3. 이미지에 포함된 텍스트가 있다면 추출
4. 전반적인 분위기나 맥락"""
        else:
            base_prompt = f"""Analyze this image and answer the following question:

{query}

Please include:
1. Detailed description of what's visible in the image
2. Identification of main objects or items
3. Any text present in the image (OCR)
4. Overall context or mood"""

        return base_prompt

    def _create_unified_context(
        self,
        context: PipelineContext,
        result: PipelineResult,
        vision_description: Optional[str]
    ) -> str:
        """통합 컨텍스트 생성"""
        sections = [
            "**Image Analysis Result**\n",
            f"**Query**: {context.query}\n",
            "\n**Image Metadata**:",
            f"- Filename: {result.metadata.get('filename')}",
            f"- Size: {result.metadata.get('original_size')}",
            f"- Format: {result.metadata.get('format')}",
            f"- Quality: {result.analysis.get('image_quality', 'unknown')}",
        ]

        if vision_description:
            sections.extend([
                "\n**Vision Analysis**:",
                vision_description,
            ])

            # OCR 텍스트가 있으면 추가
            if result.analysis.get("vision_analysis", {}).get("text"):
                sections.extend([
                    "\n**Extracted Text (OCR)**:",
                    result.analysis["vision_analysis"]["text"]
                ])
        else:
            sections.append("\n**Note**: Vision model analysis was not performed or failed.")

        return "\n".join(sections)

    def _assess_quality(self, metadata: Dict[str, Any]) -> str:
        """이미지 품질 평가"""
        size = metadata.get("original_size")
        if not size:
            return "unknown"

        pixels = size[0] * size[1]

        if pixels < 640 * 480:
            return "low"
        elif pixels < 1920 * 1080:
            return "medium"
        else:
            return "high"

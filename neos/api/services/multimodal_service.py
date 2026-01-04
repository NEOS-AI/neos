"""Multimodal service layer - handles business logic"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from neos.workflow.multimodal_workflow import MultiModalWorkflow
from neos.config.settings import settings
from neos.workflow.pipelines import VisionModelFactory

logger = logging.getLogger(__name__)


class MultimodalService:
    """Service layer for multimodal processing"""

    @staticmethod
    async def convert_upload_files_to_dict(files: List[Any]) -> List[Dict[str, Any]]:
        """
        UploadFile 객체들을 딕셔너리 형태로 변환

        Args:
            files: FastAPI UploadFile 객체 리스트

        Returns:
            변환된 파일 정보 딕셔너리 리스트
        """
        file_dicts = []

        for file in files:
            try:
                # 파일 내용 읽기
                content = await file.read()

                file_dict = {
                    "filename": file.filename,
                    "file_content": content,
                    "mime_type": file.content_type,
                    "file_size": len(content),
                    "file_path": None,  # 업로드된 파일은 경로 없음
                    "url": None
                }

                file_dicts.append(file_dict)

                # 파일 포인터 리셋 (혹시 모를 재사용을 위해)
                await file.seek(0)

            except Exception as e:
                logger.error(f"Failed to process file {file.filename}: {e}")
                raise ValueError(f"Failed to read file {file.filename}: {str(e)}")

        return file_dicts

    @staticmethod
    def extract_vision_analysis(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        워크플로우 결과에서 Vision 분석 정보 추출

        Args:
            result: MultiModalWorkflow 실행 결과

        Returns:
            Vision 분석 정보 (있을 경우)
        """
        try:
            metadata = result.get("result", {}).get("metadata", {})

            # Vision 관련 정보 추출
            vision_info = {}

            if "vision_analysis" in metadata:
                vision_info["vision_analysis"] = metadata["vision_analysis"]

            if "image_description" in metadata:
                vision_info["description"] = metadata["image_description"]

            if "detected_objects" in metadata:
                vision_info["objects"] = metadata["detected_objects"]

            if "ocr_text" in metadata:
                vision_info["ocr_text"] = metadata["ocr_text"]

            if "vision_provider" in metadata:
                vision_info["provider"] = metadata["vision_provider"]

            if "confidence" in metadata:
                vision_info["confidence"] = metadata["confidence"]

            return vision_info if vision_info else None

        except Exception as e:
            logger.warning(f"Failed to extract vision analysis: {e}")
            return None

    @staticmethod
    async def process_multimodal_query(
        query: str,
        file_dicts: List[Dict[str, Any]],
        user_id: str,
        session_id: str,
        language: str = "ko"
    ) -> Dict[str, Any]:
        """
        멀티모달 쿼리 처리

        Args:
            query: 사용자 쿼리
            file_dicts: 파일 정보 딕셔너리 리스트
            user_id: 사용자 ID
            session_id: 세션 ID
            language: 응답 언어

        Returns:
            처리 결과
        """
        logger.info(f"[Multimodal Service] Processing query with {len(file_dicts)} file(s)")

        # MultiModalWorkflow 초기화 및 실행
        workflow = MultiModalWorkflow()

        start_time = datetime.now()

        result = await workflow.process(
            query=query,
            files=file_dicts,
            user_id=user_id,
            session_id=session_id,
            language=language
        )

        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds() * 1000

        if not result.get("success", False):
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"[Multimodal Service] Workflow failed: {error_msg}")
            logger.error(f"[Multimodal Service] Full result: {result}")
            raise Exception(f"Workflow execution failed: {error_msg}")

        # 응답 데이터 추출
        workflow_result = result.get("result", {})
        final_response = workflow_result.get("final_response", "")

        # 메타데이터가 없으면 빈 딕셔너리
        if not final_response and "response" in workflow_result:
            final_response = workflow_result["response"]

        metadata = workflow_result.get("response_metadata", {})
        if not metadata:
            metadata = workflow_result.get("metadata", {})

        # Vision 분석 정보 추출
        vision_analysis = MultimodalService.extract_vision_analysis(result)

        # 추출된 텍스트 정보
        extracted_text = metadata.get("extracted_text")

        # 에러 및 경고 수집
        errors = workflow_result.get("errors", [])
        warnings = []

        # 입력 타입
        input_type = result.get("input_type", "unknown")

        logger.info(f"[Multimodal Service] Successfully processed query in {processing_time:.0f}ms")

        return {
            "success": True,
            "response": final_response,
            "session_id": session_id,
            "input_type": input_type,
            "metadata": metadata,
            "processing_time_ms": processing_time,
            "vision_analysis": vision_analysis,
            "extracted_text": extracted_text,
            "errors": [str(e) for e in errors] if errors else [],
            "warnings": warnings
        }

    @staticmethod
    async def analyze_image(
        file_content: bytes,
        filename: str,
        content_type: str,
        query: Optional[str] = None,
        user_id: str = "anonymous",
        language: str = "ko"
    ) -> Dict[str, Any]:
        """
        이미지 단독 분석

        Args:
            file_content: 이미지 파일 내용
            filename: 파일명
            content_type: MIME 타입
            query: 이미지에 대한 질문 (선택)
            user_id: 사용자 ID
            language: 응답 언어

        Returns:
            분석 결과
        """
        logger.info(f"[Image Analysis Service] Analyzing image: {filename}")

        # 파일 딕셔너리 생성
        file_dict = {
            "filename": filename,
            "file_content": file_content,
            "mime_type": content_type,
            "file_size": len(file_content),
            "file_path": None,
            "url": None
        }

        # MultiModalWorkflow로 처리 (이미지만)
        workflow = MultiModalWorkflow()

        start_time = datetime.now()

        # 쿼리가 없으면 기본 분석 요청
        analysis_query = query or "이 이미지를 자세히 분석해주세요."

        result = await workflow.process(
            query=analysis_query,
            files=[file_dict],
            user_id=user_id,
            session_id=str(datetime.now().timestamp()),
            language=language
        )

        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds() * 1000

        if not result.get("success", False):
            raise Exception(f"Image analysis failed: {result.get('error', 'Unknown error')}")

        # Vision 분석 정보 추출
        vision_info = MultimodalService.extract_vision_analysis(result)

        metadata = result.get("result", {}).get("metadata", {})

        logger.info(f"[Image Analysis Service] Successfully analyzed image in {processing_time:.0f}ms")

        return {
            "success": True,
            "filename": filename,
            "description": vision_info.get("description") if vision_info else None,
            "objects": vision_info.get("objects", []) if vision_info else [],
            "ocr_text": vision_info.get("ocr_text") if vision_info else None,
            "image_metadata": {
                "width": metadata.get("width"),
                "height": metadata.get("height"),
                "format": metadata.get("format"),
                "mime_type": content_type,
                "file_size": len(file_content),
            },
            "vision_provider": vision_info.get("provider") if vision_info else None,
            "confidence": vision_info.get("confidence") if vision_info else None,
            "processing_time_ms": processing_time
        }

    @staticmethod
    async def get_supported_types() -> Dict[str, Any]:
        """
        지원하는 파일 타입 목록 조회

        Returns:
            지원하는 파일 타입 정보
        """
        # 지원하는 파일 타입들
        supported_types = {
            "image": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"],
            "document": [".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv"],
            "audio": [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".webm"],
        }

        # Vision 설정 정보
        vision_enabled = settings.VISION_ENABLED
        vision_providers = []

        if vision_enabled:
            if settings.OPENAI_API_KEY:
                vision_providers.append("gpt4o")
            if settings.ANTHROPIC_API_KEY:
                vision_providers.append("claude")

        return {
            "supported_types": supported_types,
            "vision_enabled": vision_enabled,
            "vision_providers": vision_providers
        }

    @staticmethod
    async def check_health() -> Dict[str, Any]:
        """
        멀티모달 API 헬스 체크

        Returns:
            헬스 체크 결과
        """
        health_info = {
            "status": "healthy",
            "multimodal_workflow": "available",
            "vision_enabled": settings.VISION_ENABLED,
            "vision_models": {}
        }

        # Vision 모델 가용성 체크
        if settings.VISION_ENABLED:
            try:
                # Factory를 통한 모델 생성 테스트
                vision_model = VisionModelFactory.create(provider="auto")
                if vision_model:
                    is_available = await vision_model.is_available()
                    health_info["vision_models"]["primary"] = {
                        "available": is_available,
                        "provider": type(vision_model).__name__
                    }
                else:
                    health_info["vision_models"]["primary"] = {
                        "available": False,
                        "error": "No vision model available"
                    }
            except Exception as e:
                health_info["vision_models"]["error"] = str(e)
                health_info["status"] = "degraded"

        return health_info

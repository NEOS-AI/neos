"""
통합 입력 라우터

입력 타입을 자동으로 분류하고 적절한 파이프라인으로 라우팅합니다.
"""

import re
from typing import List, Optional, Dict, Any
from pathlib import Path
import mimetypes

from .base import (
    InputType,
    PipelineContext,
    FileInput,
    PipelineRegistry,
    BasePipeline
)


class InputRouter:
    """
    통합 입력 라우터

    사용자 입력을 분석하여 적절한 파이프라인으로 라우팅합니다.
    """

    # MIME 타입 매핑
    MIME_TYPE_MAPPING = {
        # 이미지
        "image/jpeg": InputType.IMAGE,
        "image/png": InputType.IMAGE,
        "image/gif": InputType.IMAGE,
        "image/webp": InputType.IMAGE,
        "image/svg+xml": InputType.IMAGE,

        # 문서
        "application/pdf": InputType.DOCUMENT,
        "application/msword": InputType.DOCUMENT,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": InputType.DOCUMENT,
        "application/vnd.ms-excel": InputType.DOCUMENT,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": InputType.DOCUMENT,
        "application/vnd.ms-powerpoint": InputType.DOCUMENT,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": InputType.DOCUMENT,
        "text/csv": InputType.DOCUMENT,
        "text/plain": InputType.DOCUMENT,
        "text/markdown": InputType.DOCUMENT,

        # 오디오
        "audio/mpeg": InputType.AUDIO,
        "audio/mp3": InputType.AUDIO,
        "audio/wav": InputType.AUDIO,
        "audio/ogg": InputType.AUDIO,
        "audio/webm": InputType.AUDIO,
        "audio/flac": InputType.AUDIO,

        # 비디오
        "video/mp4": InputType.VIDEO,
        "video/mpeg": InputType.VIDEO,
        "video/webm": InputType.VIDEO,
        "video/ogg": InputType.VIDEO,
        "video/quicktime": InputType.VIDEO,
    }

    # 확장자 매핑 (백업)
    EXTENSION_MAPPING = {
        # 이미지
        ".jpg": InputType.IMAGE,
        ".jpeg": InputType.IMAGE,
        ".png": InputType.IMAGE,
        ".gif": InputType.IMAGE,
        ".webp": InputType.IMAGE,
        ".svg": InputType.IMAGE,

        # 문서
        ".pdf": InputType.DOCUMENT,
        ".doc": InputType.DOCUMENT,
        ".docx": InputType.DOCUMENT,
        ".xls": InputType.DOCUMENT,
        ".xlsx": InputType.DOCUMENT,
        ".ppt": InputType.DOCUMENT,
        ".pptx": InputType.DOCUMENT,
        ".csv": InputType.DOCUMENT,
        ".txt": InputType.DOCUMENT,
        ".md": InputType.DOCUMENT,

        # 오디오
        ".mp3": InputType.AUDIO,
        ".wav": InputType.AUDIO,
        ".ogg": InputType.AUDIO,
        ".flac": InputType.AUDIO,
        ".m4a": InputType.AUDIO,

        # 비디오
        ".mp4": InputType.VIDEO,
        ".avi": InputType.VIDEO,
        ".mov": InputType.VIDEO,
        ".wmv": InputType.VIDEO,
        ".webm": InputType.VIDEO,
    }

    def __init__(self):
        self.registry = PipelineRegistry()

    def classify_input(
        self,
        query: str,
        files: Optional[List[FileInput]] = None,
        **kwargs
    ) -> InputType:
        """
        입력 타입을 자동으로 분류합니다.

        Args:
            query: 사용자 쿼리
            files: 첨부된 파일들
            **kwargs: 추가 컨텍스트

        Returns:
            분류된 입력 타입
        """
        # 1. 파일이 없으면 텍스트
        if not files or len(files) == 0:
            return InputType.TEXT

        # 2. 여러 파일 또는 다양한 타입이 섞여 있으면 멀티모달
        if len(files) > 1:
            types = set(self._classify_file(f) for f in files)
            if len(types) > 1:
                return InputType.MULTIMODAL

        # 3. 단일 파일의 타입 분류
        return self._classify_file(files[0])

    def _classify_file(self, file_input: FileInput) -> InputType:
        """
        개별 파일의 타입을 분류합니다.

        Args:
            file_input: 파일 입력

        Returns:
            분류된 입력 타입
        """
        # 1. MIME 타입으로 분류
        if file_input.mime_type:
            input_type = self.MIME_TYPE_MAPPING.get(file_input.mime_type)
            if input_type:
                return input_type

        # 2. 파일 확장자로 분류
        if file_input.file_path or file_input.filename:
            path = file_input.file_path or file_input.filename
            ext = Path(path).suffix.lower()
            input_type = self.EXTENSION_MAPPING.get(ext)
            if input_type:
                return input_type

        # 3. 파일명에서 MIME 타입 추론
        if file_input.filename:
            mime_type, _ = mimetypes.guess_type(file_input.filename)
            if mime_type:
                input_type = self.MIME_TYPE_MAPPING.get(mime_type)
                if input_type:
                    return input_type

        return InputType.UNKNOWN

    def route(
        self,
        query: str,
        files: Optional[List[FileInput]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs
    ) -> tuple[PipelineContext, Optional[BasePipeline]]:
        """
        입력을 분석하고 적절한 파이프라인으로 라우팅합니다.

        Args:
            query: 사용자 쿼리
            files: 첨부된 파일들
            user_id: 사용자 ID
            session_id: 세션 ID
            **kwargs: 추가 컨텍스트

        Returns:
            (PipelineContext, BasePipeline) 튜플
        """
        # 1. 입력 타입 분류
        input_type = self.classify_input(query, files, **kwargs)

        # 2. 컨텍스트 생성
        context = PipelineContext(
            query=query,
            input_type=input_type,
            files=files or [],
            user_id=user_id,
            session_id=session_id,
            language=kwargs.get("language"),
            preferences=kwargs.get("preferences", {}),
            additional_context=kwargs
        )

        # 3. 파이프라인 조회
        pipeline = self.registry.get(input_type)

        return context, pipeline

    def get_available_pipelines(self) -> Dict[InputType, BasePipeline]:
        """
        사용 가능한 모든 파이프라인을 조회합니다.

        Returns:
            파이프라인 딕셔너리
        """
        return self.registry.get_all()

    def is_supported(self, input_type: InputType) -> bool:
        """
        해당 입력 타입이 지원되는지 확인합니다.

        Args:
            input_type: 확인할 입력 타입

        Returns:
            지원 여부
        """
        return self.registry.get(input_type) is not None

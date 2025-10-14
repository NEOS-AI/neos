"""
멀티모달 파이프라인 베이스 클래스 및 공통 데이터 모델
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timezone
from enum import Enum
import mimetypes
from pathlib import Path


class InputType(Enum):
    """입력 타입 분류"""
    TEXT = "text"
    IMAGE = "image"
    DOCUMENT = "document"
    AUDIO = "audio"
    VIDEO = "video"
    MULTIMODAL = "multimodal"
    UNKNOWN = "unknown"


class ProcessingStage(Enum):
    """파이프라인 처리 단계"""
    VALIDATION = "validation"
    PREPROCESSING = "preprocessing"
    EXTRACTION = "extraction"
    ANALYSIS = "analysis"
    SYNTHESIS = "synthesis"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class FileInput:
    """파일 입력 정보"""
    file_path: Optional[str] = None
    file_content: Optional[bytes] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    filename: Optional[str] = None
    url: Optional[str] = None

    def __post_init__(self):
        """자동으로 MIME 타입 추론"""
        if not self.mime_type and self.file_path:
            self.mime_type, _ = mimetypes.guess_type(self.file_path)
        if not self.filename and self.file_path:
            self.filename = Path(self.file_path).name
        if not self.file_size and self.file_content:
            self.file_size = len(self.file_content)


@dataclass
class PipelineContext:
    """파이프라인 실행 컨텍스트"""
    # 입력 정보
    query: str
    input_type: InputType
    files: List[FileInput] = field(default_factory=list)

    # 메타데이터
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    language: Optional[str] = None
    preferences: Dict[str, Any] = field(default_factory=dict)

    # 실행 정보
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    stage: ProcessingStage = ProcessingStage.VALIDATION

    # 추가 컨텍스트
    additional_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """파이프라인 실행 결과"""
    # 기본 정보
    success: bool
    input_type: InputType
    stage: ProcessingStage

    # 추출된 데이터
    extracted_text: Optional[str] = None
    extracted_data: Dict[str, Any] = field(default_factory=dict)

    # 메타데이터
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 분석 결과
    analysis: Optional[Dict[str, Any]] = None
    insights: List[str] = field(default_factory=list)

    # 통합 컨텍스트 (다음 워크플로우로 전달)
    unified_context: Optional[str] = None

    # 에러 정보
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    # 성능 지표
    processing_time_ms: Optional[float] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BasePipeline(ABC):
    """
    모든 파이프라인의 베이스 클래스

    공통 인터페이스를 제공하여 느슨한 결합과 높은 재사용성을 보장합니다.
    """

    def __init__(self, name: str, input_type: InputType):
        self.name = name
        self.input_type = input_type

    @abstractmethod
    async def validate(self, context: PipelineContext) -> bool:
        """
        입력 검증

        Args:
            context: 파이프라인 컨텍스트

        Returns:
            검증 성공 여부
        """
        pass

    @abstractmethod
    async def preprocess(self, context: PipelineContext) -> PipelineContext:
        """
        전처리 단계

        Args:
            context: 파이프라인 컨텍스트

        Returns:
            전처리된 컨텍스트
        """
        pass

    @abstractmethod
    async def extract(self, context: PipelineContext) -> PipelineResult:
        """
        정보 추출 단계

        Args:
            context: 파이프라인 컨텍스트

        Returns:
            추출 결과
        """
        pass

    @abstractmethod
    async def analyze(self, result: PipelineResult, context: PipelineContext) -> PipelineResult:
        """
        분석 단계

        Args:
            result: 추출 결과
            context: 파이프라인 컨텍스트

        Returns:
            분석이 추가된 결과
        """
        pass

    async def process(self, context: PipelineContext) -> PipelineResult:
        """
        전체 파이프라인 실행 (템플릿 메서드 패턴)

        Args:
            context: 파이프라인 컨텍스트

        Returns:
            최종 처리 결과
        """
        start_time = datetime.now(timezone.utc)

        try:
            # 1. 검증
            context.stage = ProcessingStage.VALIDATION
            if not await self.validate(context):
                return PipelineResult(
                    success=False,
                    input_type=self.input_type,
                    stage=ProcessingStage.FAILED,
                    error="Validation failed"
                )

            # 2. 전처리
            context.stage = ProcessingStage.PREPROCESSING
            context = await self.preprocess(context)

            # 3. 추출
            context.stage = ProcessingStage.EXTRACTION
            result = await self.extract(context)

            # 4. 분석
            context.stage = ProcessingStage.ANALYSIS
            result = await self.analyze(result, context)

            # 5. 완료
            result.stage = ProcessingStage.COMPLETED
            result.success = True

            # 처리 시간 계산
            end_time = datetime.now(timezone.utc)
            result.processing_time_ms = (end_time - start_time).total_seconds() * 1000

            return result

        except Exception as e:
            return PipelineResult(
                success=False,
                input_type=self.input_type,
                stage=ProcessingStage.FAILED,
                error=f"{self.name} pipeline error: {str(e)}"
            )

    def _create_error_result(self, error: str, stage: ProcessingStage = ProcessingStage.FAILED) -> PipelineResult:
        """에러 결과 생성 헬퍼 메서드"""
        return PipelineResult(
            success=False,
            input_type=self.input_type,
            stage=stage,
            error=error
        )


class PipelineRegistry:
    """파이프라인 레지스트리 (싱글톤)"""

    _instance = None
    _pipelines: Dict[InputType, BasePipeline] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, input_type: InputType, pipeline: BasePipeline):
        """파이프라인 등록"""
        self._pipelines[input_type] = pipeline

    def get(self, input_type: InputType) -> Optional[BasePipeline]:
        """파이프라인 조회"""
        return self._pipelines.get(input_type)

    def get_all(self) -> Dict[InputType, BasePipeline]:
        """모든 파이프라인 조회"""
        return self._pipelines.copy()

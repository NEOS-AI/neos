"""
통합 처리 서비스 - Strategy Pattern 적용

문서 처리와 워크플로우를 통합하는 서비스 레이어
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime
import asyncio
import uuid

from neos.api.models.unified_models import (
    UnifiedProcessingRequest,
    UnifiedStreamEvent,
    DocumentProcessingResult,
    ProcessingMode,
    DocumentInfo
)
from neos.workflow.graph import multi_agent_workflow
from neos.workflow.pipelines.document_pipeline import DocumentPipeline
from neos.workflow.pipelines.base import PipelineContext, FileInput
from neos.workflow.events import WorkflowEventHandler
from neos.utils.logger import get_logger
from neos.config.settings import settings

logger = get_logger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================

class UnifiedProcessingError(Exception):
    """Base exception for unified processing errors"""
    pass


class DocumentValidationError(UnifiedProcessingError):
    """Raised when document validation fails"""
    pass


class DocumentProcessingError(UnifiedProcessingError):
    """Raised when document processing fails"""
    pass


class WorkflowExecutionError(UnifiedProcessingError):
    """Raised when workflow execution fails"""
    pass


# ============================================================================
# Unified Event Handler: Convert workflow events to stream events
# ============================================================================

class UnifiedEventHandler(WorkflowEventHandler):
    """
    Workflow event handler for the unified API.

    Converts each step of the workflow into a UnifiedStreamEvent
    and sends it to the event queue.
    """

    def __init__(self, session_id: str, event_queue: asyncio.Queue):
        self.session_id = session_id
        self.event_queue = event_queue
        self.start_time = datetime.now()

    async def on_workflow_start(self, workflow_input: Dict[str, Any]):
        """Workflow start event handler"""
        event = UnifiedStreamEvent(
            event="workflow_started",
            session_id=self.session_id,
            phase="workflow_execution",
            progress_percent=0,
            content="Workflow started...",
            data={"query": workflow_input.get("query", "")[:100]}
        )
        await self.event_queue.put(event)

    async def on_node_start(self, node_name: str, step: int, total_steps: int):
        """Node start event handler"""
        progress = int((step / total_steps) * 100)

        # User-friendly messages
        node_messages = {
            "query_classifier": "Analyzing query...",
            "skill_tool_selector": "Selecting appropriate tools...",
            "search_orchestrator": "Searching for information...",
            "analysis_orchestrator": "Analyzing data...",
            "generation_orchestrator": "Generating content...",
            "result_integrator": "Integrating results...",
            "quality_validator": "Validating quality...",
            "response_generator": "Generating final response..."
        }

        event = UnifiedStreamEvent(
            event="node_started",
            session_id=self.session_id,
            phase="workflow_execution",
            node_name=node_name,
            progress_percent=progress,
            content=node_messages.get(node_name, f"{node_name} is running..."),
            data={"step": step, "total_steps": total_steps}
        )
        await self.event_queue.put(event)


    async def on_node_progress(
        self, node_name: str, message: str, progress: int = 0
    ):
        """Node progress event handler"""
        event = UnifiedStreamEvent(
            event="node_progress",
            session_id=self.session_id,
            phase="workflow_execution",
            node_name=node_name,
            content=message,
            data={"sub_progress": progress}
        )
        await self.event_queue.put(event)


    async def on_node_complete(self, node_name: str, result: Dict[str, Any]):
        """Node complete event handler"""
        event = UnifiedStreamEvent(
            event="node_completed",
            session_id=self.session_id,
            phase="workflow_execution",
            node_name=node_name,
            data=result
        )
        await self.event_queue.put(event)


    async def on_workflow_complete(self, result: Dict[str, Any]):
        """Workflow complete event handler"""
        elapsed_ms = int((datetime.now() - self.start_time).total_seconds() * 1000)

        event = UnifiedStreamEvent(
            event="workflow_completed",
            session_id=self.session_id,
            phase="workflow_execution",
            progress_percent=100,
            content="Workflow completed!",
            data={
                "response": result.get("response"),
                "quality_score": result.get("quality_score", 0.0),
                "cache_hit": result.get("cache_hit", False)
            },
            execution_time_ms=elapsed_ms
        )
        await self.event_queue.put(event)


    async def on_workflow_error(
        self, error: Exception, node_name: Optional[str] = None
    ):
        """Workflow error event handler"""
        event = UnifiedStreamEvent(
            event="error",
            session_id=self.session_id,
            phase="workflow_execution",
            node_name=node_name,
            error=str(error)
        )
        await self.event_queue.put(event)


# ============================================================================
# Strategy Pattern: 처리 전략 인터페이스
# ============================================================================

class ProcessingStrategy(ABC):
    """Processing Strategy base class"""

    def __init__(self, event_queue: Optional[asyncio.Queue] = None):
        self.event_queue = event_queue

    @abstractmethod
    async def process(
        self,
        request: UnifiedProcessingRequest,
        session_id: str
    ) -> Dict[str, Any]:
        """처리 실행"""
        pass

    async def emit_event(self, event: UnifiedStreamEvent):
        """이벤트 발행"""
        if self.event_queue:
            await self.event_queue.put(event)


class TextOnlyStrategy(ProcessingStrategy):
    """
    Text-only query processing strategy

    Directly passes user queries to the workflow without documents
    """

    async def process(
        self,
        request: UnifiedProcessingRequest,
        session_id: str
    ) -> Dict[str, Any]:
        """텍스트 쿼리 처리"""
        user_id = request.user_id or f"user_{uuid.uuid4().hex[:8]}"

        logger.info(
            "Starting text-only processing",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "query_length": len(request.query),
                "processing_mode": "text_only"
            }
        )

        # 시작 이벤트
        await self.emit_event(UnifiedStreamEvent(
            event="started",
            session_id=session_id,
            phase="workflow_execution",
            data={"query": request.query[:100]}
        ))

        # 워크플로우 실행 (이벤트 핸들러 inject)
        workflow_input = {
            "user_id": user_id,
            "session_id": session_id,
            "query": request.query
        }

        # UnifiedEventHandler 생성 (워크플로우 이벤트를 스트림 이벤트로 변환)
        workflow_event_handler = None
        if self.event_queue:
            workflow_event_handler = UnifiedEventHandler(session_id, self.event_queue)

        start_time = datetime.now()

        # Dependency Injection: event_handler를 워크플로우에 주입
        result = await multi_agent_workflow.execute_workflow(
            workflow_input,
            event_handler=workflow_event_handler
        )

        end_time = datetime.now()
        execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

        logger.info(
            "Text-only processing completed",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "execution_time_ms": execution_time_ms,
                "quality_score": result.get("quality_score", 0.0),
                "success": result.get("success", True)
            }
        )

        # Note: Completion event is emitted by UnifiedEventHandler.on_workflow_complete
        # to avoid duplication

        return {
            "success": result.get("success", True),
            "response": result.get("response"),
            "quality_score": result.get("quality_score", 0.0),
            "execution_time_ms": execution_time_ms,
            "metadata": result.get("metadata", {}),
            "errors": result.get("errors", [])
        }


class DocumentProcessingStrategy(ProcessingStrategy):
    """
    Document processing + workflow strategy

    Extract document information via DocumentPipeline,
    then execute the workflow with enhanced context.
    """

    def __init__(self, event_queue: Optional[asyncio.Queue] = None):
        super().__init__(event_queue)
        self.document_pipeline = DocumentPipeline()


    async def process(
        self,
        request: UnifiedProcessingRequest,
        session_id: str
    ) -> Dict[str, Any]:
        """문서 처리 + 워크플로우 실행"""
        user_id = request.user_id or f"user_{uuid.uuid4().hex[:8]}"

        logger.info(
            "Starting document processing",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "document_count": len(request.documents),
                "query_length": len(request.query),
                "enable_vision": request.enable_vision,
                "processing_mode": "document_with_workflow"
            }
        )

        # 1단계: 문서 검증
        await self.emit_event(UnifiedStreamEvent(
            event="document_validation",
            session_id=session_id,
            phase="document_extraction",
            progress_percent=5,
            content="문서 검증 중..."
        ))

        validation_result = await self._validate_documents(request.documents)
        if not validation_result["valid"]:
            raise DocumentValidationError(f"문서 검증 실패: {validation_result['error']}")

        # 2단계: 문서 처리 (병렬 처리로 성능 향상)
        await self.emit_event(UnifiedStreamEvent(
            event="document_processing",
            session_id=session_id,
            phase="document_extraction",
            progress_percent=10,
            content=f"{len(request.documents)}개 문서 추출 중..."
        ))

        # 병렬 처리로 여러 문서를 동시에 처리
        documents_results = await asyncio.gather(*[
            self._process_single_document(doc_info, request, session_id)
            for doc_info in request.documents
        ])

        # 3단계: 문서 정보를 쿼리에 통합
        await self.emit_event(UnifiedStreamEvent(
            event="context_integration",
            session_id=session_id,
            phase="document_extraction",
            progress_percent=50,
            content="문서 정보 통합 중..."
        ))

        enhanced_query = self._build_enhanced_query(request.query, documents_results)

        # 4단계: 워크플로우 실행
        await self.emit_event(UnifiedStreamEvent(
            event="workflow_starting",
            session_id=session_id,
            phase="workflow_execution",
            progress_percent=60,
            content="워크플로우 시작..."
        ))

        workflow_input = {
            "user_id": user_id,
            "session_id": session_id,
            "query": enhanced_query,
            "document_context": {
                "documents": documents_results,
                "total_documents": len(documents_results)
            }
        }

        # UnifiedEventHandler 생성 (워크플로우 이벤트를 스트림 이벤트로 변환)
        workflow_event_handler = None
        if self.event_queue:
            workflow_event_handler = UnifiedEventHandler(session_id, self.event_queue)

        start_time = datetime.now()

        # Dependency Injection: event_handler를 워크플로우에 주입
        result = await multi_agent_workflow.execute_workflow(
            workflow_input,
            event_handler=workflow_event_handler
        )

        end_time = datetime.now()
        execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

        logger.info(
            "Document processing completed",
            extra={
                "session_id": session_id,
                "user_id": user_id,
                "documents_processed": len(documents_results),
                "execution_time_ms": execution_time_ms,
                "quality_score": result.get("quality_score", 0.0),
                "success": result.get("success", True)
            }
        )

        # Note: Completion event is emitted by UnifiedEventHandler.on_workflow_complete
        # to avoid duplication

        return {
            "success": result.get("success", True),
            "response": result.get("response"),
            "quality_score": result.get("quality_score", 0.0),
            "execution_time_ms": execution_time_ms,
            "documents_processed": documents_results,
            "metadata": result.get("metadata", {}),
            "errors": result.get("errors", [])
        }


    async def _validate_documents(self, documents: List[DocumentInfo]) -> Dict[str, Any]:
        """Validate documents before processing"""
        if not documents or len(documents) == 0:
            return {"valid": False, "error": "문서가 제공되지 않았습니다"}

        for doc in documents:
            # 파일 확장자 확인
            from pathlib import Path
            ext = Path(doc.filename).suffix.lower()

            if ext not in self.document_pipeline.SUPPORTED_FORMATS:
                return {
                    "valid": False,
                    "error": f"지원하지 않는 파일 형식: {ext}. 지원 형식: {list(self.document_pipeline.SUPPORTED_FORMATS.keys())}"
                }

            # 파일 크기 확인 (설정된 경우)
            if doc.file_size and doc.file_size > self.document_pipeline.MAX_FILE_SIZE:
                return {
                    "valid": False,
                    "error": f"파일 크기 초과: {doc.file_size} bytes (최대: {self.document_pipeline.MAX_FILE_SIZE})"
                }

        return {"valid": True}


    async def _process_single_document(
        self,
        doc_info: DocumentInfo,
        request: UnifiedProcessingRequest,
        session_id: str
    ) -> DocumentProcessingResult:
        """Process a single document via DocumentPipeline"""
        # FileInput 생성
        file_input = FileInput(
            filename=doc_info.filename,
            mime_type=doc_info.mime_type,
            file_size=doc_info.file_size,
            file_content=doc_info.file_content,
            file_path=doc_info.file_path
        )

        # PipelineContext 생성
        context = PipelineContext(
            query=request.query,
            files=[file_input]
        )

        # 문서 파이프라인 실행
        # Vision 분석 활성화 제어
        self.document_pipeline.vision_enabled = request.enable_vision

        result = await self.document_pipeline.extract(context)

        if not result.success:
            raise DocumentProcessingError(f"문서 처리 실패: {result.error}")

        # DocumentProcessingResult로 변환
        extracted_data = result.extracted_data
        return DocumentProcessingResult(
            document_type=extracted_data.get("extraction_method", "unknown"),
            page_count=extracted_data.get("page_count"),
            slide_count=extracted_data.get("slide_count"),
            paragraph_count=extracted_data.get("paragraph_count"),
            text=result.extracted_text or "",
            char_count=extracted_data.get("char_count", 0),
            word_count=extracted_data.get("word_count", 0),
            has_images=extracted_data.get("has_images", False),
            has_tables=extracted_data.get("has_tables", False),
            image_count=len(extracted_data.get("images", [])),
            table_count=len(extracted_data.get("tables", [])),
            vision_analysis=extracted_data.get("vision_analysis"),
            metadata=extracted_data.get("metadata", {}),
            extraction_method=extracted_data.get("extraction_method", "unknown")
        )


    def _build_enhanced_query(
        self,
        original_query: str,
        documents_results: List[DocumentProcessingResult]
    ) -> str:
        """
        문서 정보가 통합된 쿼리 생성

        전체 텍스트 길이 제한을 적용하여 너무 긴 쿼리 방지
        """
        MAX_TOTAL_CHARS = 100000  # 전체 문서 텍스트 최대 제한
        MAX_PER_DOC = 10000      # 문서당 텍스트 제한
        MAX_VISION_ITEMS = 3    # 문서당 최대 Vision 분석 결과 수

        # 문서 정보 요약
        doc_summaries = []
        total_chars_used = 0

        for i, doc in enumerate(documents_results, 1):
            # 남은 용량 확인
            if total_chars_used >= MAX_TOTAL_CHARS:
                doc_summaries.append(f"\n## 문서 {i}+ 이후: (텍스트 길이 제한으로 생략됨)")
                break

            # 이 문서에 할당할 수 있는 최대 문자 수
            remaining_chars = min(MAX_PER_DOC, MAX_TOTAL_CHARS - total_chars_used)
            text_snippet = doc.text[:remaining_chars]
            total_chars_used += len(text_snippet)

            summary = f"""
## 문서 {i}
- 형식: {doc.document_type}
- 페이지/슬라이드: {doc.page_count or doc.slide_count or 'N/A'}
- 문자 수: {doc.char_count}
- 이미지 포함: {doc.image_count}개
- 표 포함: {doc.table_count}개

### 추출된 텍스트:
{text_snippet}{'...' if len(doc.text) > remaining_chars else ''}
"""
            # Vision 분석 결과 추가
            if doc.vision_analysis:
                summary += f"\n### Vision 분석 결과 ({len(doc.vision_analysis)}개 이미지):\n"
                for img_analysis in doc.vision_analysis[:MAX_VISION_ITEMS]:
                    vision = img_analysis.get("vision_analysis", {})
                    summary += f"- {vision.get('description', 'N/A')}\n"

            doc_summaries.append(summary)

        # 통합 쿼리 생성
        enhanced_query = f"""
# 사용자 질문
{original_query}

# 제공된 문서
{chr(10).join(doc_summaries)}

위 문서를 참고하여 사용자 질문에 답변해주세요.
"""
        return enhanced_query


# ============================================================================
# Factory Pattern: 전략 선택
# ============================================================================

class ProcessingStrategyFactory:
    """Processing Strategy Factory"""

    @staticmethod
    def create_strategy(
        request: UnifiedProcessingRequest,
        event_queue: Optional[asyncio.Queue] = None
    ) -> ProcessingStrategy:
        """Choose appropriate strategy based on request"""
        # 모드가 명시적으로 지정된 경우
        if request.mode == ProcessingMode.TEXT_ONLY:
            return TextOnlyStrategy(event_queue)
        elif request.mode == ProcessingMode.DOCUMENT_ONLY or request.mode == ProcessingMode.DOCUMENT_WITH_QUERY:
            return DocumentProcessingStrategy(event_queue)

        # AUTO 모드: 문서 유무에 따라 자동 선택
        if request.documents and len(request.documents) > 0:
            return DocumentProcessingStrategy(event_queue)
        else:
            return TextOnlyStrategy(event_queue)


# ============================================================================
# Unified Processing Service
# ============================================================================

class UnifiedProcessingService:
    """통합 처리 서비스"""

    @staticmethod
    async def process(
        request: UnifiedProcessingRequest,
        event_queue: Optional[asyncio.Queue] = None
    ) -> Dict[str, Any]:
        """통합 처리 실행"""
        session_id = request.session_id or str(uuid.uuid4())

        # 전략 선택
        strategy = ProcessingStrategyFactory.create_strategy(request, event_queue)

        # 처리 실행
        result = await strategy.process(request, session_id)

        # 세션 ID 추가
        result["session_id"] = session_id

        return result


    @staticmethod
    async def process_stream(
        request: UnifiedProcessingRequest
    ) -> AsyncGenerator[UnifiedStreamEvent, None]:
        """Streaming processing for unified requests"""
        session_id = request.session_id or str(uuid.uuid4())
        event_queue: asyncio.Queue = asyncio.Queue()

        # Choose strategy based on request
        strategy = ProcessingStrategyFactory.create_strategy(request, event_queue)

        # 비동기 처리 태스크 생성
        processing_task = asyncio.create_task(
            strategy.process(request, session_id)
        )

        try:
            # 이벤트 스트리밍
            completed = False
            while not completed:
                try:
                    # 이벤트 대기 (타임아웃은 설정에서 가져옴)
                    event = await asyncio.wait_for(
                        event_queue.get(),
                        timeout=settings.STREAM_EVENT_TIMEOUT
                    )
                    yield event

                    if event.event in ["completed", "error"]:
                        completed = True

                except asyncio.TimeoutError:
                    # 처리 완료 확인
                    if processing_task.done():
                        if processing_task.exception():
                            error_event = UnifiedStreamEvent(
                                event="error",
                                session_id=session_id,
                                error=str(processing_task.exception())
                            )
                            yield error_event
                        completed = True

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            error_event = UnifiedStreamEvent(
                event="error",
                session_id=session_id,
                error=str(e)
            )
            yield error_event

        finally:
            if not processing_task.done():
                processing_task.cancel()
                try:
                    await processing_task
                except asyncio.CancelledError:
                    pass

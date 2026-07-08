"""
통합 API 핸들러 - 문서 처리 + 워크플로우

디자인 패턴 적용:
- Strategy Pattern: 문서 처리 전략
- Factory Pattern: 전략 생성
- Template Method: 스트리밍 로직
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Optional, AsyncGenerator, List
import json
import uuid

from neos.api.models.unified_models import (
    UnifiedProcessingRequest,
    UnifiedProcessingResponse,
    UnifiedStreamEvent,
    DocumentInfo,
    ProcessingMode
)
from neos.api.services.unified_processor import (
    UnifiedProcessingService,
    DocumentValidationError,
    DocumentProcessingError,
    WorkflowExecutionError
)
from neos.api.dependencies.auth import get_current_active_user
from neos.database.models import User
from neos.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/unified", tags=["Unified Processing"])


# ============================================================================
# Helper Functions
# ============================================================================

def _with_authenticated_user(
    request: UnifiedProcessingRequest,
    current_user: User,
) -> UnifiedProcessingRequest:
    return request.model_copy(update={"user_id": current_user.user_id})

async def _convert_uploaded_files_to_documents(
    files: List[UploadFile]
) -> List[DocumentInfo]:
    """
    Convert uploaded files to DocumentInfo objects.

    Args:
        files: List of uploaded files from FastAPI

    Returns:
        List of DocumentInfo objects with file content
    """
    documents = []
    for file in files:
        content = await file.read()
        doc_info = DocumentInfo(
            filename=file.filename,
            mime_type=file.content_type,
            file_size=len(content),
            file_content=content
        )
        documents.append(doc_info)
    return documents


# ============================================================================
# Non-Streaming Endpoint
# ============================================================================

@router.post("/process", response_model=UnifiedProcessingResponse)
async def process_unified(
    request: UnifiedProcessingRequest,
    current_user: User = Depends(get_current_active_user),
):
    """
    통합 처리 엔드포인트 (Non-Streaming)

    문서가 있으면 파이프라인 처리 후 워크플로우 실행,
    없으면 바로 워크플로우 실행

    ### 사용 예시:
    1. 텍스트 쿼리만:
       ```json
       {
         "query": "AI의 최신 트렌드는?",
         "mode": "text_only"
       }
       ```

    2. 문서 + 쿼리:
       ```json
       {
         "query": "이 문서를 요약해주세요",
         "documents": [{"filename": "report.pdf", ...}],
         "mode": "document_with_query"
       }
       ```

    ### 응답:
    - documents_processed: 처리된 문서 정보 (있는 경우)
    - response: 최종 응답
    - quality_score: 응답 품질 점수
    - execution_time_ms: 실행 시간
    """
    try:
        request = _with_authenticated_user(request, current_user)
        result = await UnifiedProcessingService.process(request)

        return UnifiedProcessingResponse(
            success=result["success"],
            session_id=result["session_id"],
            documents_processed=result.get("documents_processed"),
            response=result["response"],
            quality_score=result["quality_score"],
            execution_time_ms=result["execution_time_ms"],
            metadata=result["metadata"],
            errors=result.get("errors", [])
        )

    except DocumentValidationError as e:
        logger.warning(f"Document validation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except DocumentProcessingError as e:
        logger.error(f"Document processing failed: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except WorkflowExecutionError as e:
        logger.error(f"Workflow execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Streaming Endpoint (SSE)
# ============================================================================

@router.post("/process/stream")
async def process_unified_stream(
    request: UnifiedProcessingRequest,
    current_user: User = Depends(get_current_active_user),
):
    """
    통합 처리 스트리밍 엔드포인트 (SSE)

    실시간으로 처리 진행 상황을 스트리밍합니다.

    ### 이벤트 타입:
    - `started`: 처리 시작
    - `document_validation`: 문서 검증 중
    - `document_processing`: 문서 처리 중
    - `context_integration`: 컨텍스트 통합 중
    - `workflow_starting`: 워크플로우 시작
    - `node_started`: 워크플로우 노드 시작
    - `completed`: 처리 완료
    - `error`: 에러 발생

    ### Phase:
    - `document_extraction`: 문서 추출 단계
    - `workflow_execution`: 워크플로우 실행 단계

    ### 클라이언트 사용 예시 (JavaScript):
    ```javascript
    const eventSource = new EventSource('/api/v1/unified/process/stream');
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      console.log(`Event: ${data.event}, Progress: ${data.progress_percent}%`);

      if (data.event === 'completed') {
        console.log('Response:', data.data.response);
        eventSource.close();
      }
    };
    ```
    """

    request = _with_authenticated_user(request, current_user)

    async def generate_stream() -> AsyncGenerator[str, None]:
        """SSE 스트림 생성"""
        try:
            async for event in UnifiedProcessingService.process_stream(request):
                # SSE 형식으로 전송
                event_data = event.dict(exclude_none=True)
                yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            error_event = UnifiedStreamEvent(
                event="error",
                session_id=request.session_id or str(uuid.uuid4()),
                error=str(e)
            )
            yield f"data: {json.dumps(error_event.dict(), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ============================================================================
# File Upload Endpoint
# ============================================================================

@router.post("/process/upload")
async def process_with_file_upload(
    query: str = Form(..., description="사용자 질문"),
    files: List[UploadFile] = File(..., description="업로드할 문서 파일"),
    mode: ProcessingMode = Form(ProcessingMode.AUTO, description="처리 모드"),
    enable_vision: bool = Form(True, description="Vision 분석 활성화"),
    bypass_cache: bool = Form(False, description="캐시 우회"),
    session_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None, deprecated=True),
    current_user: User = Depends(get_current_active_user),
):
    """
    파일 업로드 방식의 통합 처리 엔드포인트

    멀티파트 폼 데이터로 파일을 업로드하고 처리합니다.

    ### 사용 예시 (curl):
    ```bash
    curl -X POST "http://localhost:8000/api/v1/unified/process/upload" \\
      -F "query=이 문서를 요약해주세요" \\
      -F "files=@report.pdf" \\
      -F "enable_vision=true"
    ```

    ### 사용 예시 (Python):
    ```python
    import requests

    files = {'files': open('report.pdf', 'rb')}
    data = {
        'query': '이 문서를 요약해주세요',
        'enable_vision': True
    }
    response = requests.post(
        'http://localhost:8000/api/v1/unified/process/upload',
        files=files,
        data=data
    )
    ```
    """
    try:
        # 파일을 DocumentInfo로 변환
        documents = await _convert_uploaded_files_to_documents(files)

        # UnifiedProcessingRequest 생성
        request = UnifiedProcessingRequest(
            query=query,
            documents=documents,
            mode=mode,
            enable_vision=enable_vision,
            bypass_cache=bypass_cache,
            session_id=session_id,
            user_id=current_user.user_id,
        )

        # 처리 실행
        result = await UnifiedProcessingService.process(request)

        return JSONResponse(
            content={
                "success": result["success"],
                "session_id": result["session_id"],
                "documents_processed": len(result.get("documents_processed", [])),
                "response": result["response"],
                "quality_score": result["quality_score"],
                "execution_time_ms": result["execution_time_ms"],
                "metadata": result["metadata"]
            }
        )

    except DocumentValidationError as e:
        logger.warning(f"Document validation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except DocumentProcessingError as e:
        logger.error(f"Document processing failed: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except WorkflowExecutionError as e:
        logger.error(f"Workflow execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected file upload processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Streaming File Upload Endpoint
# ============================================================================

@router.post("/process/upload/stream")
async def process_with_file_upload_stream(
    query: str = Form(...),
    files: List[UploadFile] = File(...),
    mode: ProcessingMode = Form(ProcessingMode.AUTO),
    enable_vision: bool = Form(True),
    bypass_cache: bool = Form(False),
    session_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None, deprecated=True),
    current_user: User = Depends(get_current_active_user),
):
    """
    파일 업로드 + 스트리밍 처리 엔드포인트

    파일을 업로드하고 처리 과정을 실시간으로 스트리밍합니다.
    """
    try:
        # 파일을 DocumentInfo로 변환
        documents = await _convert_uploaded_files_to_documents(files)

        # UnifiedProcessingRequest 생성
        request = UnifiedProcessingRequest(
            query=query,
            documents=documents,
            mode=mode,
            enable_vision=enable_vision,
            bypass_cache=bypass_cache,
            session_id=session_id,
            user_id=current_user.user_id,
        )

        # 스트리밍 처리
        async def generate_stream() -> AsyncGenerator[str, None]:
            try:
                async for event in UnifiedProcessingService.process_stream(request):
                    event_data = event.dict(exclude_none=True)
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

            except Exception as e:
                logger.error(f"Streaming error: {e}")
                error_event = UnifiedStreamEvent(
                    event="error",
                    session_id=request.session_id or str(uuid.uuid4()),
                    error=str(e)
                )
                yield f"data: {json.dumps(error_event.dict(), ensure_ascii=False)}\n\n"

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"File upload streaming error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Health Check
# ============================================================================

@router.get("/health")
async def health_check():
    """통합 API 상태 확인"""
    return {
        "status": "healthy",
        "service": "Unified Processing API",
        "features": {
            "document_processing": True,
            "workflow_execution": True,
            "vision_analysis": True,
            "streaming": True
        },
        "supported_formats": [
            ".pdf", ".docx", ".doc",
            ".pptx", ".ppt",
            ".xlsx", ".xls",
            ".csv", ".txt", ".md"
        ]
    }

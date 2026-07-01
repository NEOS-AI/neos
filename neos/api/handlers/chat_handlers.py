"""Chat API handlers - thin layer for FastAPI routes"""

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Depends, Query
from fastapi.responses import StreamingResponse
from typing import Optional, AsyncGenerator, List, Union
from datetime import datetime
import uuid
import asyncio

from neos.api.models.chat_models import (
    CreateConversationRequest,
    UpdateConversationRequest,
    SendMessageRequest,
    RegenerateMessageRequest,
    EditMessageRequest,
    MessageFeedbackRequest,
    GenerateTitleRequest,
    ConversationResponse,
    ConversationWithMessagesResponse,
    ConversationListResponse,
    MessageResponse,
    CreateMessageResponse,
    SuccessResponse,
    ConversationSummary,
    ConversationAnalytics,
    UserChatStatistics,
    CreateTemplateRequest,
    ConversationTemplate,
    TemplateListResponse,
)
from neos.api.dependencies.auth import get_current_active_user, get_current_user
from neos.api.dependencies.resource_access import (
    get_owned_conversation,
    get_readable_conversation,
    require_same_user_id,
)
from neos.api.services.chat_service import ChatService
from neos.api.handlers.workflow_stream_handlers import WorkflowStreamCallback
from neos.database.connection import db_manager
from neos.database.models import User
from neos.services.chat_llm_service import chat_llm_service
from neos.api.services.chat_stream_pipeline import ChatStreamPipeline
from neos.utils.cost_calculator import cost_calculator
from neos.utils.logger import get_logger
from neos.workflow.graph import multi_agent_workflow
from neos.config.settings import settings as app_settings
from neos.tools.artifact_tools import get_artifact_tools
from neos.tools.artifact_tool_handler import execute_artifact_tool
from neos.tools.inline_vis_tools import get_inline_vis_tools, is_inline_vis_tool
from neos.tools.inline_vis_tool_handler import execute_inline_vis_tool as execute_inline_vis_tool_fn

# OpenResponses imports
from neos.api.adapters.stream_adapter import (
    format_sse_event,
    format_done_token,
    create_stream_generator,
    create_text_delta_event,
    create_function_call_event,
    create_completed_event,
    create_reasoning_start_events,
    create_reasoning_delta_event,
    create_reasoning_done_events,
    parse_harness_progress_event,
)
from neos.api.models.open_responses import (
    OutputItemDoneEvent,
    NeosArtifactMetaEvent,
    NeosArtifactDeltaEvent,
    NeosArtifactFinishEvent,
    NeosWorkflowProgressEvent,
    NeosUIFrameEvent,
    NeosInlineVizEvent,
    NeosInlineVizErrorEvent,
    MermaidVizData,
    ChartVizData,
    ResponseFailedEvent,
    ResponseStatus,
    ErrorInfo,
    ItemStatus,
)

# OpenResponses version header
OPEN_RESPONSES_VERSION = "2024-01-01"

logger = get_logger(__name__)
router = APIRouter()

# ============================================================================
# Advanced Tool Search 싱글톤 (Critical 1.1 / Medium 2.4)
# EmbeddingManager / ToolRegistryStore / SearchToolsHandler는 요청마다 생성하지 않고
# 모듈 레벨에서 한 번만 초기화한다. core_tools도 최초 1회만 DB에서 로드한다.
# ============================================================================
_search_handler = None  # SearchToolsHandler 싱글톤
_registry_store = None  # ToolRegistryStore 싱글톤
_core_tools_cache = None  # List[Dict] — 서버 재시작 전까지 고정


def _get_search_handler():
    global _search_handler, _registry_store
    if _search_handler is None:
        from neos.utils.embeddings import EmbeddingManager
        from neos.tools.tool_search.tool_registry_store import ToolRegistryStore
        from neos.tools.tool_search.search_tools_handler import SearchToolsHandler

        _embedding_mgr = EmbeddingManager()
        _registry_store = ToolRegistryStore(embedding_manager=_embedding_mgr)
        _search_handler = SearchToolsHandler(
            registry_store=_registry_store,
            top_k=app_settings.TOOL_SEARCH_TOP_K,
        )
    return _search_handler


async def _get_core_tools_cached() -> list:
    global _core_tools_cache, _registry_store
    if _core_tools_cache is None:
        _get_search_handler()  # _registry_store 초기화 보장
        core_tools = await _registry_store.get_core_tools()
        _core_tools_cache = [t.to_anthropic_tool() for t in core_tools]
    return _core_tools_cache


# ============================================================================
# Helper Functions
# ============================================================================

def map_node_to_agent(node_name: str) -> str:
    """
    워크플로우 노드명을 사용자 친화적인 에이전트명으로 매핑

    Args:
        node_name: 워크플로우 노드 이름

    Returns:
        사용자 친화적인 에이전트 이름
    """
    node_to_agent = {
        "query_classifier": "query_analysis",
        "skill_tool_selector": "tool_selection",
        "search_orchestrator": "knowledge_search",
        "analysis_orchestrator": "data_analysis",
        "generation_orchestrator": "content_generation",
        "result_integrator": "result_integration",
        "quality_validator": "quality_check",
        "response_generator": "response_generation"
    }
    return node_to_agent.get(node_name, node_name)


# ============================================================================
# Conversation Endpoints
# ============================================================================

@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    request: CreateConversationRequest,
    current_user: User = Depends(get_current_active_user),
):
    """새 대화 생성"""
    try:
        conversation = await ChatService.create_conversation(
            user_id=current_user.user_id,
            conversation_id=request.conversation_id,
            model_name=request.model_name,
            title=request.title,
            system_prompt=request.system_prompt,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            mode=request.mode.value if hasattr(request.mode, 'value') else request.mode,
            template_id=request.template_id,
            visibility=request.visibility,
            metadata=request.metadata
        )
        return ConversationResponse(**conversation)
    except Exception as e:
        logger.error(f"Failed to create conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    _conversation: dict = Depends(get_readable_conversation),
):
    """대화 조회"""
    try:
        conversation = await ChatService.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return ConversationResponse(**conversation)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}/full", response_model=ConversationWithMessagesResponse)
async def get_conversation_with_messages(
    conversation_id: str,
    limit: int = 100,
    before_sequence: Optional[int] = None,
    _conversation: dict = Depends(get_readable_conversation),
):
    """대화와 메시지 함께 조회 (주어진 conversation_id에 해당하는 대화 및 메시지 목록 반환)"""
    try:
        conversation = await ChatService.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = await ChatService.get_conversation_messages(
            conversation_id=conversation_id,
            limit=limit,
            before_sequence=before_sequence
        )

        # 참여자 수 조회
        participant_count_query = """
        SELECT COUNT(*) FROM conversation_participants
        WHERE conversation_id = $1 AND is_active = TRUE
        """
        participant_result = await db_manager.fetch_one(participant_count_query, conversation_id)
        participant_count = participant_result[0] if participant_result else 1

        return ConversationWithMessagesResponse(
            conversation=ConversationResponse(**conversation),
            messages=[MessageResponse(**msg) for msg in messages],
            participant_count=participant_count,
            has_more_messages=len(messages) >= limit
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get conversation with messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: str,
    request: UpdateConversationRequest,
    _conversation: dict = Depends(get_owned_conversation),
):
    """대화 업데이트"""
    try:
        conversation = await ChatService.update_conversation(
            conversation_id=conversation_id,
            title=request.title,
            system_prompt=request.system_prompt,
            temperature=request.temperature,
            is_pinned=request.is_pinned,
            tags=request.tags,
            metadata=request.metadata,
            visibility=request.visibility,
        )
        return ConversationResponse(**conversation)
    except Exception as e:
        logger.error(f"Failed to update conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conversations/{conversation_id}", response_model=SuccessResponse)
async def delete_conversation(
    conversation_id: str,
    permanent: bool = False,
    _conversation: dict = Depends(get_owned_conversation),
):
    """대화 삭제"""
    try:
        success = await ChatService.delete_conversation(
            conversation_id=conversation_id,
            soft_delete=not permanent
        )
        return SuccessResponse(
            success=success,
            message=f"Conversation {'permanently deleted' if permanent else 'deleted'}"
        )
    except Exception as e:
        logger.error(f"Failed to delete conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/archive", response_model=ConversationResponse)
async def archive_conversation(
    conversation_id: str,
    _conversation: dict = Depends(get_owned_conversation),
):
    """대화 아카이브"""
    try:
        conversation = await ChatService.archive_conversation(conversation_id)
        return ConversationResponse(**conversation)
    except Exception as e:
        logger.error(f"Failed to archive conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/conversations", response_model=ConversationListResponse)
async def list_user_conversations(
    user_id: str,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    include_archived: bool = False,
    current_user: User = Depends(get_current_active_user),
):
    """사용자의 대화 목록 조회"""
    require_same_user_id(user_id, current_user)
    try:
        result = await ChatService.list_conversations(
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset,
            include_archived=include_archived
        )

        return ConversationListResponse(
            conversations=[ConversationSummary(**conv) for conv in result["conversations"]],
            total_count=result["total_count"],
            has_more=result["has_more"]
        )
    except Exception as e:
        logger.error(f"Failed to list conversations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{user_id}/conversations", response_model=SuccessResponse)
async def delete_all_user_conversations(
    user_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """사용자의 모든 대화 삭제"""
    require_same_user_id(user_id, current_user)
    try:
        count = await ChatService.delete_user_conversations(user_id)
        return SuccessResponse(success=True, message=f"Deleted {count} conversations")
    except Exception as e:
        logger.error(f"Failed to delete user conversations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conversations/{conversation_id}/messages/after", response_model=SuccessResponse)
async def delete_messages_after_timestamp(
    conversation_id: str,
    timestamp: datetime = Query(..., description="이 시점 이후 메시지 삭제 (ISO 8601)"),
    _conversation: dict = Depends(get_owned_conversation),
):
    """특정 시점 이후 메시지 삭제 (편집 기능용)"""
    try:
        await ChatService.delete_messages_after_timestamp(conversation_id, timestamp)
        return SuccessResponse(success=True, message="Messages deleted")
    except Exception as e:
        logger.error(f"Failed to delete messages after timestamp: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/message-count")
async def get_user_message_count(
    user_id: str,
    hours: int = Query(24, ge=1, le=168, description="집계 기간(시간)"),
    current_user: User = Depends(get_current_active_user),
):
    """최근 N시간 내 사용자 메시지 수 (rate limit 확인용)"""
    require_same_user_id(user_id, current_user)
    try:
        count = await ChatService.get_user_message_count(user_id, hours)
        return {"user_id": user_id, "hours": hours, "count": count}
    except Exception as e:
        logger.error(f"Failed to get user message count: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/generate-title")
async def generate_conversation_title(
    conversation_id: str,
    request: GenerateTitleRequest,
    _conversation: dict = Depends(get_owned_conversation),
):
    """대화 제목 자동 생성"""
    try:
        # 대화 존재 확인
        conversation = await ChatService.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # 제목 생성 (사용자 메시지 전달)
        title = await ChatService.generate_title(
            conversation_id=conversation_id,
            user_message=request.user_message
        )

        # 제목 업데이트
        await ChatService.update_conversation(
            conversation_id=conversation_id,
            title=title
        )

        return {
            "success": True,
            "title": title,
            "conversation_id": conversation_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate title: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Message Endpoints
# ============================================================================

@router.post("/conversations/{conversation_id}/messages", response_model=CreateMessageResponse)
async def send_message(conversation_id: str, request: SendMessageRequest):
    """메시지 전송 및 AI 응답 생성"""
    try:
        # 사용자 메시지 저장
        user_message = await ChatService.add_message(
            conversation_id=conversation_id,
            role=request.role.value,
            content=request.content,
            attachments=request.attachments,
            parent_message_id=request.parent_message_id,
            metadata=request.metadata
        )

        # AI 응답 생성 (실제 LLM 통합)
        assistant_message = None
        if request.role.value == "user":
            # 대화 정보 및 히스토리 가져오기
            conversation = await ChatService.get_conversation(conversation_id)

            # 대화 히스토리 조회 (최근 20개 메시지)
            history_messages = await ChatService.get_conversation_messages(
                conversation_id=conversation_id,
                limit=20
            )

            # 메시지 ID 생성
            assistant_message_id = str(uuid.uuid4())

            # LLM 응답 생성
            llm_response = await chat_llm_service.generate_response(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                conversation_messages=history_messages + [{"role": "user", "content": request.content}],
                model_name=conversation.get("model_name"),
                system_prompt=conversation.get("system_prompt"),
                temperature=conversation.get("temperature", 0.7),
                max_tokens=conversation.get("max_tokens")
            )

            # 어시스턴트 메시지 저장
            assistant_message = await ChatService.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=llm_response["content"],
                message_id=assistant_message_id,
                model_name=llm_response["model_name"],
                total_tokens=llm_response["usage"]["total_tokens"],
                prompt_tokens=llm_response["usage"]["prompt_tokens"],
                completion_tokens=llm_response["usage"]["completion_tokens"],
                metadata={
                    "cost_usd": float(llm_response["cost"]["total_cost"]),
                    "latency_ms": llm_response["latency_ms"],
                    "finish_reason": llm_response["finish_reason"]
                }
            )

            # 메시지 저장 후 비용 기록 (FK 제약 위반 방지)
            await cost_calculator.record_cost_for_existing_message(
                message_id=assistant_message_id,
                conversation_id=conversation_id,
                provider=llm_response["provider"],
                model_name=llm_response["model_name"],
                prompt_tokens=llm_response["usage"]["prompt_tokens"],
                completion_tokens=llm_response["usage"]["completion_tokens"],
                total_tokens=llm_response["usage"]["total_tokens"],
                latency_ms=llm_response["latency_ms"],
                finish_reason=llm_response["finish_reason"]
            )

        return CreateMessageResponse(
            success=True,
            user_message=MessageResponse(**user_message),
            assistant_message=MessageResponse(**assistant_message) if assistant_message else None,
            conversation_id=conversation_id,
            errors=[]
        )

    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_conversation_messages(
    conversation_id: str,
    limit: int = 100,
    before_sequence: Optional[int] = None,
    after_sequence: Optional[int] = None
):
    """대화의 메시지 목록 조회"""
    try:
        messages = await ChatService.get_conversation_messages(
            conversation_id=conversation_id,
            limit=limit,
            before_sequence=before_sequence,
            after_sequence=after_sequence
        )
        return [MessageResponse(**msg) for msg in messages]
    except Exception as e:
        logger.error(f"Failed to get messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages/{message_id}", response_model=MessageResponse)
async def get_message(message_id: str):
    """메시지 조회"""
    try:
        message = await ChatService.get_message(message_id)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        return MessageResponse(**message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/messages/{message_id}", response_model=MessageResponse)
async def edit_message(message_id: str, request: EditMessageRequest):
    """메시지 편집"""
    try:
        message = await ChatService.edit_message(
            message_id=message_id,
            new_content=request.new_content,
            edited_by=request.user_id,
            edit_reason=request.edit_reason
        )
        return MessageResponse(**message)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to edit message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/messages/{message_id}/feedback", response_model=MessageResponse)
async def add_message_feedback(message_id: str, request: MessageFeedbackRequest):
    """메시지에 피드백 추가"""
    try:
        message = await ChatService.add_message_feedback(
            message_id=message_id,
            feedback=request.feedback,
            comment=request.comment
        )
        return MessageResponse(**message)
    except Exception as e:
        logger.error(f"Failed to add feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/messages/{message_id}", response_model=SuccessResponse)
async def delete_message(message_id: str):
    """메시지 삭제"""
    try:
        success = await ChatService.delete_message(message_id)
        return SuccessResponse(success=success, message="Message deleted")
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/messages/{message_id}/regenerate")
async def regenerate_message(message_id: str, request: RegenerateMessageRequest):
    """메시지 재생성 (alternative response)"""
    try:
        # 원본 메시지 조회
        original_message = await ChatService.get_message(message_id)
        if not original_message:
            raise HTTPException(status_code=404, detail="Message not found")

        # 대화 정보 및 히스토리 가져오기
        conversation = await ChatService.get_conversation(original_message["conversation_id"])

        # 원본 메시지까지의 히스토리 조회
        history_messages = await ChatService.get_conversation_messages(
            conversation_id=original_message["conversation_id"],
            limit=20,
            before_sequence=original_message["sequence_number"]
        )

        # 새 메시지 ID 생성
        new_message_id = str(uuid.uuid4())

        # 실제 LLM으로 재생성
        llm_response = await chat_llm_service.generate_response(
            conversation_id=original_message["conversation_id"],
            message_id=new_message_id,
            conversation_messages=history_messages,
            model_name=request.model_name or conversation.get("model_name"),
            system_prompt=conversation.get("system_prompt"),
            temperature=request.temperature or conversation.get("temperature", 0.7),
            max_tokens=conversation.get("max_tokens")
        )

        # 새 메시지 저장
        new_message = await ChatService.add_message(
            conversation_id=original_message["conversation_id"],
            role="assistant",
            content=llm_response["content"],
            message_id=new_message_id,
            model_name=llm_response["model_name"],
            parent_message_id=original_message.get("parent_message_id"),
            total_tokens=llm_response["usage"]["total_tokens"],
            prompt_tokens=llm_response["usage"]["prompt_tokens"],
            completion_tokens=llm_response["usage"]["completion_tokens"],
            metadata={
                "cost_usd": float(llm_response["cost"]["total_cost"]),
                "latency_ms": llm_response["latency_ms"],
                "finish_reason": llm_response["finish_reason"],
                "regenerated_from": message_id
            }
        )

        # 메시지 저장 후 비용 기록 (FK 제약 위반 방지)
        await cost_calculator.record_cost_for_existing_message(
            message_id=new_message_id,
            conversation_id=original_message["conversation_id"],
            provider=llm_response["provider"],
            model_name=llm_response["model_name"],
            prompt_tokens=llm_response["usage"]["prompt_tokens"],
            completion_tokens=llm_response["usage"]["completion_tokens"],
            total_tokens=llm_response["usage"]["total_tokens"],
            latency_ms=llm_response["latency_ms"],
            finish_reason=llm_response["finish_reason"]
        )

        return MessageResponse(**new_message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to regenerate message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Streaming Endpoint
# ============================================================================

def _get_chat_stream_pipeline() -> ChatStreamPipeline:
    _chat_stream_pipeline = ChatStreamPipeline(
        chat_llm_service=chat_llm_service,
        cost_calculator=cost_calculator,
        get_core_tools_fn=_get_core_tools_cached,
        get_search_handler_fn=_get_search_handler,
        chat_service_cls=ChatService,
        multi_agent_workflow=multi_agent_workflow,
        workflow_callback_cls=WorkflowStreamCallback,
        map_node_to_agent_fn=map_node_to_agent,
    )
    return _chat_stream_pipeline


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: User = Depends(get_current_user)
):
    """스트리밍 메시지 전송 (아티팩트 지원)"""
    pipeline = _get_chat_stream_pipeline()

    return StreamingResponse(
        pipeline.run(conversation_id, request, current_user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-OpenResponses-Version": OPEN_RESPONSES_VERSION,
        },
    )


# @deprecated(reason="점진적 리팩토링 완료 후 제거 예정 (대체: /stream)")
@router.post("/conversations/{conversation_id}/messages/stream_legacy")
async def stream_message_legacy(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: User = Depends(get_current_user)
):
    """[Legacy] 리팩토링 전 stream_message 구현 — 점진적 전환용."""

    async def generate_stream() -> AsyncGenerator[str, None]:
        try:
            # 사용자 메시지 저장
            user_message = await ChatService.add_message(
                conversation_id=conversation_id,
                role=request.role.value,
                content=request.content,
                attachments=request.attachments,
                parent_message_id=request.parent_message_id,
                metadata=request.metadata
            )

            # 메시지 ID 생성 (여기서 미리 생성)
            assistant_message_id = str(uuid.uuid4())

            # OpenResponses: 스트림 상태 및 시작 이벤트 생성
            stream_state, start_event = create_stream_generator(
                response_id=conversation_id,
                message_id=assistant_message_id
            )
            yield format_sse_event(start_event)

            # 대화 정보 및 히스토리 가져오기
            conversation = await ChatService.get_conversation(conversation_id)
            history_messages = await ChatService.get_conversation_messages(
                conversation_id=conversation_id,
                limit=20
            )

            # ============================================================
            # 워크플로우 실행 (활성화된 경우)
            # ============================================================
            workflow_result = None
            workflow_agents = []  # 워크플로우 에이전트 추적 (메타데이터용)

            if app_settings.ENABLE_WORKFLOW_IN_CHAT:
                try:
                    # 이벤트 큐 생성
                    event_queue = asyncio.Queue(maxsize=100)

                    # 워크플로우 콜백 생성
                    workflow_callback = WorkflowStreamCallback(
                        session_id=conversation_id,
                        event_queue=event_queue,
                        enable_db_logging=False,  # 채팅에서는 DB 로깅 비활성화
                        user_id=current_user.user_id
                    )

                    # 대화 히스토리 포맷 변환
                    formatted_history = []
                    if app_settings.CHAT_HISTORY_ENABLED and history_messages:
                        formatted_history = [
                            {
                                "role": msg["role"],
                                "content": msg["content"],
                                "timestamp": msg.get("created_at")
                            }
                            for msg in history_messages[:app_settings.MAX_HISTORY_MESSAGES]
                        ]
                        logger.info(f"[ChatHandler] Passing {len(formatted_history)} history messages to workflow")

                    # 워크플로우 비동기 실행 (채팅은 stateless이므로 checkpointer 비활성화)
                    workflow_task = asyncio.create_task(
                        multi_agent_workflow.execute_workflow(
                            user_input={
                                "user_id": current_user.user_id,
                                "session_id": conversation_id,
                                "query": request.content,
                                # 채팅 히스토리 추가
                                "chat_history": formatted_history,
                                "enable_history_context": True  # 기본 활성화
                            },
                            event_handler=workflow_callback,
                            use_checkpointer=False  # 채팅 API는 단일 요청이므로 state persistence 불필요
                        )
                    )

                    # 이벤트 루프: 워크플로우 이벤트를 SSE로 전송
                    while True:
                        try:
                            # 짧은 타임아웃으로 이벤트 대기
                            event = await asyncio.wait_for(event_queue.get(), timeout=0.5)

                            # OpenResponses: 노드 시작 → function_call 아이템 추가
                            if event.event == "node_started":
                                agent_name = map_node_to_agent(event.node_name)
                                workflow_agents.append({
                                    "agent_name": agent_name,
                                    "node_name": event.node_name,
                                    "status": "input-available"
                                })

                                fc_event = create_function_call_event(
                                    stream_state, event.node_name, agent_name
                                )
                                yield format_sse_event(fc_event)

                            # OpenResponses: 노드 완료 → function_call 아이템 완료
                            elif event.event == "node_completed":
                                agent_name = map_node_to_agent(event.node_name)
                                # 에이전트 상태 업데이트
                                for agent in workflow_agents:
                                    if agent["node_name"] == event.node_name:
                                        agent["status"] = "output-available"

                                # function_call 완료 이벤트
                                if event.node_name in stream_state.function_calls:
                                    fc = stream_state.function_calls[event.node_name]
                                    fc.status = ItemStatus.COMPLETED
                                    done_event = OutputItemDoneEvent(
                                        output_index=stream_state.output_index,
                                        item=fc
                                    )
                                    yield format_sse_event(done_event)

                            # OpenResponses: 진행 상황 → neos:workflow_progress (확장)
                            elif event.event == "agent_progress":
                                progress_event = NeosWorkflowProgressEvent(
                                    progress_percent=event.progress_percent,
                                    message=event.content if event.content else None
                                )
                                yield format_sse_event(progress_event)

                            elif event.event == "node_progress":
                                harness_event = parse_harness_progress_event(
                                    node_name=event.node_name,
                                    message=event.content,
                                )
                                if harness_event is not None:
                                    yield format_sse_event(harness_event)

                            # Phase 8 (A2UI): UIFrame → neos:ui_frame (확장)
                            elif event.event == "ui_frame":
                                ui_frame_event = NeosUIFrameEvent(
                                    ui_frame=event.data.get("ui_frame", {})
                                )
                                yield format_sse_event(ui_frame_event)

                            # 워크플로우 완료 이벤트
                            elif event.event == "completed":
                                # 워크플로우 결과 가져오기
                                workflow_result = await workflow_task
                                break

                        except asyncio.TimeoutError:
                            # 타임아웃 시 워크플로우 완료 여부 확인
                            if workflow_task.done():
                                workflow_result = await workflow_task
                                break

                except Exception as e:
                    import traceback
                    error_details = traceback.format_exc()
                    logger.error(f"Workflow execution failed: {str(e)}")
                    logger.error(f"Traceback:\n{error_details}")
                    logger.warning("Falling back to direct LLM.")
                    # 워크플로우 실패 시에도 계속 진행 (폴백)
                    workflow_result = None

            # 시스템 프롬프트 구성
            system_prompt = conversation.get("system_prompt", "")
            tools = []

            # 워크플로우 결과를 시스템 프롬프트에 추가
            if workflow_result and workflow_result.get("response"):
                workflow_context = f"""
# Workflow Results
The multi-agent workflow has gathered the following information to help answer the user's question:

{workflow_result['response'][:5000]}

Use this information to provide a comprehensive and accurate answer. If needed, you can create artifacts using the available tools.
"""
                system_prompt = f"{system_prompt}\n\n{workflow_context}"

            tools: list = []

            if app_settings.ARTIFACTS_ENABLED:
                system_prompt = f"{system_prompt}\n\n{app_settings.ARTIFACTS_SYSTEM_PROMPT}"
                tools = get_artifact_tools()

            if app_settings.INLINE_VIS_ENABLED:
                tools = tools + get_inline_vis_tools()
                system_prompt = f"{system_prompt}\n\n{app_settings.INLINE_VIS_SYSTEM_PROMPT}"

            # ============================================================
            # 실제 LLM 스트리밍 (tool calling 지원)
            # ============================================================
            full_content = ""
            usage_info = None
            cost_info = None
            latency_ms = None
            artifact_info = None  # artifact 정보 추적
            inline_viz_list: list = []  # 인라인 시각화 목록 추적

            # Advanced Tool Search 또는 기존 방식 분기
            # TOOL_SEARCH_ENABLED는 ARTIFACTS_ENABLED=true 일 때만 동작합니다.
            if app_settings.TOOL_SEARCH_ENABLED and app_settings.ARTIFACTS_ENABLED:
                core_tools_dicts = await _get_core_tools_cached()

                llm_stream = chat_llm_service.generate_response_stream_with_tool_search(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    conversation_messages=history_messages + [{"role": "user", "content": request.content}],
                    core_tools=core_tools_dicts,
                    search_handler=_get_search_handler(),
                    model_name=conversation.get("model_name"),
                    system_prompt=system_prompt,
                    temperature=conversation.get("temperature", 0.7),
                    max_tokens=conversation.get("max_tokens"),
                    max_tool_rounds=app_settings.TOOL_SEARCH_MAX_ROUNDS,
                )
            else:
                llm_stream = chat_llm_service.generate_response_stream_with_tools(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    conversation_messages=history_messages + [{"role": "user", "content": request.content}],
                    tools=tools,
                    model_name=conversation.get("model_name"),
                    system_prompt=system_prompt,
                    temperature=conversation.get("temperature", 0.7),
                    max_tokens=conversation.get("max_tokens"),
                )

            async for chunk in llm_stream:
                if chunk["type"] == "start":
                    # 스트리밍 시작
                    pass
                elif chunk["type"] == "reasoning_start":
                    # OpenResponses: reasoning 아이템 시작
                    for event in create_reasoning_start_events(stream_state):
                        yield format_sse_event(event)
                elif chunk["type"] == "reasoning":
                    # OpenResponses: reasoning 델타 이벤트 (thinking block)
                    # reasoning_start가 없으면 자동으로 시작
                    if not stream_state.reasoning_item:
                        for event in create_reasoning_start_events(stream_state):
                            yield format_sse_event(event)
                    delta_event = create_reasoning_delta_event(stream_state, chunk["content"])
                    yield format_sse_event(delta_event)
                elif chunk["type"] == "content":
                    # 텍스트 시작 전에 진행 중인 reasoning이 있으면 완료 처리
                    if stream_state.reasoning_item and stream_state.reasoning_item.status.value == "in_progress":
                        for event in create_reasoning_done_events(stream_state):
                            yield format_sse_event(event)
                    # OpenResponses: 텍스트 델타 이벤트
                    full_content += chunk["content"]
                    delta_event = create_text_delta_event(stream_state, chunk["content"])
                    yield format_sse_event(delta_event)
                elif chunk["type"] == "tool_use":
                    # 진행 중인 reasoning이 있으면 완료 처리
                    if stream_state.reasoning_item and stream_state.reasoning_item.status.value == "in_progress":
                        for event in create_reasoning_done_events(stream_state):
                            yield format_sse_event(event)
                    # Tool 호출 감지 - 아티팩트 도구 실행
                    tool_name = chunk.get("tool_name")
                    tool_input = chunk.get("tool_input")

                    logger.info(f"Tool called: {tool_name} with input: {tool_input}")

                    # ── 인라인 시각화 도구 분기 (DB 세션 불필요) ─────────────
                    if app_settings.INLINE_VIS_ENABLED and is_inline_vis_tool(tool_name):
                        async for tool_event in execute_inline_vis_tool_fn(
                            tool_name=tool_name,
                            tool_input=tool_input,
                        ):
                            event_type = tool_event.get("type")

                            if event_type == "inline_viz":
                                viz_type = tool_event["viz_type"]
                                raw_data = tool_event["data"]

                                # data 페이로드를 Pydantic 모델로 검증
                                if viz_type == "mermaid":
                                    validated_data: Union[MermaidVizData, ChartVizData] = MermaidVizData(**raw_data)
                                else:
                                    validated_data = ChartVizData(
                                        title=raw_data["title"],
                                        type=raw_data["type"],
                                        data=raw_data["data"],
                                    )

                                inline_viz_event = NeosInlineVizEvent(
                                    viz_id=tool_event["viz_id"],
                                    viz_type=viz_type,
                                    data=validated_data,
                                )
                                # model_dump()으로 viz_entry 생성하여 필드 불일치 방지
                                event_dict = inline_viz_event.model_dump()
                                viz_entry = {
                                    "id": event_dict["viz_id"],
                                    "viz_type": event_dict["viz_type"],
                                    "data": event_dict["data"],
                                }
                                inline_viz_list.append(viz_entry)
                                yield format_sse_event(inline_viz_event)

                            elif event_type == "error":
                                err_msg = tool_event.get("error", "Unknown inline visualization error")
                                logger.error(f"[InlineVis] Tool error ({tool_name}): {err_msg}")
                                error_event = NeosInlineVizErrorEvent(
                                    tool_name=tool_name,
                                    error=err_msg,
                                )
                                yield format_sse_event(error_event)
                                # 시각화 실패는 치명적이지 않으므로 스트림 중단하지 않음

                    # ── INLINE_VIS_ENABLED=false 상태에서 inline vis 도구 호출 방어 ──
                    elif is_inline_vis_tool(tool_name):
                        # LLM이 이전 세션 system prompt 캐시 등으로 renderDiagram/renderChart를
                        # 호출할 수 있음. 아티팩트 핸들러로 넘어가면 잘못된 DB 레코드 생성 가능.
                        logger.warning(
                            f"[InlineVis] {tool_name} called but INLINE_VIS_ENABLED=false. "
                            "Skipping to prevent artifact handler misbehavior."
                        )

                    # ── 기존 아티팩트 도구 분기 ──────────────────────────────
                    else:
                        # DB 세션 가져오기
                        async with await db_manager.get_session() as db_session:
                            # 백엔드 user_id 사용 (인증된 사용자)
                            user_id = current_user.user_id
                            logger.info(f"Using backend user_id: {user_id} for artifact creation")

                            # 아티팩트 도구 실행 및 스트리밍
                            async for tool_event in execute_artifact_tool(
                                tool_name=tool_name,
                                tool_input=tool_input,
                                user_id=user_id,
                                db_session=db_session,
                                conversation_id=conversation_id
                            ):
                                event_type = tool_event.get("type")

                                if event_type == "artifact_meta":
                                    # OpenResponses: neos:artifact_meta (확장 이벤트)
                                    artifact_info = {
                                        "id": tool_event.get("artifact_id"),
                                        "title": tool_event.get("artifact_title"),
                                        "kind": tool_event.get("artifact_kind")
                                    }
                                    meta_event = NeosArtifactMetaEvent(
                                        artifact_id=tool_event.get("artifact_id", ""),
                                        artifact_title=tool_event.get("artifact_title", ""),
                                        artifact_kind=tool_event.get("artifact_kind", "text")
                                    )
                                    yield format_sse_event(meta_event)

                                elif event_type == "artifact_delta":
                                    # OpenResponses: neos:artifact_delta (확장 이벤트)
                                    delta_event = NeosArtifactDeltaEvent(
                                        content=tool_event.get("content", "")
                                    )
                                    yield format_sse_event(delta_event)

                                elif event_type == "artifact_finish":
                                    # OpenResponses: neos:artifact_finish (확장 이벤트)
                                    finish_event = NeosArtifactFinishEvent(
                                        artifact_id=tool_event.get("artifact_id")
                                    )
                                    yield format_sse_event(finish_event)

                                elif event_type == "tool_result":
                                    # Tool 실행 결과를 채팅 메시지에 추가
                                    # (단, artifact tool인 경우는 제외 - artifact 블록으로 표시됨)
                                    if not artifact_info:
                                        result_content = tool_event.get("content", "")
                                        full_content += f"\n\n{result_content}"

                                elif event_type == "error":
                                    # OpenResponses: response.failed 이벤트
                                    logger.error(f"Tool execution error: {tool_event.get('error')}")
                                    stream_state.response.status = ResponseStatus.FAILED
                                    stream_state.response.error = ErrorInfo(
                                        type="server_error",
                                        message=tool_event.get("error", "Tool execution failed")
                                    )
                                    failed_event = ResponseFailedEvent(response=stream_state.response)
                                    yield format_sse_event(failed_event)

                elif chunk["type"] == "complete":
                    # 진행 중인 reasoning이 있으면 완료 처리
                    if stream_state.reasoning_item and stream_state.reasoning_item.status.value == "in_progress":
                        for event in create_reasoning_done_events(stream_state):
                            yield format_sse_event(event)
                    # 완료
                    usage_info = chunk["usage"]
                    cost_info = chunk["cost"]
                    latency_ms = chunk["latency_ms"]
                elif chunk["type"] == "error":
                    # OpenResponses: response.failed 이벤트
                    stream_state.response.status = ResponseStatus.FAILED
                    stream_state.response.error = ErrorInfo(
                        type="server_error",
                        message=chunk.get("error", "Unknown error")
                    )
                    failed_event = ResponseFailedEvent(response=stream_state.response)
                    yield format_sse_event(failed_event)
                    yield format_done_token()
                    return

            # 어시스턴트 메시지 저장 (artifact 정보 포함)
            message_metadata = {
                "cost_usd": float(cost_info["total_cost"]) if cost_info else 0.0,
                "latency_ms": latency_ms
            }

            # artifact 정보가 있으면 metadata에 포함
            if artifact_info:
                message_metadata["artifact"] = artifact_info

            # 인라인 시각화 정보가 있으면 metadata에 포함
            if inline_viz_list:
                message_metadata["inline_visualizations"] = inline_viz_list

            # 워크플로우 에이전트 정보가 있으면 metadata에 포함
            if workflow_agents:
                message_metadata["workflow_agents"] = workflow_agents

            assistant_message = await ChatService.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=full_content,
                message_id=assistant_message_id,
                model_name=conversation.get("model_name"),
                total_tokens=usage_info["total_tokens"] if usage_info else 0,
                prompt_tokens=usage_info["prompt_tokens"] if usage_info else 0,
                completion_tokens=usage_info["completion_tokens"] if usage_info else 0,
                metadata=message_metadata
            )

            # 메시지 저장 후 비용 기록 (FK 제약 위반 방지)
            if usage_info and cost_info:
                provider = "anthropic" if "claude" in conversation.get("model_name", "").lower() else "openai"
                await cost_calculator.record_cost_for_existing_message(
                    message_id=assistant_message_id,
                    conversation_id=conversation_id,
                    provider=provider,
                    model_name=conversation.get("model_name"),
                    prompt_tokens=usage_info["prompt_tokens"],
                    completion_tokens=usage_info["completion_tokens"],
                    total_tokens=usage_info["total_tokens"],
                    latency_ms=latency_ms,
                    finish_reason="end_turn"
                )

            # OpenResponses: response.completed 이벤트
            completed_event = create_completed_event(
                stream_state,
                usage={
                    "prompt_tokens": usage_info["prompt_tokens"] if usage_info else 0,
                    "completion_tokens": usage_info["completion_tokens"] if usage_info else 0
                }
            )
            yield format_sse_event(completed_event)

            # OpenResponses: [DONE] 토큰으로 스트림 종료
            yield format_done_token()

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            # OpenResponses: response.failed 이벤트
            if stream_state.response:
                stream_state.response.status = ResponseStatus.FAILED
                stream_state.response.error = ErrorInfo(
                    type="server_error",
                    message=str(e)
                )
                failed_event = ResponseFailedEvent(response=stream_state.response)
                yield format_sse_event(failed_event)
            yield format_done_token()

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-OpenResponses-Version": OPEN_RESPONSES_VERSION,
        },
    )


# ============================================================================
# Analytics Endpoints
# ============================================================================

@router.get("/conversations/{conversation_id}/analytics", response_model=ConversationAnalytics)
async def get_conversation_analytics(
    conversation_id: str,
    period: str = "session",
    _conversation: dict = Depends(get_readable_conversation),
):
    """대화 분석 데이터 조회"""
    try:
        analytics = await ChatService.get_conversation_analytics(conversation_id, period)
        if not analytics:
            raise HTTPException(status_code=404, detail="Analytics not found")
        return ConversationAnalytics(**analytics)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/statistics", response_model=UserChatStatistics)
async def get_user_statistics(
    user_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """사용자 채팅 통계"""
    require_same_user_id(user_id, current_user)
    try:
        stats = await ChatService.get_user_statistics(user_id)
        return UserChatStatistics(**stats)
    except Exception as e:
        logger.error(f"Failed to get user statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Template Endpoints
# ============================================================================

@router.post("/templates", response_model=ConversationTemplate)
async def create_template(request: CreateTemplateRequest):
    """대화 템플릿 생성"""
    try:
        template = await ChatService.create_template(
            name=request.name,
            created_by=request.created_by,
            description=request.description,
            category=request.category,
            default_model=request.default_model,
            default_system_prompt=request.default_system_prompt,
            default_temperature=request.default_temperature,
            default_settings=request.default_settings,
            initial_messages=request.initial_messages,
            is_public=request.is_public,
            tags=request.tags,
            metadata=request.metadata
        )
        return ConversationTemplate(**template)
    except Exception as e:
        logger.error(f"Failed to create template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/templates/{template_id}", response_model=ConversationTemplate)
async def get_template(template_id: str):
    """템플릿 조회"""
    try:
        template = await ChatService.get_template(template_id)
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        return ConversationTemplate(**template)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get template: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates(
    category: Optional[str] = None,
    is_public: Optional[bool] = None,
    created_by: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """템플릿 목록 조회"""
    try:
        result = await ChatService.list_templates(
            category=category,
            is_public=is_public,
            created_by=created_by,
            limit=limit,
            offset=offset
        )

        return TemplateListResponse(
            templates=[ConversationTemplate(**t) for t in result["templates"]],
            total_count=result["total_count"]
        )
    except Exception as e:
        logger.error(f"Failed to list templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# WebSocket Endpoint
# ============================================================================

@router.websocket("/ws/{conversation_id}")
async def websocket_chat(websocket: WebSocket, conversation_id: str):
    """
    WebSocket 기반 실시간 채팅

    클라이언트 메시지 형식:
    {
        "type": "message",
        "content": "Hello!",
        "metadata": {}
    }

    서버 응답 형식:
    {
        "type": "start" | "content" | "complete" | "error",
        "content": "...",
        "message_id": "...",
        "usage": {...},
        "cost": {...}
    }
    """
    await websocket.accept()
    logger.info(f"WebSocket connected: conversation_id={conversation_id}")

    try:
        # 대화 존재 확인
        conversation = await ChatService.get_conversation(conversation_id)
        if not conversation:
            await websocket.send_json({
                "type": "error",
                "error": "Conversation not found"
            })
            await websocket.close()
            return

        # 연결 확인 메시지
        await websocket.send_json({
            "type": "connected",
            "conversation_id": conversation_id,
            "model": conversation.get("model_name"),
            "temperature": conversation.get("temperature", 0.7)
        })

        while True:
            # 클라이언트 메시지 수신
            data = await websocket.receive_json()

            message_type = data.get("type")

            if message_type == "ping":
                # Ping/Pong
                await websocket.send_json({"type": "pong"})
                continue

            elif message_type == "message":
                # 사용자 메시지 처리
                content = data.get("content", "")
                metadata = data.get("metadata", {})

                if not content:
                    await websocket.send_json({
                        "type": "error",
                        "error": "Empty message content"
                    })
                    continue

                try:
                    # 사용자 메시지 저장
                    user_message = await ChatService.add_message(
                        conversation_id=conversation_id,
                        role="user",
                        content=content,
                        metadata=metadata
                    )

                    # 확인 메시지
                    await websocket.send_json({
                        "type": "user_message_saved",
                        "message_id": user_message["message_id"],
                        "sequence_number": user_message["sequence_number"]
                    })

                    # 대화 히스토리 조회
                    history_messages = await ChatService.get_conversation_messages(
                        conversation_id=conversation_id,
                        limit=20
                    )

                    # AI 응답 스트리밍
                    assistant_message_id = str(uuid.uuid4())
                    full_content = ""
                    usage_info = None
                    cost_info = None

                    async for chunk in chat_llm_service.generate_response_stream(
                        conversation_id=conversation_id,
                        message_id=assistant_message_id,
                        conversation_messages=history_messages,
                        model_name=conversation.get("model_name"),
                        system_prompt=conversation.get("system_prompt"),
                        temperature=conversation.get("temperature", 0.7),
                        max_tokens=conversation.get("max_tokens")
                    ):
                        if chunk["type"] == "start":
                            await websocket.send_json({
                                "type": "assistant_start",
                                "message_id": assistant_message_id
                            })

                        elif chunk["type"] == "content":
                            full_content += chunk["content"]
                            await websocket.send_json({
                                "type": "assistant_content",
                                "content": chunk["content"]
                            })

                        elif chunk["type"] == "complete":
                            usage_info = chunk["usage"]
                            cost_info = chunk["cost"]

                            # 어시스턴트 메시지 저장
                            assistant_message = await ChatService.add_message(
                                conversation_id=conversation_id,
                                role="assistant",
                                content=full_content,
                                message_id=assistant_message_id,
                                model_name=conversation.get("model_name"),
                                total_tokens=usage_info["total_tokens"],
                                prompt_tokens=usage_info["prompt_tokens"],
                                completion_tokens=usage_info["completion_tokens"],
                                metadata={
                                    "cost_usd": float(cost_info["total_cost"]),
                                    "latency_ms": chunk["latency_ms"]
                                }
                            )

                            # 메시지 저장 후 비용 기록 (FK 제약 위반 방지)
                            provider = "anthropic" if "claude" in conversation.get("model_name", "").lower() else "openai"
                            await cost_calculator.record_cost_for_existing_message(
                                message_id=assistant_message_id,
                                conversation_id=conversation_id,
                                provider=provider,
                                model_name=conversation.get("model_name"),
                                prompt_tokens=usage_info["prompt_tokens"],
                                completion_tokens=usage_info["completion_tokens"],
                                total_tokens=usage_info["total_tokens"],
                                latency_ms=chunk["latency_ms"],
                                finish_reason="end_turn"
                            )

                            await websocket.send_json({
                                "type": "assistant_complete",
                                "message_id": assistant_message["message_id"],
                                "sequence_number": assistant_message["sequence_number"],
                                "usage": usage_info,
                                "cost_usd": float(cost_info["total_cost"]),
                                "latency_ms": chunk["latency_ms"]
                            })

                        elif chunk["type"] == "error":
                            await websocket.send_json({
                                "type": "assistant_error",
                                "error": chunk["error"]
                            })
                            break

                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "error": f"Failed to process message: {str(e)}"
                    })

            else:
                await websocket.send_json({
                    "type": "error",
                    "error": f"Unknown message type: {message_type}"
                })

    except WebSocketDisconnect as wde:
        logger.info(f"WebSocket disconnected: conversation_id={conversation_id} ({wde.code})")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e)
            })
        except Exception as e:
            logger.error(f"Error sending error message: {e}")
    finally:
        try:
            await websocket.close()
        except Exception as e:
            logger.error(f"Error closing websocket: {e}")

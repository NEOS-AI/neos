"""Chat API handlers - thin layer for FastAPI routes"""

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from typing import Optional, List
from datetime import datetime
import uuid

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
from neos.api.dependencies.auth import get_current_active_user
from neos.api.dependencies.resource_access import (
    get_owned_conversation,
    get_owned_message,
    get_readable_conversation,
    require_same_user_id,
)
from neos.api.services.chat_service import ChatService
from neos.api.handlers.workflow_stream_handlers import WorkflowStreamCallback
from neos.database.connection import db_manager
from neos.database.models import User
from neos.services.chat_llm_service import chat_llm_service
from neos.api.services.chat_stream_pipeline import (
    ChatStreamPipeline,
    resolve_authorized_parent_message,
)
from neos.config.model_config import is_user_selectable_model
from neos.utils.cost_calculator import cost_calculator
from neos.utils.logger import get_logger
from neos.workflow.graph import multi_agent_workflow
from neos.config.settings import settings as app_settings

# 스트리밍 관련 임포트(stream_adapter · open_responses · 아티팩트/인라인시각화 도구)는
# `stream_message_legacy`와 함께 제거했다. 그 구현은 `ChatStreamPipeline`에 있고,
# 이 핸들러는 파이프라인을 조립해 넘기기만 한다.

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

# 대화 생성/재생성이 받는 model_name은 사용자가 통제하는 값이다 — 턴 오버라이드와
# 같은 selectable 게이트를 통과해야 한다(neos.config.model_config.is_user_selectable_model).
# "선택 불가 모델"과 "존재하지 않는 모델"을 같은 메시지로 응답해, 어떤 내부 모델이
# 존재하는지 흘리지 않는다.
_MODEL_NOT_SELECTABLE_DETAIL = "Requested model is not available for selection"


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
    if request.model_name and not is_user_selectable_model(request.model_name):
        raise HTTPException(status_code=400, detail=_MODEL_NOT_SELECTABLE_DETAIL)
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
    """대화와 메시지 함께 조회 (주어진 conversation_id에 해당하는 대화 및 메시지 목록 반환)

    messages는 커서 없음/before_sequence 지정 시 가장 최근 limit개를 sequence_number
    오름차순으로 정렬해 반환한다.
    """
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
    cursor: Optional[str] = None,
    include_archived: bool = False,
    current_user: User = Depends(get_current_active_user),
):
    """사용자의 대화 목록 조회 (keyset 커서 페이지네이션)."""
    require_same_user_id(user_id, current_user)
    try:
        result = await ChatService.list_conversations(
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset,
            include_archived=include_archived,
            cursor=cursor,
        )

        return ConversationListResponse(
            conversations=[ConversationSummary(**conv) for conv in result["conversations"]],
            total_count=result["total_count"],
            has_more=result["has_more"],
            next_cursor=result["next_cursor"],
        )
    except ValidationError as e:
        logger.error(f"Failed to list conversations (response validation): {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid cursor: {e}")
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

async def _require_authorized_parent_message(
    parent_message_id: Optional[str],
    authorized_conversation: dict,
    current_user: User,
) -> Optional[dict]:
    parent_message = await resolve_authorized_parent_message(
        ChatService,
        parent_message_id,
        authorized_conversation,
        current_user,
    )
    if parent_message_id is not None and parent_message is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return parent_message

@router.post("/conversations/{conversation_id}/messages", response_model=CreateMessageResponse)
async def send_message(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: User = Depends(get_current_active_user),
    authorized_conversation: dict = Depends(get_owned_conversation),
):
    """메시지 전송 및 AI 응답 생성"""
    await _require_authorized_parent_message(
        request.parent_message_id,
        authorized_conversation,
        current_user,
    )
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
                # history_messages는 이미 방금 저장한 유저 턴으로 끝난다
                # (tail 조회이므로) — 여기서 다시 append하면 중복된다.
                conversation_messages=history_messages,
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
                finish_reason=llm_response["finish_reason"],
                cache_creation_tokens=llm_response["usage"].get(
                    "cache_creation_tokens", 0
                ),
                cache_read_tokens=llm_response["usage"].get(
                    "cache_read_tokens", 0
                ),
                cache_ttl=app_settings.config.llm.prompt_caching.ttl,
                additional_cost_usd=llm_response["cost"].get(
                    "additional_cost", 0
                ),
                metadata={
                    "anthropic": llm_response["usage"].get("anthropic", {})
                },
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
    after_sequence: Optional[int] = None,
    _conversation: dict = Depends(get_readable_conversation),
):
    """대화의 메시지 목록 조회

    커서 없음/before_sequence: 가장 최근(마지막) limit개를 sequence_number 오름차순으로 반환한다.
    after_sequence: 해당 시퀀스 이후를 앞에서부터 limit개 오름차순으로 반환한다(꼬리가 아니라 이후 따라잡기).
    """
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
async def get_message(
    message_id: str,
    authorized_message: dict = Depends(get_owned_message),
):
    """메시지 조회"""
    try:
        return MessageResponse(**authorized_message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/messages/{message_id}", response_model=MessageResponse)
async def edit_message(
    message_id: str,
    request: EditMessageRequest,
    current_user: User = Depends(get_current_active_user),
    _message: dict = Depends(get_owned_message),
):
    """메시지 편집"""
    try:
        message = await ChatService.edit_message(
            message_id=message_id,
            new_content=request.new_content,
            edited_by=current_user.user_id,
            edit_reason=request.edit_reason
        )
        return MessageResponse(**message)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to edit message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/messages/{message_id}/feedback", response_model=MessageResponse)
async def add_message_feedback(
    message_id: str,
    request: MessageFeedbackRequest,
    _message: dict = Depends(get_owned_message),
):
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
async def delete_message(
    message_id: str,
    _message: dict = Depends(get_owned_message),
):
    """메시지 삭제"""
    try:
        success = await ChatService.delete_message(message_id)
        return SuccessResponse(success=success, message="Message deleted")
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/messages/{message_id}/regenerate")
async def regenerate_message(
    message_id: str,
    request: RegenerateMessageRequest,
    original_message: dict = Depends(get_owned_message),
):
    """메시지 재생성 (alternative response)"""
    if request.model_name and not is_user_selectable_model(request.model_name):
        raise HTTPException(status_code=400, detail=_MODEL_NOT_SELECTABLE_DETAIL)
    try:
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
            finish_reason=llm_response["finish_reason"],
            cache_creation_tokens=llm_response["usage"].get(
                "cache_creation_tokens", 0
            ),
            cache_read_tokens=llm_response["usage"].get("cache_read_tokens", 0),
            cache_ttl=app_settings.config.llm.prompt_caching.ttl,
            additional_cost_usd=llm_response["cost"].get("additional_cost", 0),
            metadata={
                "anthropic": llm_response["usage"].get("anthropic", {})
            },
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
    current_user: User = Depends(get_current_active_user),
    authorized_conversation: dict = Depends(get_owned_conversation),
):
    """스트리밍 메시지 전송 (아티팩트 지원)"""
    await _require_authorized_parent_message(
        request.parent_message_id,
        authorized_conversation,
        current_user,
    )
    pipeline = _get_chat_stream_pipeline()

    return StreamingResponse(
        pipeline.run(
            conversation_id,
            request,
            current_user,
            authorized_conversation=authorized_conversation,
        ),
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
async def create_template(
    request: CreateTemplateRequest,
    current_user: User = Depends(get_current_active_user),
):
    """대화 템플릿 생성"""
    try:
        template = await ChatService.create_template(
            name=request.name,
            created_by=current_user.user_id,
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
async def get_template(
    template_id: str,
    current_user: User = Depends(get_current_active_user),
):
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
    offset: int = 0,
    current_user: User = Depends(get_current_active_user),
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
                                finish_reason="end_turn",
                                cache_creation_tokens=usage_info.get(
                                    "cache_creation_tokens", 0
                                ),
                                cache_read_tokens=usage_info.get(
                                    "cache_read_tokens", 0
                                ),
                                cache_ttl=app_settings.config.llm.prompt_caching.ttl,
                                additional_cost_usd=cost_info.get(
                                    "additional_cost", 0
                                ),
                                metadata={
                                    "anthropic": usage_info.get("anthropic", {})
                                },
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

"""Chat API handlers - thin layer for FastAPI routes"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from typing import Optional, AsyncGenerator, List
import json
import asyncio
import uuid

from neos.api.models.chat_models import (
    CreateConversationRequest,
    UpdateConversationRequest,
    SendMessageRequest,
    RegenerateMessageRequest,
    EditMessageRequest,
    MessageFeedbackRequest,
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
    ChatStreamChunk
)
from neos.api.services.chat_service import ChatService
from neos.services.chat_llm_service import chat_llm_service
from neos.utils.cost_calculator import cost_calculator
from neos.database.connection import db_manager
from neos.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ============================================================================
# Conversation Endpoints
# ============================================================================

@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(request: CreateConversationRequest):
    """새 대화 생성"""
    try:
        conversation = await ChatService.create_conversation(
            user_id=request.user_id,
            model_name=request.model_name,
            title=request.title,
            system_prompt=request.system_prompt,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            template_id=request.template_id,
            metadata=request.metadata
        )
        return ConversationResponse(**conversation)
    except Exception as e:
        logger.error(f"Failed to create conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: str):
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
    before_sequence: Optional[int] = None
):
    """대화와 메시지 함께 조회"""
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
async def update_conversation(conversation_id: str, request: UpdateConversationRequest):
    """대화 업데이트"""
    try:
        conversation = await ChatService.update_conversation(
            conversation_id=conversation_id,
            title=request.title,
            system_prompt=request.system_prompt,
            temperature=request.temperature,
            is_pinned=request.is_pinned,
            tags=request.tags,
            metadata=request.metadata
        )
        return ConversationResponse(**conversation)
    except Exception as e:
        logger.error(f"Failed to update conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conversations/{conversation_id}", response_model=SuccessResponse)
async def delete_conversation(conversation_id: str, permanent: bool = False):
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
async def archive_conversation(conversation_id: str):
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
    include_archived: bool = False
):
    """사용자의 대화 목록 조회"""
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


# ============================================================================
# Message Endpoints
# ============================================================================

@router.post("/conversations/{conversation_id}/messages", response_model=CreateMessageResponse)
async def send_message(
    conversation_id: str,
    request: SendMessageRequest,
    background_tasks: BackgroundTasks
):
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
            import uuid
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

@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(conversation_id: str, request: SendMessageRequest):
    """스트리밍 메시지 전송"""

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

            # 시작 이벤트
            yield f"data: {json.dumps(ChatStreamChunk(type='start', message_id=user_message['message_id'], conversation_id=conversation_id).dict())}\n\n"

            # 대화 정보 및 히스토리 가져오기
            conversation = await ChatService.get_conversation(conversation_id)
            history_messages = await ChatService.get_conversation_messages(
                conversation_id=conversation_id,
                limit=20
            )

            # 메시지 ID 생성
            import uuid
            assistant_message_id = str(uuid.uuid4())

            # 실제 LLM 스트리밍
            full_content = ""
            usage_info = None
            cost_info = None
            latency_ms = None

            async for chunk in chat_llm_service.generate_response_stream(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                conversation_messages=history_messages + [{"role": "user", "content": request.content}],
                model_name=conversation.get("model_name"),
                system_prompt=conversation.get("system_prompt"),
                temperature=conversation.get("temperature", 0.7),
                max_tokens=conversation.get("max_tokens")
            ):
                if chunk["type"] == "start":
                    # 스트리밍 시작
                    pass
                elif chunk["type"] == "content":
                    # 컨텐츠 스트리밍
                    full_content += chunk["content"]
                    stream_chunk = ChatStreamChunk(
                        type="content",
                        content=chunk["content"],
                        conversation_id=conversation_id
                    )
                    yield f"data: {json.dumps(stream_chunk.dict())}\n\n"
                elif chunk["type"] == "complete":
                    # 완료
                    usage_info = chunk["usage"]
                    cost_info = chunk["cost"]
                    latency_ms = chunk["latency_ms"]
                elif chunk["type"] == "error":
                    # 에러
                    error_chunk = ChatStreamChunk(
                        type="error",
                        error=chunk["error"],
                        conversation_id=conversation_id
                    )
                    yield f"data: {json.dumps(error_chunk.dict())}\n\n"
                    return

            # 어시스턴트 메시지 저장
            assistant_message = await ChatService.add_message(
                conversation_id=conversation_id,
                role="assistant",
                content=full_content,
                message_id=assistant_message_id,
                model_name=conversation.get("model_name"),
                total_tokens=usage_info["total_tokens"] if usage_info else 0,
                prompt_tokens=usage_info["prompt_tokens"] if usage_info else 0,
                completion_tokens=usage_info["completion_tokens"] if usage_info else 0,
                metadata={
                    "cost_usd": float(cost_info["total_cost"]) if cost_info else 0.0,
                    "latency_ms": latency_ms
                }
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

            # 완료 이벤트
            complete_chunk = ChatStreamChunk(
                type="complete",
                message_id=assistant_message["message_id"],
                conversation_id=conversation_id,
                metadata={
                    "total_tokens": usage_info["total_tokens"] if usage_info else 0,
                    "cost_usd": float(cost_info["total_cost"]) if cost_info else 0.0
                }
            )
            yield f"data: {json.dumps(complete_chunk.dict())}\n\n"

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            error_chunk = ChatStreamChunk(
                type="error",
                error=str(e),
                conversation_id=conversation_id
            )
            yield f"data: {json.dumps(error_chunk.dict())}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ============================================================================
# Analytics Endpoints
# ============================================================================

@router.get("/conversations/{conversation_id}/analytics", response_model=ConversationAnalytics)
async def get_conversation_analytics(conversation_id: str, period: str = "session"):
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
async def get_user_statistics(user_id: str):
    """사용자 채팅 통계"""
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

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: conversation_id={conversation_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e)
            })
        except:
            pass
    finally:
        try:
            await websocket.close()
        except:
            pass

"""
Similarity Chat API handlers - 유사도 검색 기반 채팅 API
일반 채팅 API와 분리된 엔드포인트 제공
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional
import json

from neos.api.models.chat_models import (
    SendSimilarityMessageRequest,
    CreateSimilarityMessageResponse,
    MessageResponse,
    SimilarityMessageMetadata,
    ChatStreamChunk
)
from neos.api.services.chat_service import ChatService
from neos.api.services.similarity_chat_processor import (
    similarity_chat_processor,
    cross_conversation_similarity_processor,
    high_confidence_similarity_processor,
    SimilarityChatProcessor
)
from neos.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ============================================================================
# Similarity-based Chat Endpoints
# ============================================================================

@router.post("/conversations/{conversation_id}/messages/similarity",
             response_model=CreateSimilarityMessageResponse)
async def send_similarity_message(
    conversation_id: str,
    request: SendSimilarityMessageRequest
):
    """
    유사도 검색 기반 메시지 전송 (Non-streaming)

    이전 대화에서 유사한 메시지를 검색하여 컨텍스트로 활용
    """
    try:
        # 대화 존재 확인
        conversation = await ChatService.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # 프로세서 생성 (요청별 설정)
        processor = SimilarityChatProcessor(
            top_k=request.top_k,
            similarity_threshold=request.similarity_threshold,
            include_cross_conversation=request.include_cross_conversation,
            enable_auto_embedding=request.enable_auto_embedding
        )

        # 메시지 처리
        result = await processor.process_message(
            conversation_id=conversation_id,
            user_content=request.content,
            user_id=conversation.get("user_id"),
            parent_message_id=request.parent_message_id,
            attachments=request.attachments,
            metadata=request.metadata
        )

        # 응답 생성
        metadata = result["processing_metadata"]

        return CreateSimilarityMessageResponse(
            success=True,
            user_message=MessageResponse(**result["user_message"]),
            assistant_message=MessageResponse(**result["assistant_message"]),
            conversation_id=conversation_id,
            errors=[],
            context_enhanced=metadata.get("context_enhanced", False),
            relevant_message_count=metadata.get("relevant_message_count", 0),
            similarity_scores=[
                SimilarityMessageMetadata(**score)
                for score in metadata.get("similarity_scores", [])
            ],
            search_config=metadata.get("search_config", {})
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to send similarity message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/messages/similarity/stream")
async def send_similarity_message_stream(
    conversation_id: str,
    request: SendSimilarityMessageRequest
):
    """
    유사도 검색 기반 메시지 전송 (Streaming)

    Server-Sent Events 방식으로 스트리밍 응답 제공
    """
    try:
        # 대화 존재 확인
        conversation = await ChatService.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # 프로세서 생성
        processor = SimilarityChatProcessor(
            top_k=request.top_k,
            similarity_threshold=request.similarity_threshold,
            include_cross_conversation=request.include_cross_conversation,
            enable_auto_embedding=request.enable_auto_embedding
        )

        async def event_generator():
            """SSE 이벤트 생성기"""
            try:
                async for chunk in processor.process_message_stream(
                    conversation_id=conversation_id,
                    user_content=request.content,
                    user_id=conversation.get("user_id"),
                    parent_message_id=request.parent_message_id,
                    attachments=request.attachments,
                    metadata=request.metadata
                ):
                    # SSE 형식으로 변환
                    event_data = json.dumps(chunk, ensure_ascii=False, default=str)
                    yield f"data: {event_data}\n\n"

            except Exception as e:
                logger.error(f"Streaming error: {e}")
                error_chunk = {
                    "type": "error",
                    "error": str(e),
                    "content": str(e)
                }
                yield f"data: {json.dumps(error_chunk)}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start similarity streaming: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Preset Similarity Chat Endpoints (편의 엔드포인트)
# ============================================================================

@router.post("/conversations/{conversation_id}/messages/similarity/cross-conversation",
             response_model=CreateSimilarityMessageResponse)
async def send_cross_conversation_similarity_message(
    conversation_id: str,
    request: SendSimilarityMessageRequest
):
    """
    크로스 대화 유사도 검색 기반 메시지 전송

    현재 대화뿐만 아니라 사용자의 다른 모든 대화에서도 유사 메시지 검색
    """
    try:
        conversation = await ChatService.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # 크로스 대화 프로세서 사용
        result = await cross_conversation_similarity_processor.process_message(
            conversation_id=conversation_id,
            user_content=request.content,
            user_id=conversation.get("user_id"),
            parent_message_id=request.parent_message_id,
            attachments=request.attachments,
            metadata=request.metadata,
            top_k=request.top_k
        )

        metadata = result["processing_metadata"]

        return CreateSimilarityMessageResponse(
            success=True,
            user_message=MessageResponse(**result["user_message"]),
            assistant_message=MessageResponse(**result["assistant_message"]),
            conversation_id=conversation_id,
            errors=[],
            context_enhanced=metadata.get("context_enhanced", False),
            relevant_message_count=metadata.get("relevant_message_count", 0),
            similarity_scores=[
                SimilarityMessageMetadata(**score)
                for score in metadata.get("similarity_scores", [])
            ],
            search_config=metadata.get("search_config", {})
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to send cross-conversation similarity message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/messages/similarity/high-confidence",
             response_model=CreateSimilarityMessageResponse)
async def send_high_confidence_similarity_message(
    conversation_id: str,
    request: SendSimilarityMessageRequest
):
    """
    고신뢰도 유사도 검색 기반 메시지 전송

    유사도 임계값 0.85 이상의 매우 유사한 메시지만 컨텍스트로 사용
    """
    try:
        conversation = await ChatService.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # 고신뢰도 프로세서 사용
        result = await high_confidence_similarity_processor.process_message(
            conversation_id=conversation_id,
            user_content=request.content,
            user_id=conversation.get("user_id"),
            parent_message_id=request.parent_message_id,
            attachments=request.attachments,
            metadata=request.metadata,
            top_k=request.top_k
        )

        metadata = result["processing_metadata"]

        return CreateSimilarityMessageResponse(
            success=True,
            user_message=MessageResponse(**result["user_message"]),
            assistant_message=MessageResponse(**result["assistant_message"]),
            conversation_id=conversation_id,
            errors=[],
            context_enhanced=metadata.get("context_enhanced", False),
            relevant_message_count=metadata.get("relevant_message_count", 0),
            similarity_scores=[
                SimilarityMessageMetadata(**score)
                for score in metadata.get("similarity_scores", [])
            ],
            search_config=metadata.get("search_config", {})
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to send high-confidence similarity message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Configuration Endpoints
# ============================================================================

@router.get("/conversations/{conversation_id}/similarity/config")
async def get_similarity_config(conversation_id: str):
    """
    유사도 검색 설정 조회

    현재 대화의 임베딩 통계 및 권장 설정 반환
    """
    try:
        from neos.services.message_embedding_service import message_embedding_service

        # 대화 존재 확인
        conversation = await ChatService.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # 임베딩 통계 조회
        embedding_count = await message_embedding_service.get_conversation_embeddings_count(
            conversation_id
        )

        # 사용자 전체 임베딩 통계
        user_stats = None
        if conversation.get("user_id"):
            user_stats = await message_embedding_service.get_user_embeddings_stats(
                conversation.get("user_id")
            )

        # 권장 설정 계산
        if embedding_count < 10:
            recommended_config = {
                "top_k": 3,
                "similarity_threshold": 0.7,
                "include_cross_conversation": False,
                "note": "대화 초기 단계: 기본 설정 사용"
            }
        elif embedding_count < 50:
            recommended_config = {
                "top_k": 5,
                "similarity_threshold": 0.75,
                "include_cross_conversation": False,
                "note": "중간 단계: 검색 범위 확대"
            }
        else:
            recommended_config = {
                "top_k": 5,
                "similarity_threshold": 0.8,
                "include_cross_conversation": True,
                "note": "성숙 단계: 크로스 대화 검색 추천"
            }

        return {
            "conversation_id": conversation_id,
            "embedding_count": embedding_count,
            "user_stats": user_stats,
            "recommended_config": recommended_config,
            "available_presets": {
                "standard": {
                    "endpoint": "/messages/similarity",
                    "top_k": 3,
                    "threshold": 0.7,
                    "cross_conversation": False
                },
                "cross_conversation": {
                    "endpoint": "/messages/similarity/cross-conversation",
                    "top_k": 5,
                    "threshold": 0.75,
                    "cross_conversation": True
                },
                "high_confidence": {
                    "endpoint": "/messages/similarity/high-confidence",
                    "top_k": 3,
                    "threshold": 0.85,
                    "cross_conversation": False
                }
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get similarity config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

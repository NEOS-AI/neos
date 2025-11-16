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

        # 에러 메시지 수집
        errors = []
        if metadata.get("similarity_search_failed"):
            errors.append(metadata.get("error_message", "유사도 검색에 실패했습니다."))

        return CreateSimilarityMessageResponse(
            success=True,
            user_message=MessageResponse(**result["user_message"]),
            assistant_message=MessageResponse(**result["assistant_message"]),
            conversation_id=conversation_id,
            errors=errors,
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


@router.get("/conversations/{conversation_id}/similarity/analytics")
async def get_similarity_analytics(conversation_id: str):
    """
    유사도 검색 사용 통계 및 분석

    메시지의 similarity 메타데이터를 분석하여 통계 반환
    """
    try:
        # 대화 존재 확인
        conversation = await ChatService.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # 대화의 모든 메시지 조회
        from neos.api.services.chat_service import ChatService
        messages = await ChatService.get_messages(conversation_id, limit=1000)

        # Similarity search를 사용한 메시지 필터링
        similarity_messages = [
            msg for msg in messages
            if msg.get("metadata", {}).get("context_enhanced")
        ]

        # 통계 계산
        total_similarity_searches = len(similarity_messages)

        if total_similarity_searches == 0:
            return {
                "conversation_id": conversation_id,
                "total_similarity_searches": 0,
                "average_relevant_messages": 0,
                "average_similarity_score": 0,
                "most_common_settings": None,
                "usage_over_time": []
            }

        # 평균 관련 메시지 수
        avg_relevant_messages = sum(
            msg.get("metadata", {}).get("relevant_message_count", 0)
            for msg in similarity_messages
        ) / total_similarity_searches

        # 평균 유사도 점수 계산
        all_scores = []
        for msg in similarity_messages:
            scores = msg.get("metadata", {}).get("similarity_scores", [])
            for score_obj in scores:
                all_scores.append(score_obj.get("similarity_score", 0))

        avg_similarity_score = sum(all_scores) / len(all_scores) if all_scores else 0

        # 가장 많이 사용된 설정
        settings_usage = {}
        for msg in similarity_messages:
            config = msg.get("metadata", {}).get("search_config", {})
            config_key = f"k{config.get('top_k', 3)}_t{config.get('threshold', 0.7)}"
            settings_usage[config_key] = settings_usage.get(config_key, 0) + 1

        most_common_setting = max(settings_usage.items(), key=lambda x: x[1]) if settings_usage else None

        return {
            "conversation_id": conversation_id,
            "total_similarity_searches": total_similarity_searches,
            "average_relevant_messages": round(avg_relevant_messages, 2),
            "average_similarity_score": round(avg_similarity_score, 3),
            "most_common_settings": most_common_setting[0] if most_common_setting else None,
            "cross_conversation_usage": sum(
                1 for msg in similarity_messages
                if msg.get("metadata", {}).get("search_config", {}).get("include_cross_conversation")
            ),
            "total_messages_analyzed": len(messages)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get similarity analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

"""
RAG Chat API Handlers

유사도 검색 기반 RAG 채팅 API
일반 채팅 API와 분리되어 있지만 필요한 코드는 공유
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
import json
import uuid

from neos.api.models.rag_chat_models import (
    RAGSendMessageRequest,
    SimilaritySearchRequest,
    CreateEmbeddingRequest,
    SimilaritySearchResponse,
    SimilarMessageResult,
    RAGMessageResponse,
    RAGContextInfo,
    EmbeddingStatsResponse,
    CreateEmbeddingResponse
)
from neos.api.services.chat_service import ChatService
from neos.services.rag_chat_llm_service import rag_chat_llm_service
from neos.services.similarity_search_service import similarity_search_service
from neos.services.message_embedding_service import message_embedding_service
from neos.utils.cost_calculator import cost_calculator
from neos.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ============================================================================
# RAG Chat Endpoints
# ============================================================================

@router.post("/conversations/{conversation_id}/messages/rag", response_model=RAGMessageResponse)
async def send_rag_message(
    conversation_id: str,
    request: RAGSendMessageRequest,
    background_tasks: BackgroundTasks
):
    """
    RAG 기반 메시지 전송

    유사한 이전 메시지를 검색하여 컨텍스트에 추가
    """
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

        # 백그라운드에서 사용자 메시지 임베딩 생성
        background_tasks.add_task(
            message_embedding_service.create_message_embedding,
            message_id=user_message["message_id"],
            conversation_id=conversation_id,
            content=request.content,
            role=request.role.value,
            user_id=None,  # TODO: 실제 사용자 ID
            sequence_number=user_message["sequence_number"]
        )

        # AI 응답 생성
        assistant_message_id = str(uuid.uuid4())

        if request.role.value == "user" and request.enable_rag:
            # 대화 정보 및 히스토리 가져오기
            conversation = await ChatService.get_conversation(conversation_id)
            history_messages = await ChatService.get_conversation_messages(
                conversation_id=conversation_id,
                limit=20
            )

            # RAG 기반 응답 생성
            llm_response = await rag_chat_llm_service.generate_response_with_rag(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                # history_messages는 이미 방금 저장한 유저 턴으로 끝난다
                # (tail 조회이므로) — 여기서 다시 append하면 중복된다.
                conversation_messages=history_messages,
                user_query=request.content,
                user_id=conversation.get("user_id"),
                model_name=conversation.get("model_name"),
                system_prompt=conversation.get("system_prompt"),
                temperature=conversation.get("temperature", 0.7),
                max_tokens=conversation.get("max_tokens"),
                top_k=request.rag_top_k,
                include_cross_conversation=request.include_cross_conversation
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
                    "rag_enabled": True,
                    "rag_context": llm_response.get("rag_context", {})
                }
            )

            # 백그라운드에서 어시스턴트 메시지 임베딩 생성
            background_tasks.add_task(
                message_embedding_service.create_message_embedding,
                message_id=assistant_message_id,
                conversation_id=conversation_id,
                content=llm_response["content"],
                role="assistant",
                sequence_number=assistant_message["sequence_number"]
            )

            return RAGMessageResponse(
                success=True,
                user_message_id=user_message["message_id"],
                assistant_message_id=assistant_message["message_id"],
                assistant_content=llm_response["content"],
                rag_enabled=True,
                rag_context=RAGContextInfo(**llm_response["rag_context"]),
                usage=llm_response["usage"],
                cost_usd=float(llm_response["cost"]["total_cost"]),
                latency_ms=llm_response["latency_ms"]
            )
        else:
            # RAG 비활성화 - 일반 응답
            raise HTTPException(
                status_code=400,
                detail="RAG is disabled. Use regular chat endpoint instead."
            )

    except Exception as e:
        logger.error(f"Failed to send RAG message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/messages/rag/stream")
async def stream_rag_message(
    conversation_id: str,
    request: RAGSendMessageRequest
):
    """RAG 기반 스트리밍 메시지"""

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

            # 사용자 메시지 임베딩 생성 (비동기)
            await message_embedding_service.create_message_embedding(
                message_id=user_message["message_id"],
                conversation_id=conversation_id,
                content=request.content,
                role=request.role.value,
                sequence_number=user_message["sequence_number"]
            )

            # 시작 이벤트
            yield f"data: {json.dumps({'type': 'start', 'message_id': user_message['message_id']})}\n\n"

            # 대화 정보 및 히스토리 가져오기
            conversation = await ChatService.get_conversation(conversation_id)
            history_messages = await ChatService.get_conversation_messages(
                conversation_id=conversation_id,
                limit=20
            )

            # 메시지 ID 생성
            assistant_message_id = str(uuid.uuid4())

            # RAG 스트리밍
            full_content = ""
            usage_info = None
            cost_info = None
            rag_context_info = None

            async for chunk in rag_chat_llm_service.generate_response_stream_with_rag(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                conversation_messages=history_messages,
                user_query=request.content,
                user_id=conversation.get("user_id"),
                model_name=conversation.get("model_name"),
                system_prompt=conversation.get("system_prompt"),
                temperature=conversation.get("temperature", 0.7),
                max_tokens=conversation.get("max_tokens"),
                top_k=request.rag_top_k,
                include_cross_conversation=request.include_cross_conversation
            ):
                if chunk["type"] == "content":
                    full_content += chunk["content"]
                    yield f"data: {json.dumps({'type': 'content', 'content': chunk['content']})}\n\n"

                elif chunk["type"] == "complete":
                    usage_info = chunk["usage"]
                    cost_info = chunk["cost"]
                    rag_context_info = chunk.get("rag_context")

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
                    "rag_enabled": True,
                    "rag_context": rag_context_info
                }
            )

            # 어시스턴트 메시지 임베딩 생성
            await message_embedding_service.create_message_embedding(
                message_id=assistant_message_id,
                conversation_id=conversation_id,
                content=full_content,
                role="assistant",
                sequence_number=assistant_message["sequence_number"]
            )

            # 완료 이벤트
            complete_data = {
                "type": "complete",
                "message_id": assistant_message["message_id"],
                "usage": usage_info,
                "cost_usd": float(cost_info["total_cost"]) if cost_info else 0.0,
                "rag_context": rag_context_info
            }
            yield f"data: {json.dumps(complete_data)}\n\n"

        except Exception as e:
            logger.error(f"RAG streaming error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

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
# Similarity Search Endpoints
# ============================================================================

@router.post("/conversations/{conversation_id}/search", response_model=SimilaritySearchResponse)
async def search_similar_messages(
    conversation_id: str,
    request: SimilaritySearchRequest
):
    """대화 내 유사 메시지 검색"""
    try:
        results = await similarity_search_service.search(
            query=request.query,
            strategy=request.strategy,
            conversation_id=conversation_id,
            limit=request.limit,
            similarity_threshold=request.similarity_threshold
        )

        similar_results = [SimilarMessageResult(**r) for r in results]

        return SimilaritySearchResponse(
            success=True,
            query=request.query,
            strategy=request.strategy,
            results=similar_results,
            total_results=len(similar_results)
        )

    except Exception as e:
        logger.error(f"Similarity search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/{user_id}/search", response_model=SimilaritySearchResponse)
async def search_across_conversations(
    user_id: str,
    request: SimilaritySearchRequest
):
    """사용자의 모든 대화에서 유사 메시지 검색"""
    try:
        results = await similarity_search_service.search(
            query=request.query,
            strategy="cross_conversation",
            user_id=user_id,
            limit=request.limit,
            similarity_threshold=request.similarity_threshold
        )

        similar_results = [SimilarMessageResult(**r) for r in results]

        return SimilaritySearchResponse(
            success=True,
            query=request.query,
            strategy="cross_conversation",
            results=similar_results,
            total_results=len(similar_results)
        )

    except Exception as e:
        logger.error(f"Cross-conversation search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Embedding Management Endpoints
# ============================================================================

@router.post("/messages/{message_id}/embedding", response_model=CreateEmbeddingResponse)
async def create_message_embedding(
    message_id: str,
    request: CreateEmbeddingRequest
):
    """메시지 임베딩 생성"""
    try:
        # 메시지 조회
        message = await ChatService.get_message(message_id)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")

        # 임베딩 생성
        success = await message_embedding_service.create_message_embedding(
            message_id=message_id,
            conversation_id=message["conversation_id"],
            content=message["content"],
            role=message["role"],
            sequence_number=message["sequence_number"]
        )

        if success:
            return CreateEmbeddingResponse(
                success=True,
                message_id=message_id,
                message="Embedding created successfully"
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to create embedding")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create embedding: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/embeddings/stats", response_model=EmbeddingStatsResponse)
async def get_user_embedding_stats(user_id: str):
    """사용자 임베딩 통계"""
    try:
        stats = await message_embedding_service.get_user_embeddings_stats(user_id)
        return EmbeddingStatsResponse(**stats)
    except Exception as e:
        logger.error(f"Failed to get embedding stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/messages/{message_id}/embedding")
async def delete_message_embedding(message_id: str):
    """메시지 임베딩 삭제"""
    try:
        success = await message_embedding_service.delete_message_embedding(message_id)
        return {"success": success, "message": "Embedding deleted"}
    except Exception as e:
        logger.error(f"Failed to delete embedding: {e}")
        raise HTTPException(status_code=500, detail=str(e))

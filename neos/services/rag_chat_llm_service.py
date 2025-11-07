"""
RAG-Enhanced Chat LLM Service

유사도 검색 기반 RAG(Retrieval-Augmented Generation) 채팅 서비스
Template Method Pattern을 사용하여 기존 ChatLLMService 확장
"""

from typing import Dict, Any, List, Optional, AsyncGenerator

from neos.services.chat_llm_service import ChatLLMService
from neos.services.similarity_search_service import similarity_search_service
from neos.services.message_embedding_service import message_embedding_service
from neos.utils.logger import get_logger

logger = get_logger(__name__)


class RAGChatLLMService(ChatLLMService):
    """
    RAG 기반 채팅 LLM 서비스

    Template Method Pattern을 사용하여 기존 ChatLLMService를 확장
    유사한 메시지를 검색하여 컨텍스트에 추가
    """

    def __init__(self):
        super().__init__()
        self.rag_enabled = True
        self.default_top_k = 3
        self.similarity_threshold = 0.75

    def _build_rag_system_prompt(
        self,
        original_system_prompt: Optional[str],
        context_text: str
    ) -> str:
        """RAG 컨텍스트를 포함한 시스템 프롬프트 생성"""
        rag_instruction = """
다음은 이전 대화에서 현재 질문과 관련있는 내용들입니다.
이 정보를 참고하여 답변하되, 관련이 없다면 무시하고 일반적으로 답변하세요.

=== 관련 대화 내용 ===
{context}
=== 관련 대화 끝 ===

위 내용을 참고하여 답변해주세요.
"""
        rag_section = rag_instruction.format(context=context_text)

        if original_system_prompt:
            return f"{original_system_prompt}\n\n{rag_section}"
        else:
            return rag_section

    async def generate_response_with_rag(
        self,
        conversation_id: str,
        message_id: str,
        conversation_messages: List[Dict[str, Any]],
        user_query: str,
        user_id: Optional[str] = None,
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        top_k: int = 3,
        include_cross_conversation: bool = False,
    ) -> Dict[str, Any]:
        """
        RAG 기반 응답 생성 (비스트리밍)

        Args:
            conversation_id: 대화 ID
            message_id: 메시지 ID
            conversation_messages: 대화 히스토리
            user_query: 사용자 쿼리
            user_id: 사용자 ID
            model_name: 모델명
            system_prompt: 원래 시스템 프롬프트
            temperature: 온도
            max_tokens: 최대 토큰
            top_k: RAG에 사용할 유사 메시지 수
            include_cross_conversation: 다른 대화에서도 검색할지 여부

        Returns:
            LLM 응답 + RAG 메타데이터
        """
        # RAG 컨텍스트 생성
        rag_context = await similarity_search_service.get_rag_context(
            conversation_id=conversation_id,
            query=user_query,
            top_k=top_k,
            include_cross_conversation=include_cross_conversation,
            user_id=user_id
        )

        # RAG 컨텍스트를 시스템 프롬프트에 추가
        enhanced_system_prompt = self._build_rag_system_prompt(
            original_system_prompt=system_prompt,
            context_text=rag_context["context_text"]
        )

        # 기존 generate_response 호출
        llm_response = await self.generate_response(
            conversation_id=conversation_id,
            message_id=message_id,
            conversation_messages=conversation_messages,
            model_name=model_name,
            system_prompt=enhanced_system_prompt,
            temperature=temperature,
            max_tokens=max_tokens
        )

        # RAG 메타데이터 추가
        llm_response["rag_context"] = {
            "relevant_messages_count": rag_context["total_relevant"],
            "relevant_messages": [
                {
                    "message_id": msg["message_id"],
                    "similarity_score": msg.get("similarity_score", 0),
                    "content_preview": msg["content"][:100] + "..."
                }
                for msg in rag_context["relevant_messages"]
            ]
        }

        return llm_response

    async def generate_response_stream_with_rag(
        self,
        conversation_id: str,
        message_id: str,
        conversation_messages: List[Dict[str, Any]],
        user_query: str,
        user_id: Optional[str] = None,
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        top_k: int = 3,
        include_cross_conversation: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        RAG 기반 스트리밍 응답 생성

        Yields:
            스트리밍 청크 + RAG 메타데이터 (complete 이벤트에 포함)
        """
        # RAG 컨텍스트 생성
        rag_context = await similarity_search_service.get_rag_context(
            conversation_id=conversation_id,
            query=user_query,
            top_k=top_k,
            include_cross_conversation=include_cross_conversation,
            user_id=user_id
        )

        # RAG 컨텍스트를 시스템 프롬프트에 추가
        enhanced_system_prompt = self._build_rag_system_prompt(
            original_system_prompt=system_prompt,
            context_text=rag_context["context_text"]
        )

        # 기존 generate_response_stream 호출
        async for chunk in self.generate_response_stream(
            conversation_id=conversation_id,
            message_id=message_id,
            conversation_messages=conversation_messages,
            model_name=model_name,
            system_prompt=enhanced_system_prompt,
            temperature=temperature,
            max_tokens=max_tokens
        ):
            # complete 이벤트에 RAG 메타데이터 추가
            if chunk["type"] == "complete":
                chunk["rag_context"] = {
                    "relevant_messages_count": rag_context["total_relevant"],
                    "relevant_messages": [
                        {
                            "message_id": msg["message_id"],
                            "similarity_score": msg.get("similarity_score", 0),
                            "content_preview": msg["content"][:100] + "..."
                        }
                        for msg in rag_context["relevant_messages"]
                    ]
                }

            yield chunk


# 전역 인스턴스
rag_chat_llm_service = RAGChatLLMService()

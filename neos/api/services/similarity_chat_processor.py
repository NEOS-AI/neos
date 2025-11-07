"""
Similarity Chat Processor - 유사도 검색 기반 채팅 처리
템플릿 메서드 패턴의 구체 클래스: 메시지 유사도 검색을 통한 RAG 구현
"""

from typing import Dict, List, Any, Optional

from neos.api.services.chat_message_processor import BaseChatMessageProcessor
from neos.services.similarity_search_service import similarity_search_service
from neos.services.message_embedding_service import message_embedding_service
from neos.utils.logger import get_logger

logger = get_logger(__name__)


class SimilarityChatProcessor(BaseChatMessageProcessor):
    """
    유사도 검색 기반 채팅 프로세서
    - 사용자 쿼리에 대한 유사 메시지 검색
    - 검색 결과를 컨텍스트로 시스템 프롬프트에 주입
    - 임베딩 자동 생성 (백그라운드)
    """

    def __init__(
        self,
        top_k: int = 3,
        similarity_threshold: float = 0.7,
        include_cross_conversation: bool = False,
        enable_auto_embedding: bool = True
    ):
        """
        Args:
            top_k: 검색할 유사 메시지 수
            similarity_threshold: 유사도 임계값 (0.0 ~ 1.0)
            include_cross_conversation: 다른 대화에서도 검색할지 여부
            enable_auto_embedding: 메시지 저장 시 자동 임베딩 생성 여부
        """
        super().__init__()
        self.logger = logger
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.include_cross_conversation = include_cross_conversation
        self.enable_auto_embedding = enable_auto_embedding

    async def prepare_context(
        self,
        conversation_id: str,
        user_content: str,
        history_messages: List[Dict],
        conversation: Dict,
        **kwargs
    ) -> Dict[str, Any]:
        """
        유사도 검색을 통한 컨텍스트 준비
        """
        try:
            # 파라미터 오버라이드
            top_k = kwargs.get("top_k", self.top_k)
            include_cross = kwargs.get("include_cross_conversation", self.include_cross_conversation)
            user_id = kwargs.get("user_id") or conversation.get("user_id")

            # RAG 컨텍스트 생성
            rag_context = await similarity_search_service.get_rag_context(
                conversation_id=conversation_id,
                query=user_content,
                top_k=top_k,
                include_cross_conversation=include_cross,
                user_id=user_id
            )

            # 유사도가 임계값 이상인 메시지만 필터링
            relevant_messages = [
                msg for msg in rag_context["relevant_messages"]
                if msg.get("similarity_score", 0) >= self.similarity_threshold
            ]

            # 강화된 시스템 프롬프트 생성
            enhanced_system_prompt = self._build_enhanced_system_prompt(
                base_prompt=conversation.get("system_prompt", ""),
                relevant_messages=relevant_messages
            )

            self.logger.info(
                f"Similarity search completed for conversation {conversation_id}: "
                f"found {len(relevant_messages)} relevant messages (threshold={self.similarity_threshold})"
            )

            return {
                "enhanced_system_prompt": enhanced_system_prompt,
                "metadata": {
                    "chat_type": "similarity",
                    "context_enhanced": len(relevant_messages) > 0,
                    "relevant_message_count": len(relevant_messages),
                    "similarity_scores": [
                        {
                            "message_id": msg["message_id"],
                            "score": msg.get("similarity_score", 0),
                            "search_type": msg.get("search_type", "conversation")
                        }
                        for msg in relevant_messages
                    ],
                    "search_config": {
                        "top_k": top_k,
                        "threshold": self.similarity_threshold,
                        "include_cross_conversation": include_cross
                    }
                },
                "context_messages": relevant_messages
            }

        except Exception as e:
            self.logger.error(f"Failed to prepare similarity context: {e}")
            # 실패 시 일반 채팅으로 폴백
            return {
                "enhanced_system_prompt": conversation.get("system_prompt"),
                "metadata": {
                    "chat_type": "similarity",
                    "context_enhanced": False,
                    "error": str(e)
                },
                "context_messages": []
            }

    def _build_enhanced_system_prompt(
        self,
        base_prompt: str,
        relevant_messages: List[Dict]
    ) -> str:
        """
        유사 메시지를 포함한 강화된 시스템 프롬프트 생성
        """
        if not relevant_messages:
            return base_prompt

        # 컨텍스트 섹션 생성
        context_lines = [
            "\n\n=== 관련 대화 컨텍스트 ===",
            "아래는 현재 질문과 관련된 이전 대화 내용입니다. 이를 참고하여 답변해주세요.\n"
        ]

        for i, msg in enumerate(relevant_messages, 1):
            similarity = msg.get("similarity_score", 0)
            content = msg["content"][:500]  # 최대 500자까지만
            role = msg["role"]

            # 메시지 출처 표시
            source = ""
            if msg.get("search_type") == "cross_conversation":
                conv_title = msg.get("conversation_title", "다른 대화")
                source = f" (출처: {conv_title})"

            context_lines.append(
                f"[관련 메시지 {i}] (유사도: {similarity:.2f}){source}\n"
                f"[{role.upper()}]: {content}\n"
            )

        context_lines.append("=== 컨텍스트 끝 ===\n")

        # 기본 프롬프트에 컨텍스트 추가
        enhanced_prompt = base_prompt or "You are a helpful assistant."
        enhanced_prompt += "\n".join(context_lines)

        return enhanced_prompt

    async def post_process(
        self,
        user_message: Dict,
        assistant_message: Dict,
        context_data: Dict,
        **kwargs
    ) -> None:
        """
        후처리: 메시지 임베딩 자동 생성
        """
        if not self.enable_auto_embedding:
            return

        try:
            # 사용자 메시지 임베딩 생성
            await self._create_message_embedding(user_message)

            # 어시스턴트 메시지 임베딩 생성
            await self._create_message_embedding(assistant_message)

            self.logger.debug(
                f"Embeddings created for messages: {user_message['message_id']}, {assistant_message['message_id']}"
            )

        except Exception as e:
            # 임베딩 생성 실패는 전체 프로세스를 중단시키지 않음
            self.logger.warning(f"Failed to create embeddings in post-process: {e}")

    async def _create_message_embedding(self, message: Dict) -> None:
        """메시지 임베딩 생성"""
        try:
            await message_embedding_service.create_message_embedding(
                message_id=message["message_id"],
                conversation_id=message["conversation_id"],
                content=message["content"],
                role=message["role"],
                user_id=None,  # 메시지 테이블에 user_id가 없으므로 None
                sequence_number=message.get("sequence_number"),
                metadata=message.get("metadata", {})
            )
        except Exception as e:
            self.logger.warning(f"Failed to create embedding for message {message['message_id']}: {e}")


# ============================================================================
# 프리셋 프로세서 인스턴스
# ============================================================================

# 기본 유사도 채팅 프로세서
similarity_chat_processor = SimilarityChatProcessor(
    top_k=3,
    similarity_threshold=0.7,
    include_cross_conversation=False,
    enable_auto_embedding=True
)

# 크로스 대화 유사도 프로세서 (다른 대화에서도 검색)
cross_conversation_similarity_processor = SimilarityChatProcessor(
    top_k=5,
    similarity_threshold=0.75,
    include_cross_conversation=True,
    enable_auto_embedding=True
)

# 하이 컨피던스 프로세서 (높은 유사도만 사용)
high_confidence_similarity_processor = SimilarityChatProcessor(
    top_k=3,
    similarity_threshold=0.85,
    include_cross_conversation=False,
    enable_auto_embedding=True
)

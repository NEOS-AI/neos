"""
Standard Chat Processor - 일반 채팅 처리
템플릿 메서드 패턴의 구체 클래스: 컨텍스트 추가 없이 기본 LLM 호출만 수행
"""

from typing import Dict, List, Any

from neos.api.services.chat_message_processor import BaseChatMessageProcessor
from neos.utils.logger import get_logger

logger = get_logger(__name__)


class StandardChatProcessor(BaseChatMessageProcessor):
    """
    일반 채팅 프로세서
    - 유사도 검색 없음
    - 대화 히스토리만 사용
    - 기본 시스템 프롬프트 사용
    """

    def __init__(self):
        super().__init__()
        self.logger = logger

    async def prepare_context(
        self,
        conversation_id: str,
        user_content: str,
        history_messages: List[Dict],
        conversation: Dict,
        **kwargs
    ) -> Dict[str, Any]:
        """
        일반 채팅: 추가 컨텍스트 없음
        기본 시스템 프롬프트를 그대로 사용
        """
        self.logger.debug(f"Standard chat: No additional context preparation for conversation {conversation_id}")

        return {
            "enhanced_system_prompt": conversation.get("system_prompt"),
            "metadata": {
                "chat_type": "standard",
                "context_enhanced": False
            },
            "context_messages": []
        }

    async def post_process(
        self,
        user_message: Dict,
        assistant_message: Dict,
        context_data: Dict,
        **kwargs
    ) -> None:
        """
        일반 채팅: 추가 후처리 없음
        필요시 로깅, 통계 업데이트 등 추가 가능
        """
        self.logger.debug(
            f"Standard chat completed: user_msg={user_message['message_id']}, "
            f"assistant_msg={assistant_message['message_id']}"
        )


# 싱글톤 인스턴스
standard_chat_processor = StandardChatProcessor()

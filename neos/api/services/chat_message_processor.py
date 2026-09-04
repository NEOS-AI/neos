"""
Chat Message Processor - Template Method Pattern for code reuse
메시지 처리의 공통 로직을 추상화하고, 일반 채팅과 유사도 기반 채팅을 분리
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, AsyncGenerator, Any
import uuid

from neos.api.services.chat_service import ChatService
from neos.config.settings import settings as app_settings
from neos.services.chat_llm_service import chat_llm_service
from neos.utils.cost_calculator import cost_calculator
from neos.utils.logger import get_logger

logger = get_logger(__name__)


class BaseChatMessageProcessor(ABC):
    """
    Template Method Pattern: 메시지 처리의 공통 흐름을 정의

    공통 흐름:
    1. 사용자 메시지 저장
    2. 대화 히스토리 조회
    3. 컨텍스트 준비 (서브클래스에서 구현)
    4. LLM 응답 생성
    5. 어시스턴트 메시지 저장
    6. 후처리 (임베딩 생성 등)
    """

    def __init__(self):
        self.logger = logger

    async def process_message(
        self,
        conversation_id: str,
        user_content: str,
        user_id: Optional[str] = None,
        parent_message_id: Optional[str] = None,
        attachments: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Template Method: 메시지 처리의 전체 흐름

        Returns:
            {
                "user_message": Dict,
                "assistant_message": Dict,
                "processing_metadata": Dict  # 서브클래스에서 추가 정보 제공
            }
        """
        try:
            # 1. 사용자 메시지 저장
            user_message = await self._save_user_message(
                conversation_id=conversation_id,
                content=user_content,
                user_id=user_id,
                parent_message_id=parent_message_id,
                attachments=attachments,
                metadata=metadata
            )

            # 2. 대화 정보 조회
            conversation = await ChatService.get_conversation(conversation_id)
            if not conversation:
                raise ValueError(f"Conversation {conversation_id} not found")

            # 3. 대화 히스토리 조회
            history_messages = await self._get_conversation_history(
                conversation_id=conversation_id,
                limit=kwargs.get("history_limit", 20)
            )

            # 4. 컨텍스트 준비 (서브클래스에서 구현)
            context_data = await self.prepare_context(
                conversation_id=conversation_id,
                user_content=user_content,
                history_messages=history_messages,
                conversation=conversation,
                **kwargs
            )

            # 5. 어시스턴트 메시지 ID 생성
            assistant_message_id = str(uuid.uuid4())

            # 6. LLM 응답 생성 (서브클래스에서 오버라이드 가능)
            llm_response = await self.generate_llm_response(
                conversation_id=conversation_id,
                assistant_message_id=assistant_message_id,
                user_content=user_content,
                history_messages=history_messages,
                conversation=conversation,
                context_data=context_data,
                **kwargs
            )

            # 7. 어시스턴트 메시지 저장
            assistant_message = await self._save_assistant_message(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                llm_response=llm_response,
                parent_message_id=user_message["message_id"]
            )

            # 7.5. 메시지 저장 후 비용 기록 (FK 제약 위반 방지)
            await cost_calculator.record_cost_for_existing_message(
                message_id=assistant_message_id,
                conversation_id=conversation_id,
                provider=llm_response.get("provider", "anthropic"),
                model_name=llm_response["model_name"],
                prompt_tokens=llm_response["usage"]["prompt_tokens"],
                completion_tokens=llm_response["usage"]["completion_tokens"],
                total_tokens=llm_response["usage"]["total_tokens"],
                latency_ms=llm_response.get("latency_ms"),
                finish_reason=llm_response.get("finish_reason"),
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

            # 8. 후처리 (임베딩 생성 등)
            await self.post_process(
                user_message=user_message,
                assistant_message=assistant_message,
                context_data=context_data,
                **kwargs
            )

            # 9. 결과 반환
            return {
                "user_message": user_message,
                "assistant_message": assistant_message,
                "processing_metadata": context_data.get("metadata", {})
            }

        except Exception as e:
            self.logger.error(f"Failed to process message: {e}")
            raise

    async def process_message_stream(
        self,
        conversation_id: str,
        user_content: str,
        user_id: Optional[str] = None,
        parent_message_id: Optional[str] = None,
        attachments: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Template Method: 스트리밍 메시지 처리

        Yields:
            ChatStreamChunk 형식의 딕셔너리
        """
        try:
            # 1. 사용자 메시지 저장
            user_message = await self._save_user_message(
                conversation_id=conversation_id,
                content=user_content,
                user_id=user_id,
                parent_message_id=parent_message_id,
                attachments=attachments,
                metadata=metadata
            )

            # 사용자 메시지 확인 청크 전송
            yield {
                "type": "user_message",
                "content": user_message,
                "message_id": user_message["message_id"]
            }

            # 2. 대화 정보 조회
            conversation = await ChatService.get_conversation(conversation_id)

            # 3. 대화 히스토리 조회
            history_messages = await self._get_conversation_history(
                conversation_id=conversation_id,
                limit=kwargs.get("history_limit", 20)
            )

            # 4. 컨텍스트 준비
            context_data = await self.prepare_context(
                conversation_id=conversation_id,
                user_content=user_content,
                history_messages=history_messages,
                conversation=conversation,
                **kwargs
            )

            # 컨텍스트 메타데이터 전송 (유사도 검색 결과 등)
            if context_data.get("metadata"):
                yield {
                    "type": "context",
                    "content": context_data["metadata"]
                }

            # 5. 어시스턴트 메시지 ID 생성
            assistant_message_id = str(uuid.uuid4())

            # 6. LLM 스트리밍 응답 생성
            full_content = ""
            llm_metadata = {}

            async for chunk in self.generate_llm_response_stream(
                conversation_id=conversation_id,
                assistant_message_id=assistant_message_id,
                user_content=user_content,
                history_messages=history_messages,
                conversation=conversation,
                context_data=context_data,
                **kwargs
            ):
                full_content += chunk.get("content", "")
                if chunk.get("metadata"):
                    llm_metadata.update(chunk["metadata"])

                # 스트리밍 청크 전송
                yield {
                    "type": "content",
                    "content": chunk.get("content", ""),
                    "message_id": assistant_message_id,
                    "metadata": chunk.get("metadata")
                }

            # 7. 어시스턴트 메시지 저장
            llm_response = {
                "content": full_content,
                "model_name": llm_metadata.get("model_name", conversation.get("model_name")),
                "provider": llm_metadata.get("provider", "anthropic"),
                "usage": llm_metadata.get("usage", {}),
                "cost": llm_metadata.get("cost", {}),
                "latency_ms": llm_metadata.get("latency_ms", 0),
                "finish_reason": llm_metadata.get("finish_reason", "stop")
            }

            assistant_message = await self._save_assistant_message(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                llm_response=llm_response,
                parent_message_id=user_message["message_id"]
            )

            # 7.5. 메시지 저장 후 비용 기록 (FK 제약 위반 방지)
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

            # 8. 후처리
            await self.post_process(
                user_message=user_message,
                assistant_message=assistant_message,
                context_data=context_data,
                **kwargs
            )

            # 완료 청크 전송
            yield {
                "type": "done",
                "message_id": assistant_message_id,
                "metadata": {
                    "processing_metadata": context_data.get("metadata", {}),
                    "usage": llm_metadata.get("usage", {}),
                    "cost": llm_metadata.get("cost", {})
                }
            }

        except Exception as e:
            self.logger.error(f"Failed to process streaming message: {e}")
            yield {
                "type": "error",
                "content": str(e),
                "error": str(e)
            }

    # ========================================================================
    # 공통 메서드 (모든 서브클래스에서 사용)
    # ========================================================================

    async def _save_user_message(
        self,
        conversation_id: str,
        content: str,
        user_id: Optional[str],
        parent_message_id: Optional[str],
        attachments: Optional[List[Dict]],
        metadata: Optional[Dict]
    ) -> Dict:
        """사용자 메시지 저장"""
        return await ChatService.add_message(
            conversation_id=conversation_id,
            role="user",
            content=content,
            parent_message_id=parent_message_id,
            attachments=attachments,
            metadata=metadata or {}
        )

    async def _save_assistant_message(
        self,
        conversation_id: str,
        message_id: str,
        llm_response: Dict,
        parent_message_id: Optional[str]
    ) -> Dict:
        """어시스턴트 메시지 저장"""
        return await ChatService.add_message(
            conversation_id=conversation_id,
            role="assistant",
            content=llm_response["content"],
            message_id=message_id,
            model_name=llm_response["model_name"],
            total_tokens=llm_response["usage"].get("total_tokens", 0),
            prompt_tokens=llm_response["usage"].get("prompt_tokens", 0),
            completion_tokens=llm_response["usage"].get("completion_tokens", 0),
            parent_message_id=parent_message_id,
            metadata={
                "cost_usd": float(llm_response["cost"].get("total_cost", 0)),
                "latency_ms": llm_response.get("latency_ms", 0),
                "finish_reason": llm_response.get("finish_reason", "stop")
            }
        )

    async def _get_conversation_history(
        self,
        conversation_id: str,
        limit: int = 20
    ) -> List[Dict]:
        """대화 히스토리 조회"""
        return await ChatService.get_conversation_messages(
            conversation_id=conversation_id,
            limit=limit
        )

    # ========================================================================
    # 추상 메서드 (서브클래스에서 구현 필수)
    # ========================================================================

    @abstractmethod
    async def prepare_context(
        self,
        conversation_id: str,
        user_content: str,
        history_messages: List[Dict],
        conversation: Dict,
        **kwargs
    ) -> Dict[str, Any]:
        """
        컨텍스트 준비 (서브클래스에서 구현)

        Returns:
            {
                "enhanced_system_prompt": str,  # 강화된 시스템 프롬프트
                "metadata": Dict,  # 처리 메타데이터 (유사도 점수 등)
                "context_messages": List[Dict]  # 추가 컨텍스트 메시지
            }
        """
        pass

    # ========================================================================
    # 훅 메서드 (서브클래스에서 선택적 오버라이드)
    # ========================================================================

    async def generate_llm_response(
        self,
        conversation_id: str,
        assistant_message_id: str,
        user_content: str,
        history_messages: List[Dict],
        conversation: Dict,
        context_data: Dict,
        **kwargs
    ) -> Dict[str, Any]:
        """
        LLM 응답 생성 (기본 구현 제공, 필요시 오버라이드)
        """
        # history_messages는 이미 방금 저장한 유저 턴(user_content)으로 끝난다
        # (tail 조회이므로) — 여기서 다시 append하면 중복된다.
        # user_content 파라미터는 서브클래스 오버라이드 계약을 위해 시그니처에 남긴다.
        messages = history_messages

        return await chat_llm_service.generate_response(
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            conversation_messages=messages,
            model_name=conversation.get("model_name"),
            system_prompt=context_data.get("enhanced_system_prompt") or conversation.get("system_prompt"),
            temperature=conversation.get("temperature", 0.7),
            max_tokens=conversation.get("max_tokens")
        )

    async def generate_llm_response_stream(
        self,
        conversation_id: str,
        assistant_message_id: str,
        user_content: str,
        history_messages: List[Dict],
        conversation: Dict,
        context_data: Dict,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        LLM 스트리밍 응답 생성 (기본 구현 제공, 필요시 오버라이드)
        """
        # history_messages는 이미 방금 저장한 유저 턴(user_content)으로 끝난다
        # (tail 조회이므로) — 여기서 다시 append하면 중복된다.
        # user_content 파라미터는 서브클래스 오버라이드 계약을 위해 시그니처에 남긴다.
        messages = history_messages

        async for chunk in chat_llm_service.generate_response_stream(
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            conversation_messages=messages,
            model_name=conversation.get("model_name"),
            system_prompt=context_data.get("enhanced_system_prompt") or conversation.get("system_prompt"),
            temperature=conversation.get("temperature", 0.7),
            max_tokens=conversation.get("max_tokens")
        ):
            yield chunk

    async def post_process(
        self,
        user_message: Dict,
        assistant_message: Dict,
        context_data: Dict,
        **kwargs
    ) -> None:
        """
        후처리 작업 (기본 구현: 아무것도 안함, 필요시 오버라이드)
        예: 임베딩 생성, 통계 업데이트 등
        """
        pass

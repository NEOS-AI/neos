"""Chat service layer - handles chat business logic"""

from typing import Dict, Any, List, Optional
import uuid
import json

from neos.database.connection import db_manager
from neos.database.repositories.chat_repository import ChatRepository
from neos.utils.logger import get_logger

logger = get_logger(__name__)


class ChatService:
    """Service layer for chat operations"""

    # ============================================================================
    # Conversation Management
    # ============================================================================

    @staticmethod
    async def create_conversation(
        user_id: str,
        model_name: str = "claude-opus-4-5-20251101",
        title: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        mode: str = "standard",
        template_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """새 대화 생성"""
        conversation_id = str(uuid.uuid4())

        try:
            await ChatRepository.create_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
                model_name=model_name,
                system_prompt=system_prompt,
                template_id=template_id,
                mode=mode
            )

            # 생성된 대화 조회
            return await ChatService.get_conversation(conversation_id)

        except Exception as e:
            logger.error(f"Failed to create conversation: {e}")
            raise

    @staticmethod
    async def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
        """대화 조회"""
        conversation = await ChatRepository.get_conversation(conversation_id)

        if not conversation:
            return None

        # dataclass를 dict로 변환
        return {
            "conversation_id": conversation.conversation_id,
            "user_id": conversation.user_id,
            "title": conversation.title,
            "summary": conversation.summary,
            "model_name": conversation.model_name,
            "model_version": conversation.model_version,
            "system_prompt": conversation.system_prompt,
            "temperature": conversation.temperature,
            "max_tokens": conversation.max_tokens,
            "mode": conversation.mode,
            "status": conversation.status,
            "is_pinned": conversation.is_pinned,
            "is_shared": conversation.is_shared,
            "share_token": conversation.share_token,
            "visibility": conversation.visibility,
            "message_count": conversation.message_count,
            "total_tokens_used": conversation.total_tokens_used,
            "total_cost": conversation.total_cost,
            "last_message_at": conversation.last_message_at,
            "last_accessed_at": conversation.last_accessed_at,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "tags": conversation.tags,
            "metadata": conversation.metadata
        }

    @staticmethod
    async def update_conversation(
        conversation_id: str,
        title: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        is_pinned: Optional[bool] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """대화 업데이트"""
        updates = {}

        if title is not None:
            updates["title"] = title
        if system_prompt is not None:
            updates["system_prompt"] = system_prompt
        if temperature is not None:
            updates["temperature"] = temperature
        if is_pinned is not None:
            updates["is_pinned"] = is_pinned
        if tags is not None:
            updates["tags"] = tags
        if metadata is not None:
            updates["metadata"] = metadata

        if not updates:
            return await ChatService.get_conversation(conversation_id)

        await ChatRepository.update_conversation(conversation_id, updates)
        return await ChatService.get_conversation(conversation_id)

    @staticmethod
    async def delete_conversation(conversation_id: str, soft_delete: bool = True) -> bool:
        """대화 삭제"""
        await ChatRepository.delete_conversation(conversation_id, soft_delete)
        return True

    @staticmethod
    async def archive_conversation(conversation_id: str) -> Dict[str, Any]:
        """대화 아카이브"""
        await ChatRepository.archive_conversation(conversation_id)
        return await ChatService.get_conversation(conversation_id)

    @staticmethod
    async def list_conversations(
        user_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False
    ) -> Dict[str, Any]:
        """사용자의 대화 목록 조회"""
        conversations, total_count = await ChatRepository.list_conversations(
            user_id=user_id,
            status=status,
            include_archived=include_archived,
            limit=limit,
            offset=offset
        )

        return {
            "conversations": conversations,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count
        }

    # ============================================================================
    # Message Management
    # ============================================================================

    @staticmethod
    async def add_message(
        conversation_id: str,
        role: str,
        content: str,
        message_id: Optional[str] = None,
        model_name: Optional[str] = None,
        total_tokens: Optional[int] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        parent_message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """메시지 추가"""
        if not message_id:
            message_id = str(uuid.uuid4())

        await ChatRepository.add_message(
            message_id=message_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            tool_calls=tool_calls,
            tool_results=tool_results,
            attachments=attachments,
            parent_message_id=parent_message_id,
            metadata=metadata
        )

        return await ChatService.get_message(message_id)

    @staticmethod
    async def get_message(message_id: str) -> Optional[Dict[str, Any]]:
        """메시지 조회"""
        from neos.api.services.chat_service_helper import message_to_dict
        message = await ChatRepository.get_message(message_id)
        if not message:
            return None
        return message_to_dict(message)

    @staticmethod
    async def get_conversation_messages(
        conversation_id: str,
        limit: int = 100,
        before_sequence: Optional[int] = None,
        after_sequence: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """대화의 메시지 목록 조회"""
        from neos.api.services.chat_service_helper import messages_to_dict_list

        messages = await ChatRepository.get_conversation_messages(
            conversation_id=conversation_id,
            limit=limit,
            before_sequence=before_sequence,
            after_sequence=after_sequence
        )

        return messages_to_dict_list(messages)

    @staticmethod
    async def edit_message(
        message_id: str,
        new_content: str,
        edited_by: str,
        edit_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """메시지 편집"""
        # 기존 메시지 조회
        message = await ChatService.get_message(message_id)
        if not message:
            raise ValueError(f"Message not found: {message_id}")

        previous_content = message["content"]

        # 편집 이력 저장
        await ChatRepository.edit_message_add_history(
            message_id=message_id,
            previous_content=previous_content,
            new_content=new_content,
            edited_by=edited_by,
            edit_reason=edit_reason
        )

        # 메시지 업데이트
        await ChatRepository.update_message_content(message_id, new_content)

        return await ChatService.get_message(message_id)

    @staticmethod
    async def add_message_feedback(
        message_id: str,
        feedback: str,
        comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """메시지에 피드백 추가"""
        await ChatRepository.add_message_feedback(message_id, feedback, comment)
        return await ChatService.get_message(message_id)

    @staticmethod
    async def delete_message(message_id: str) -> bool:
        """메시지 삭제"""
        await ChatRepository.delete_message(message_id)
        return True

    # ============================================================================
    # Analytics
    # ============================================================================

    @staticmethod
    async def get_conversation_analytics(
        conversation_id: str,
        period: str = "session"
    ) -> Optional[Dict[str, Any]]:
        """대화 분석 데이터 조회"""
        from neos.api.services.chat_service_helper import analytics_to_dict

        analytics = await ChatRepository.get_conversation_analytics(conversation_id, period)

        if not analytics:
            return None

        return analytics_to_dict(analytics)

    @staticmethod
    async def get_user_statistics(user_id: str) -> Dict[str, Any]:
        """사용자 채팅 통계"""
        return await ChatRepository.get_user_statistics(user_id)

    # ============================================================================
    # Templates
    # ============================================================================

    @staticmethod
    async def create_template(
        name: str,
        created_by: str,
        description: Optional[str] = None,
        category: Optional[str] = None,
        default_model: str = "claude-opus-4-5-20251101",
        default_system_prompt: Optional[str] = None,
        default_temperature: float = 0.7,
        default_settings: Optional[Dict[str, Any]] = None,
        initial_messages: Optional[List[Dict[str, Any]]] = None,
        is_public: bool = False,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """대화 템플릿 생성"""
        template_id = str(uuid.uuid4())

        query = """
        INSERT INTO conversation_templates (
            template_id,
            name,
            description,
            category,
            default_model,
            default_system_prompt,
            default_temperature,
            default_settings,
            initial_messages,
            is_public,
            created_by,
            tags,
            metadata
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        RETURNING template_id
        """

        await db_manager.execute(
            query,
            template_id,
            name,
            description,
            category,
            default_model,
            default_system_prompt,
            default_temperature,
            json.dumps(default_settings or {}),
            json.dumps(initial_messages or []),
            is_public,
            created_by,
            json.dumps(tags or []),
            json.dumps(metadata or {})
        )

        return await ChatService.get_template(template_id)

    @staticmethod
    async def get_template(template_id: str) -> Optional[Dict[str, Any]]:
        """템플릿 조회"""
        from neos.api.services.chat_service_helper import template_to_dict

        template = await ChatRepository.get_template(template_id)

        if not template:
            return None

        return template_to_dict(template)

    @staticmethod
    async def list_templates(
        category: Optional[str] = None,
        is_public: Optional[bool] = None,
        created_by: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """템플릿 목록 조회"""
        from neos.api.services.chat_service_helper import templates_to_dict_list

        templates, total_count = await ChatRepository.list_templates(
            category=category,
            is_public=is_public,
            created_by=created_by,
            limit=limit,
            offset=offset
        )

        return {
            "templates": templates_to_dict_list(templates),
            "total_count": total_count
        }

    # ============================================================================
    # Title Generation
    # ============================================================================

    @staticmethod
    async def generate_title(conversation_id: str, user_message: str) -> str:
        """사용자 메시지를 기반으로 제목 생성

        Args:
            conversation_id: 대화 ID
            user_message: 제목 생성에 사용할 사용자 메시지

        Returns:
            생성된 제목 문자열
        """
        from neos.services.chat_llm_service import chat_llm_service

        if not user_message or not user_message.strip():
            return "New chat"

        # LLM을 사용하여 제목 생성
        title_prompt = f"""Based on the following user message, generate a short, concise title (maximum 6 words) that captures the essence of the conversation.
Only return the title, nothing else.

User message: {user_message}"""

        try:
            response = await chat_llm_service.generate_response(
                conversation_id=conversation_id,
                message_id=str(uuid.uuid4()),  # 임시 message_id
                conversation_messages=[{"role": "user", "content": title_prompt}],
                model_name="claude-sonnet-4-5-20250929",
                temperature=0.7,
                max_tokens=50,
                workflow_type="title_generation",
                enable_context_optimization=False
            )

            title = response.get("content", "New chat").strip()

            # 제목이 너무 길면 잘라내기
            if len(title) > 100:
                title = title[:97] + "..."

            return title

        except Exception as e:
            logger.error(f"Failed to generate title: {e}")
            # 에러 발생 시 첫 번째 메시지의 일부를 제목으로 사용
            return user_message[:50] + ("..." if len(user_message) > 50 else "")

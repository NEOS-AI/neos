"""Chat service layer - handles chat business logic"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import uuid
import json
import asyncpg

from neos.database.connection import db_manager
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
        model_name: str = "claude-opus-4-1-20250805",
        title: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        template_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """새 대화 생성"""
        conversation_id = str(uuid.uuid4())

        query = """
        SELECT create_conversation($1, $2, $3, $4, $5)
        """

        try:
            result = await db_manager.fetch_one(
                query,
                user_id,
                conversation_id,
                model_name,
                system_prompt,
                template_id
            )

            # 생성된 대화 조회
            return await ChatService.get_conversation(conversation_id)

        except Exception as e:
            logger.error(f"Failed to create conversation: {e}")
            raise

    @staticmethod
    async def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
        """대화 조회"""
        query = """
        SELECT
            conversation_id,
            user_id,
            title,
            summary,
            model_name,
            model_version,
            system_prompt,
            temperature,
            max_tokens,
            status,
            is_pinned,
            is_shared,
            share_token,
            message_count,
            total_tokens_used,
            total_cost,
            last_message_at,
            last_accessed_at,
            created_at,
            updated_at,
            tags,
            metadata
        FROM conversations
        WHERE conversation_id = $1 AND deleted_at IS NULL
        """

        row = await db_manager.fetch_one(query, conversation_id)

        if not row:
            return None

        return {
            "conversation_id": row[0],
            "user_id": row[1],
            "title": row[2],
            "summary": row[3],
            "model_name": row[4],
            "model_version": row[5],
            "system_prompt": row[6],
            "temperature": float(row[7]) if row[7] is not None else 0.7,
            "max_tokens": row[8],
            "status": row[9],
            "is_pinned": row[10],
            "is_shared": row[11],
            "share_token": row[12],
            "message_count": row[13],
            "total_tokens_used": row[14],
            "total_cost": float(row[15]) if row[15] is not None else 0.0,
            "last_message_at": row[16],
            "last_accessed_at": row[17],
            "created_at": row[18],
            "updated_at": row[19],
            "tags": row[20] if row[20] else [],
            "metadata": row[21] if row[21] else {}
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
        updates = []
        params = []
        param_idx = 1

        if title is not None:
            updates.append(f"title = ${param_idx}")
            params.append(title)
            param_idx += 1

        if system_prompt is not None:
            updates.append(f"system_prompt = ${param_idx}")
            params.append(system_prompt)
            param_idx += 1

        if temperature is not None:
            updates.append(f"temperature = ${param_idx}")
            params.append(temperature)
            param_idx += 1

        if is_pinned is not None:
            updates.append(f"is_pinned = ${param_idx}")
            params.append(is_pinned)
            param_idx += 1

        if tags is not None:
            updates.append(f"tags = CAST(${param_idx} AS jsonb)")
            params.append(json.dumps(tags))
            param_idx += 1

        if metadata is not None:
            updates.append(f"metadata = CAST(${param_idx} AS jsonb)")
            params.append(json.dumps(metadata))
            param_idx += 1

        if not updates:
            return await ChatService.get_conversation(conversation_id)

        query = f"""
        UPDATE conversations
        SET {', '.join(updates)}
        WHERE conversation_id = ${param_idx}
        RETURNING conversation_id
        """
        params.append(conversation_id)

        await db_manager.execute(query, *params)
        return await ChatService.get_conversation(conversation_id)

    @staticmethod
    async def delete_conversation(conversation_id: str, soft_delete: bool = True) -> bool:
        """대화 삭제"""
        if soft_delete:
            query = """
            UPDATE conversations
            SET deleted_at = CURRENT_TIMESTAMP, status = 'deleted'
            WHERE conversation_id = $1
            """
        else:
            query = """
            DELETE FROM conversations
            WHERE conversation_id = $1
            """

        await db_manager.execute(query, conversation_id)
        return True

    @staticmethod
    async def archive_conversation(conversation_id: str) -> Dict[str, Any]:
        """대화 아카이브"""
        query = """
        UPDATE conversations
        SET status = 'archived', archived_at = CURRENT_TIMESTAMP
        WHERE conversation_id = $1
        RETURNING conversation_id
        """

        await db_manager.execute(query, conversation_id)
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
        where_clauses = ["user_id = $1", "deleted_at IS NULL"]
        params = [user_id]
        param_idx = 2

        if status:
            where_clauses.append(f"status = ${param_idx}")
            params.append(status)
            param_idx += 1
        elif not include_archived:
            where_clauses.append("status != 'archived'")

        where_sql = " AND ".join(where_clauses)

        # 목록 조회
        list_query = f"""
        SELECT
            conversation_id,
            user_id,
            title,
            model_name,
            status,
            is_pinned,
            message_count,
            last_message_at,
            created_at,
            (
                SELECT content
                FROM messages m
                WHERE m.conversation_id = c.conversation_id
                  AND m.role = 'user'
                ORDER BY m.sequence_number ASC
                LIMIT 1
            ) as first_message_preview,
            (
                SELECT content
                FROM messages m
                WHERE m.conversation_id = c.conversation_id
                ORDER BY m.sequence_number DESC
                LIMIT 1
            ) as last_message_preview
        FROM conversations c
        WHERE {where_sql}
        ORDER BY is_pinned DESC, last_message_at DESC NULLS LAST, created_at DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        params.extend([limit, offset])
        rows = await db_manager.fetch_all(list_query, *params)

        # 전체 개수 조회
        count_query = f"""
        SELECT COUNT(*)
        FROM conversations
        WHERE {where_sql}
        """
        count_params = params[:-2]  # limit, offset 제외
        count_result = await db_manager.fetch_one(count_query, *count_params)
        total_count = count_result[0] if count_result else 0

        conversations = []
        for row in rows:
            conversations.append({
                "conversation_id": row[0],
                "user_id": row[1],
                "title": row[2],
                "model_name": row[3],
                "status": row[4],
                "is_pinned": row[5],
                "message_count": row[6],
                "last_message_at": row[7],
                "created_at": row[8],
                "first_message_preview": row[9][:100] if row[9] else None,
                "last_message_preview": row[10][:100] if row[10] else None
            })

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

        query = """
        INSERT INTO messages (
            message_id,
            conversation_id,
            role,
            content,
            model_name,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            tool_calls,
            tool_results,
            attachments,
            parent_message_id,
            metadata,
            status
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, 'completed')
        RETURNING message_id
        """

        await db_manager.execute(
            query,
            message_id,
            conversation_id,
            role,
            content,
            model_name,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            json.dumps(tool_calls or []),
            json.dumps(tool_results or []),
            json.dumps(attachments or []),
            parent_message_id,
            json.dumps(metadata or {})
        )

        return await ChatService.get_message(message_id)

    @staticmethod
    async def get_message(message_id: str) -> Optional[Dict[str, Any]]:
        """메시지 조회"""
        query = """
        SELECT
            message_id,
            conversation_id,
            role,
            content,
            content_type,
            sequence_number,
            parent_message_id,
            status,
            model_name,
            model_version,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            finish_reason,
            tool_calls,
            tool_results,
            attachments,
            user_feedback,
            feedback_comment,
            quality_score,
            created_at,
            updated_at,
            completed_at,
            metadata
        FROM messages
        WHERE message_id = $1
        """

        row = await db_manager.fetch_one(query, message_id)

        if not row:
            return None

        return {
            "message_id": row[0],
            "conversation_id": row[1],
            "role": row[2],
            "content": row[3],
            "content_type": row[4],
            "sequence_number": row[5],
            "parent_message_id": row[6],
            "status": row[7],
            "model_name": row[8],
            "model_version": row[9],
            "prompt_tokens": row[10],
            "completion_tokens": row[11],
            "total_tokens": row[12],
            "finish_reason": row[13],
            "tool_calls": row[14] if row[14] else [],
            "tool_results": row[15] if row[15] else [],
            "attachments": row[16] if row[16] else [],
            "user_feedback": row[17],
            "feedback_comment": row[18],
            "quality_score": float(row[19]) if row[19] is not None else None,
            "created_at": row[20],
            "updated_at": row[21],
            "completed_at": row[22],
            "metadata": row[23] if row[23] else {}
        }

    @staticmethod
    async def get_conversation_messages(
        conversation_id: str,
        limit: int = 100,
        before_sequence: Optional[int] = None,
        after_sequence: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """대화의 메시지 목록 조회"""
        where_clauses = ["conversation_id = $1"]
        params = [conversation_id]
        param_idx = 2

        if before_sequence is not None:
            where_clauses.append(f"sequence_number < ${param_idx}")
            params.append(before_sequence)
            param_idx += 1

        if after_sequence is not None:
            where_clauses.append(f"sequence_number > ${param_idx}")
            params.append(after_sequence)
            param_idx += 1

        where_sql = " AND ".join(where_clauses)

        query = f"""
        SELECT
            message_id,
            conversation_id,
            role,
            content,
            content_type,
            sequence_number,
            parent_message_id,
            status,
            model_name,
            model_version,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            finish_reason,
            tool_calls,
            tool_results,
            attachments,
            user_feedback,
            feedback_comment,
            quality_score,
            created_at,
            updated_at,
            completed_at,
            metadata
        FROM messages
        WHERE {where_sql}
        ORDER BY sequence_number ASC
        LIMIT ${param_idx}
        """

        params.append(limit)
        rows = await db_manager.fetch_all(query, *params)

        messages = []
        for row in rows:
            messages.append({
                "message_id": row[0],
                "conversation_id": row[1],
                "role": row[2],
                "content": row[3],
                "content_type": row[4],
                "sequence_number": row[5],
                "parent_message_id": row[6],
                "status": row[7],
                "model_name": row[8],
                "model_version": row[9],
                "prompt_tokens": row[10],
                "completion_tokens": row[11],
                "total_tokens": row[12],
                "finish_reason": row[13],
                "tool_calls": row[14] if row[14] else [],
                "tool_results": row[15] if row[15] else [],
                "attachments": row[16] if row[16] else [],
                "user_feedback": row[17],
                "feedback_comment": row[18],
                "quality_score": float(row[19]) if row[19] is not None else None,
                "created_at": row[20],
                "updated_at": row[21],
                "completed_at": row[22],
                "metadata": row[23] if row[23] else {}
            })

        return messages

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
        edit_query = """
        INSERT INTO message_edits (
            message_id,
            edit_version,
            previous_content,
            new_content,
            edited_by,
            edit_reason
        ) VALUES (
            $1,
            (SELECT COALESCE(MAX(edit_version), 0) + 1 FROM message_edits WHERE message_id = $1),
            $2,
            $3,
            $4,
            $5
        )
        """

        await db_manager.execute(
            edit_query,
            message_id,
            previous_content,
            new_content,
            edited_by,
            edit_reason
        )

        # 메시지 업데이트
        update_query = """
        UPDATE messages
        SET content = $1, status = 'edited', updated_at = CURRENT_TIMESTAMP
        WHERE message_id = $2
        """

        await db_manager.execute(update_query, new_content, message_id)

        return await ChatService.get_message(message_id)

    @staticmethod
    async def add_message_feedback(
        message_id: str,
        feedback: str,
        comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """메시지에 피드백 추가"""
        query = """
        UPDATE messages
        SET user_feedback = $1, feedback_comment = $2, updated_at = CURRENT_TIMESTAMP
        WHERE message_id = $3
        RETURNING message_id
        """

        await db_manager.execute(query, feedback, comment, message_id)
        return await ChatService.get_message(message_id)

    @staticmethod
    async def delete_message(message_id: str) -> bool:
        """메시지 삭제"""
        query = """
        DELETE FROM messages
        WHERE message_id = $1
        """

        await db_manager.execute(query, message_id)
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
        query = """
        SELECT
            conversation_id,
            analysis_period,
            period_start,
            period_end,
            total_messages,
            user_messages,
            assistant_messages,
            total_tokens_used,
            prompt_tokens_used,
            completion_tokens_used,
            estimated_cost,
            average_response_time_ms,
            average_message_length,
            average_quality_score,
            tools_used,
            tool_call_count,
            positive_feedback_count,
            negative_feedback_count,
            messages_edited_count,
            created_at,
            metadata
        FROM chat_analytics
        WHERE conversation_id = $1 AND analysis_period = $2
        ORDER BY created_at DESC
        LIMIT 1
        """

        row = await db_manager.fetch_one(query, conversation_id, period)

        if not row:
            return None

        return {
            "conversation_id": row[0],
            "analysis_period": row[1],
            "period_start": row[2],
            "period_end": row[3],
            "total_messages": row[4],
            "user_messages": row[5],
            "assistant_messages": row[6],
            "total_tokens_used": row[7],
            "prompt_tokens_used": row[8],
            "completion_tokens_used": row[9],
            "estimated_cost": float(row[10]) if row[10] is not None else 0.0,
            "average_response_time_ms": row[11],
            "average_message_length": row[12],
            "average_quality_score": float(row[13]) if row[13] is not None else None,
            "tools_used": row[14] if row[14] else [],
            "tool_call_count": row[15],
            "positive_feedback_count": row[16],
            "negative_feedback_count": row[17],
            "messages_edited_count": row[18],
            "created_at": row[19],
            "metadata": row[20] if row[20] else {}
        }

    @staticmethod
    async def get_user_statistics(user_id: str) -> Dict[str, Any]:
        """사용자 채팅 통계"""
        query = """
        SELECT
            $1 as user_id,
            COUNT(DISTINCT conversation_id) as total_conversations,
            COUNT(DISTINCT conversation_id) FILTER (WHERE status = 'active') as active_conversations,
            COUNT(DISTINCT conversation_id) FILTER (WHERE is_pinned = TRUE) as pinned_conversations,
            SUM(message_count) as total_messages,
            SUM(total_tokens_used) as total_tokens,
            SUM(total_cost) as total_cost,
            MAX(last_message_at) as last_activity_at,
            MIN(created_at) as first_conversation_at
        FROM conversations
        WHERE user_id = $1 AND deleted_at IS NULL
        """

        row = await db_manager.fetch_one(query, user_id)

        if not row:
            return {
                "user_id": user_id,
                "total_conversations": 0,
                "active_conversations": 0,
                "pinned_conversations": 0,
                "total_messages": 0,
                "total_tokens": 0,
                "total_cost": 0.0,
                "last_activity_at": None,
                "first_conversation_at": None
            }

        return {
            "user_id": row[0],
            "total_conversations": row[1] or 0,
            "active_conversations": row[2] or 0,
            "pinned_conversations": row[3] or 0,
            "total_messages": row[4] or 0,
            "total_tokens": row[5] or 0,
            "total_cost": float(row[6]) if row[6] is not None else 0.0,
            "last_activity_at": row[7],
            "first_conversation_at": row[8]
        }

    # ============================================================================
    # Templates
    # ============================================================================

    @staticmethod
    async def create_template(
        name: str,
        created_by: str,
        description: Optional[str] = None,
        category: Optional[str] = None,
        default_model: str = "claude-opus-4-1-20250805",
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
        query = """
        SELECT
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
            is_active,
            created_by,
            usage_count,
            created_at,
            updated_at,
            tags,
            metadata
        FROM conversation_templates
        WHERE template_id = $1 AND is_active = TRUE
        """

        row = await db_manager.fetch_one(query, template_id)

        if not row:
            return None

        return {
            "template_id": row[0],
            "name": row[1],
            "description": row[2],
            "category": row[3],
            "default_model": row[4],
            "default_system_prompt": row[5],
            "default_temperature": float(row[6]) if row[6] is not None else 0.7,
            "default_settings": row[7] if row[7] else {},
            "initial_messages": row[8] if row[8] else [],
            "is_public": row[9],
            "is_active": row[10],
            "created_by": row[11],
            "usage_count": row[12],
            "created_at": row[13],
            "updated_at": row[14],
            "tags": row[15] if row[15] else [],
            "metadata": row[16] if row[16] else {}
        }

    @staticmethod
    async def list_templates(
        category: Optional[str] = None,
        is_public: Optional[bool] = None,
        created_by: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """템플릿 목록 조회"""
        where_clauses = ["is_active = TRUE"]
        params = []
        param_idx = 1

        if category:
            where_clauses.append(f"category = ${param_idx}")
            params.append(category)
            param_idx += 1

        if is_public is not None:
            where_clauses.append(f"is_public = ${param_idx}")
            params.append(is_public)
            param_idx += 1

        if created_by:
            where_clauses.append(f"created_by = ${param_idx}")
            params.append(created_by)
            param_idx += 1

        where_sql = " AND ".join(where_clauses)

        # 목록 조회
        list_query = f"""
        SELECT
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
            is_active,
            created_by,
            usage_count,
            created_at,
            updated_at,
            tags,
            metadata
        FROM conversation_templates
        WHERE {where_sql}
        ORDER BY usage_count DESC, created_at DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        params.extend([limit, offset])
        rows = await db_manager.fetch_all(list_query, *params)

        # 전체 개수 조회
        count_query = f"SELECT COUNT(*) FROM conversation_templates WHERE {where_sql}"
        count_params = params[:-2]
        count_result = await db_manager.fetch_one(count_query, *count_params)
        total_count = count_result[0] if count_result else 0

        templates = []
        for row in rows:
            templates.append({
                "template_id": row[0],
                "name": row[1],
                "description": row[2],
                "category": row[3],
                "default_model": row[4],
                "default_system_prompt": row[5],
                "default_temperature": float(row[6]) if row[6] is not None else 0.7,
                "default_settings": row[7] if row[7] else {},
                "initial_messages": row[8] if row[8] else [],
                "is_public": row[9],
                "is_active": row[10],
                "created_by": row[11],
                "usage_count": row[12],
                "created_at": row[13],
                "updated_at": row[14],
                "tags": row[15] if row[15] else [],
                "metadata": row[16] if row[16] else {}
            })

        return {
            "templates": templates,
            "total_count": total_count
        }

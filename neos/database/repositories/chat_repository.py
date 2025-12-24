"""Chat Repository - 채팅 데이터 접근 레이어

이 모듈은 Repository 패턴을 구현하여 채팅, 대화, 메시지 관련 모든 데이터베이스
쿼리를 캡슐화하고, 매직 인덱스 접근을 데이터 클래스로 대체합니다.
"""

from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime
from dataclasses import dataclass
import json

from neos.database.connection import db_manager


@dataclass
class Conversation:
    """대화 데이터 클래스"""
    conversation_id: str
    user_id: str
    title: Optional[str]
    summary: Optional[str]
    model_name: str
    model_version: Optional[str]
    system_prompt: Optional[str]
    temperature: float
    max_tokens: Optional[int]
    mode: str
    status: str
    is_pinned: bool
    is_shared: bool
    share_token: Optional[str]
    visibility: str  # 추가: 'public' 또는 'private'
    message_count: int
    total_tokens_used: int
    total_cost: float
    last_message_at: Optional[datetime]
    last_accessed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    tags: List[str]
    metadata: Dict[str, Any]


@dataclass
class Message:
    """메시지 데이터 클래스"""
    message_id: str
    conversation_id: str
    role: str
    content: str
    content_type: str
    sequence_number: int
    parent_message_id: Optional[str]
    status: str
    model_name: Optional[str]
    model_version: Optional[str]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    finish_reason: Optional[str]
    tool_calls: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    attachments: List[Dict[str, Any]]
    user_feedback: Optional[str]
    feedback_comment: Optional[str]
    quality_score: Optional[float]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    metadata: Dict[str, Any]


@dataclass
class ConversationAnalytics:
    """대화 분석 데이터 클래스"""
    conversation_id: str
    analysis_period: str
    period_start: datetime
    period_end: datetime
    total_messages: int
    user_messages: int
    assistant_messages: int
    total_tokens_used: int
    prompt_tokens_used: int
    completion_tokens_used: int
    estimated_cost: float
    average_response_time_ms: Optional[int]
    average_message_length: Optional[int]
    average_quality_score: Optional[float]
    tools_used: List[str]
    tool_call_count: int
    positive_feedback_count: int
    negative_feedback_count: int
    messages_edited_count: int
    created_at: datetime
    metadata: Dict[str, Any]


@dataclass
class ConversationTemplate:
    """대화 템플릿 데이터 클래스"""
    template_id: str
    name: str
    description: Optional[str]
    category: Optional[str]
    default_model: str
    default_system_prompt: Optional[str]
    default_temperature: float
    default_settings: Dict[str, Any]
    initial_messages: List[Dict[str, Any]]
    is_public: bool
    is_active: bool
    created_by: str
    usage_count: int
    created_at: datetime
    updated_at: datetime
    tags: List[str]
    metadata: Dict[str, Any]


class ChatRepository:
    """채팅 데이터 리포지토리"""

    # ==================== Conversation 관리 ====================

    @staticmethod
    async def create_conversation(
        user_id: str,
        conversation_id: str,
        model_name: str,
        system_prompt: Optional[str],
        template_id: Optional[str],
        mode: str = "standard"
    ) -> str:
        """새 대화 생성 (stored procedure 호출)

        Args:
            user_id: 사용자 ID
            conversation_id: 대화 ID
            model_name: 모델 이름
            system_prompt: 시스템 프롬프트
            template_id: 템플릿 ID
            mode: 대화 모드 (standard, rag, similarity, deep_research)

        Returns:
            생성된 대화 ID
        """
        query = """
        SELECT create_conversation($1, $2, $3, $4, $5, $6)
        """

        result = await db_manager.fetch_one(
            query,
            user_id,
            conversation_id,
            model_name,
            system_prompt,
            template_id,
            mode
        )
        return result[0] if result else conversation_id

    @staticmethod
    async def get_conversation(conversation_id: str) -> Optional[Conversation]:
        """대화 조회

        Args:
            conversation_id: 대화 ID

        Returns:
            대화 데이터 또는 None
        """
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
            mode,
            status,
            is_pinned,
            is_shared,
            share_token,
            visibility,
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

        return Conversation(
            conversation_id=row[0],
            user_id=row[1],
            title=row[2],
            summary=row[3],
            model_name=row[4],
            model_version=row[5],
            system_prompt=row[6],
            temperature=float(row[7]) if row[7] is not None else 0.7,
            max_tokens=row[8],
            mode=row[9] if row[9] else "standard",
            status=row[10],
            is_pinned=row[11],
            is_shared=row[12],
            share_token=row[13],
            visibility=row[14] if row[14] else "private",
            message_count=row[15],
            total_tokens_used=row[16],
            total_cost=float(row[17]) if row[17] is not None else 0.0,
            last_message_at=row[18],
            last_accessed_at=row[19],
            created_at=row[20],
            updated_at=row[21],
            tags=row[22] if row[22] else [],
            metadata=row[23] if row[23] else {}
        )

    @staticmethod
    async def update_conversation(
        conversation_id: str,
        updates: Dict[str, Any]
    ) -> None:
        """대화 업데이트

        Args:
            conversation_id: 대화 ID
            updates: 업데이트할 필드와 값의 딕셔너리
        """
        if not updates:
            return

        update_clauses = []
        params = []
        param_idx = 1

        for field, value in updates.items():
            if field in ['tags', 'metadata']:
                update_clauses.append(f"{field} = CAST(${param_idx} AS jsonb)")
                params.append(json.dumps(value))
            else:
                update_clauses.append(f"{field} = ${param_idx}")
                params.append(value)
            param_idx += 1

        query = f"""
        UPDATE conversations
        SET {', '.join(update_clauses)}
        WHERE conversation_id = ${param_idx}
        RETURNING conversation_id
        """
        params.append(conversation_id)

        await db_manager.execute(query, *params)

    @staticmethod
    async def delete_conversation(conversation_id: str, soft_delete: bool = True) -> None:
        """대화 삭제

        Args:
            conversation_id: 대화 ID
            soft_delete: soft delete 여부
        """
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

    @staticmethod
    async def archive_conversation(conversation_id: str) -> None:
        """대화 아카이브

        Args:
            conversation_id: 대화 ID
        """
        query = """
        UPDATE conversations
        SET status = 'archived', archived_at = CURRENT_TIMESTAMP
        WHERE conversation_id = $1
        RETURNING conversation_id
        """

        await db_manager.execute(query, conversation_id)

    @staticmethod
    async def list_conversations(
        user_id: str,
        status: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        """대화 목록 조회

        Args:
            user_id: 사용자 ID
            status: 상태 필터
            include_archived: 아카이브 포함 여부
            limit: 최대 결과 수
            offset: 오프셋

        Returns:
            (대화 목록, 전체 개수)
        """
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

        conversations = [
            {
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
            }
            for row in rows
        ]

        return conversations, total_count

    # ==================== Message 관리 ====================

    @staticmethod
    async def add_message(
        message_id: str,
        conversation_id: str,
        role: str,
        content: str,
        model_name: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        parent_message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """메시지 추가

        Args:
            message_id: 메시지 ID
            conversation_id: 대화 ID
            role: 역할 (user/assistant/system)
            content: 메시지 내용
            model_name: 모델 이름
            prompt_tokens: 프롬프트 토큰 수
            completion_tokens: 완성 토큰 수
            total_tokens: 전체 토큰 수
            tool_calls: 도구 호출 목록
            tool_results: 도구 결과 목록
            attachments: 첨부파일 목록
            parent_message_id: 부모 메시지 ID
            metadata: 메타데이터

        Returns:
            생성된 메시지 ID
        """
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

        return message_id

    @staticmethod
    async def get_message(message_id: str) -> Optional[Message]:
        """메시지 조회

        Args:
            message_id: 메시지 ID

        Returns:
            메시지 데이터 또는 None
        """
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

        return Message(
            message_id=row[0],
            conversation_id=row[1],
            role=row[2],
            content=row[3],
            content_type=row[4],
            sequence_number=row[5],
            parent_message_id=row[6],
            status=row[7],
            model_name=row[8],
            model_version=row[9],
            prompt_tokens=row[10],
            completion_tokens=row[11],
            total_tokens=row[12],
            finish_reason=row[13],
            tool_calls=row[14] if row[14] else [],
            tool_results=row[15] if row[15] else [],
            attachments=row[16] if row[16] else [],
            user_feedback=row[17],
            feedback_comment=row[18],
            quality_score=float(row[19]) if row[19] is not None else None,
            created_at=row[20],
            updated_at=row[21],
            completed_at=row[22],
            metadata=row[23] if row[23] else {}
        )

    @staticmethod
    async def get_conversation_messages(
        conversation_id: str,
        limit: int = 100,
        before_sequence: Optional[int] = None,
        after_sequence: Optional[int] = None
    ) -> List[Message]:
        """대화의 메시지 목록 조회

        Args:
            conversation_id: 대화 ID
            limit: 최대 결과 수
            before_sequence: 이전 시퀀스 번호
            after_sequence: 이후 시퀀스 번호

        Returns:
            메시지 목록
        """
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

        return [
            Message(
                message_id=row[0],
                conversation_id=row[1],
                role=row[2],
                content=row[3],
                content_type=row[4],
                sequence_number=row[5],
                parent_message_id=row[6],
                status=row[7],
                model_name=row[8],
                model_version=row[9],
                prompt_tokens=row[10],
                completion_tokens=row[11],
                total_tokens=row[12],
                finish_reason=row[13],
                tool_calls=row[14] if row[14] else [],
                tool_results=row[15] if row[15] else [],
                attachments=row[16] if row[16] else [],
                user_feedback=row[17],
                feedback_comment=row[18],
                quality_score=float(row[19]) if row[19] is not None else None,
                created_at=row[20],
                updated_at=row[21],
                completed_at=row[22],
                metadata=row[23] if row[23] else {}
            )
            for row in rows
        ]

    @staticmethod
    async def edit_message_add_history(
        message_id: str,
        previous_content: str,
        new_content: str,
        edited_by: str,
        edit_reason: Optional[str]
    ) -> None:
        """메시지 편집 이력 저장

        Args:
            message_id: 메시지 ID
            previous_content: 이전 내용
            new_content: 새 내용
            edited_by: 편집자
            edit_reason: 편집 사유
        """
        query = """
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
            query,
            message_id,
            previous_content,
            new_content,
            edited_by,
            edit_reason
        )

    @staticmethod
    async def update_message_content(message_id: str, new_content: str) -> None:
        """메시지 내용 업데이트

        Args:
            message_id: 메시지 ID
            new_content: 새 내용
        """
        query = """
        UPDATE messages
        SET content = $1, status = 'edited', updated_at = CURRENT_TIMESTAMP
        WHERE message_id = $2
        """

        await db_manager.execute(query, new_content, message_id)

    @staticmethod
    async def add_message_feedback(
        message_id: str,
        feedback: str,
        comment: Optional[str]
    ) -> None:
        """메시지에 피드백 추가

        Args:
            message_id: 메시지 ID
            feedback: 피드백 ('positive'/'negative')
            comment: 코멘트
        """
        query = """
        UPDATE messages
        SET user_feedback = $1, feedback_comment = $2, updated_at = CURRENT_TIMESTAMP
        WHERE message_id = $3
        RETURNING message_id
        """

        await db_manager.execute(query, feedback, comment, message_id)

    @staticmethod
    async def delete_message(message_id: str) -> None:
        """메시지 삭제

        Args:
            message_id: 메시지 ID
        """
        query = """
        DELETE FROM messages
        WHERE message_id = $1
        """

        await db_manager.execute(query, message_id)

    # ==================== Analytics ====================

    @staticmethod
    async def get_conversation_analytics(
        conversation_id: str,
        period: str = "session"
    ) -> Optional[ConversationAnalytics]:
        """대화 분석 데이터 조회

        Args:
            conversation_id: 대화 ID
            period: 분석 기간

        Returns:
            분석 데이터 또는 None
        """
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

        return ConversationAnalytics(
            conversation_id=row[0],
            analysis_period=row[1],
            period_start=row[2],
            period_end=row[3],
            total_messages=row[4],
            user_messages=row[5],
            assistant_messages=row[6],
            total_tokens_used=row[7],
            prompt_tokens_used=row[8],
            completion_tokens_used=row[9],
            estimated_cost=float(row[10]) if row[10] is not None else 0.0,
            average_response_time_ms=row[11],
            average_message_length=row[12],
            average_quality_score=float(row[13]) if row[13] is not None else None,
            tools_used=row[14] if row[14] else [],
            tool_call_count=row[15],
            positive_feedback_count=row[16],
            negative_feedback_count=row[17],
            messages_edited_count=row[18],
            created_at=row[19],
            metadata=row[20] if row[20] else {}
        )

    @staticmethod
    async def get_user_statistics(user_id: str) -> Dict[str, Any]:
        """사용자 채팅 통계

        Args:
            user_id: 사용자 ID

        Returns:
            사용자 통계
        """
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

        if not row or row[1] is None:
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

    # ==================== Templates ====================

    @staticmethod
    async def create_template(
        template_id: str,
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
    ) -> str:
        """대화 템플릿 생성

        Args:
            template_id: 템플릿 ID
            name: 템플릿 이름
            created_by: 생성자
            description: 설명
            category: 카테고리
            default_model: 기본 모델
            default_system_prompt: 기본 시스템 프롬프트
            default_temperature: 기본 temperature
            default_settings: 기본 설정
            initial_messages: 초기 메시지
            is_public: 공개 여부
            tags: 태그
            metadata: 메타데이터

        Returns:
            생성된 템플릿 ID
        """
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

        return template_id

    @staticmethod
    async def get_template(template_id: str) -> Optional[ConversationTemplate]:
        """템플릿 조회

        Args:
            template_id: 템플릿 ID

        Returns:
            템플릿 데이터 또는 None
        """
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

        return ConversationTemplate(
            template_id=row[0],
            name=row[1],
            description=row[2],
            category=row[3],
            default_model=row[4],
            default_system_prompt=row[5],
            default_temperature=float(row[6]) if row[6] is not None else 0.7,
            default_settings=row[7] if row[7] else {},
            initial_messages=row[8] if row[8] else [],
            is_public=row[9],
            is_active=row[10],
            created_by=row[11],
            usage_count=row[12],
            created_at=row[13],
            updated_at=row[14],
            tags=row[15] if row[15] else [],
            metadata=row[16] if row[16] else {}
        )

    @staticmethod
    async def list_templates(
        category: Optional[str] = None,
        is_public: Optional[bool] = None,
        created_by: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[ConversationTemplate], int]:
        """템플릿 목록 조회

        Args:
            category: 카테고리 필터
            is_public: 공개 여부 필터
            created_by: 생성자 필터
            limit: 최대 결과 수
            offset: 오프셋

        Returns:
            (템플릿 목록, 전체 개수)
        """
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

        templates = [
            ConversationTemplate(
                template_id=row[0],
                name=row[1],
                description=row[2],
                category=row[3],
                default_model=row[4],
                default_system_prompt=row[5],
                default_temperature=float(row[6]) if row[6] is not None else 0.7,
                default_settings=row[7] if row[7] else {},
                initial_messages=row[8] if row[8] else [],
                is_public=row[9],
                is_active=row[10],
                created_by=row[11],
                usage_count=row[12],
                created_at=row[13],
                updated_at=row[14],
                tags=row[15] if row[15] else [],
                metadata=row[16] if row[16] else {}
            )
            for row in rows
        ]

        return templates, total_count

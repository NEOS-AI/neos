-- Chat System Schema
-- Claude 서비스와 같은 AI 채팅 시스템을 위한 데이터베이스 스키마
-- 사용자는 여러 대화(conversation)를 가질 수 있으며, 각 대화는 여러 메시지로 구성됨

-- ============================================================================
-- 1. 대화방 테이블 (Conversations)
-- ============================================================================
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(255) UNIQUE NOT NULL, -- UUID 형식

    -- 소유자 정보
    user_id VARCHAR(255) NOT NULL,

    -- 대화 메타데이터
    title VARCHAR(500), -- 대화 제목 (첫 메시지 기반 자동 생성 또는 사용자 설정)
    summary TEXT, -- 대화 요약

    -- 대화 설정
    model_name VARCHAR(100), -- 'claude-3-opus', 'gpt-4', etc.
    model_version VARCHAR(50),
    system_prompt TEXT, -- 대화에 적용되는 시스템 프롬프트
    temperature FLOAT DEFAULT 0.7,
    max_tokens INTEGER,
    mode VARCHAR(50) DEFAULT 'standard', -- 'standard', 'rag', 'similarity', 'deep_research'

    -- 대화 상태
    status VARCHAR(50) DEFAULT 'active', -- 'active', 'archived', 'deleted'
    is_pinned BOOLEAN DEFAULT FALSE,
    is_shared BOOLEAN DEFAULT FALSE,
    share_token VARCHAR(255) UNIQUE, -- 공유용 토큰

    -- 대화 통계
    message_count INTEGER DEFAULT 0,
    total_tokens_used INTEGER DEFAULT 0,
    total_cost DECIMAL(10, 6) DEFAULT 0.0,

    -- 마지막 활동
    last_message_at TIMESTAMP,
    last_accessed_at TIMESTAMP,

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    archived_at TIMESTAMP,
    deleted_at TIMESTAMP,

    -- 추가 메타데이터
    tags JSONB DEFAULT '[]', -- ['coding', 'research', 'brainstorming']
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- ============================================================================
-- 2. 메시지 타입 ENUM
-- ============================================================================
DO $$ BEGIN
    CREATE TYPE message_role AS ENUM (
        'user',        -- 사용자 메시지
        'assistant',   -- AI 어시스턴트 응답
        'system',      -- 시스템 메시지 (알림, 상태 변경 등)
        'function',    -- 함수/도구 호출 결과
        'tool'         -- 도구 실행 메시지
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE message_status AS ENUM (
        'pending',     -- 생성 중
        'streaming',   -- 스트리밍 중
        'completed',   -- 완료
        'failed',      -- 실패
        'cancelled',   -- 취소됨
        'edited'       -- 편집됨
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- ============================================================================
-- 3. 메시지 테이블 (Messages)
-- ============================================================================
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(255) UNIQUE NOT NULL, -- UUID 형식
    conversation_id VARCHAR(255) NOT NULL,

    -- 메시지 기본 정보
    role message_role NOT NULL,
    content TEXT NOT NULL, -- 메시지 본문
    content_type VARCHAR(50) DEFAULT 'text', -- 'text', 'markdown', 'code', 'image'

    -- 메시지 순서 및 계층
    sequence_number INTEGER, -- 대화 내 순서 (트리거로 자동 설정)
    parent_message_id VARCHAR(255), -- 브랜치/편집 추적용

    -- 메시지 상태
    status message_status DEFAULT 'completed',
    error_message TEXT,

    -- AI 응답 메타데이터 (role='assistant'인 경우)
    model_name VARCHAR(100),
    model_version VARCHAR(50),
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    finish_reason VARCHAR(50), -- 'stop', 'length', 'content_filter', 'tool_calls'

    -- 도구 사용 정보
    tool_calls JSONB DEFAULT '[]', -- 호출된 도구들의 정보
    tool_results JSONB DEFAULT '[]', -- 도구 실행 결과

    -- 첨부 파일 및 미디어
    attachments JSONB DEFAULT '[]', -- [{type: 'image', url: '...', name: '...'}]

    -- 피드백 및 품질
    user_feedback VARCHAR(20), -- 'positive', 'negative', 'neutral'
    feedback_comment TEXT,
    quality_score FLOAT, -- 자동 평가 점수

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    streamed_at TIMESTAMP, -- 스트리밍 시작 시간
    completed_at TIMESTAMP, -- 완료 시간

    -- 메타데이터
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_message_id) REFERENCES messages(message_id) ON DELETE SET NULL
);

-- ============================================================================
-- 4. 메시지 편집 이력 테이블
-- ============================================================================
CREATE TABLE IF NOT EXISTS message_edits (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(255) NOT NULL,

    -- 편집 정보
    edit_version INTEGER NOT NULL, -- 편집 버전 번호
    previous_content TEXT NOT NULL,
    new_content TEXT NOT NULL,

    -- 편집자
    edited_by VARCHAR(255) NOT NULL, -- user_id
    edit_reason VARCHAR(100), -- 'correction', 'clarification', 'regenerate'

    -- 타임스탬프
    edited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- 메타데이터
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (message_id) REFERENCES messages(message_id) ON DELETE CASCADE
);

-- ============================================================================
-- 5. 대화 참여자 테이블 (Conversation Participants)
-- ============================================================================
CREATE TABLE IF NOT EXISTS conversation_participants (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,

    -- 참여자 역할
    role VARCHAR(50) DEFAULT 'member', -- 'owner', 'admin', 'member', 'viewer'

    -- 권한
    can_read BOOLEAN DEFAULT TRUE,
    can_write BOOLEAN DEFAULT TRUE,
    can_edit BOOLEAN DEFAULT FALSE,
    can_delete BOOLEAN DEFAULT FALSE,
    can_share BOOLEAN DEFAULT FALSE,

    -- 참여 상태
    is_active BOOLEAN DEFAULT TRUE,
    last_read_message_id VARCHAR(255), -- 마지막으로 읽은 메시지
    unread_count INTEGER DEFAULT 0,

    -- 타임스탬프
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    left_at TIMESTAMP,
    last_accessed_at TIMESTAMP,

    -- 메타데이터
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (last_read_message_id) REFERENCES messages(message_id) ON DELETE SET NULL,

    UNIQUE(conversation_id, user_id)
);

-- ============================================================================
-- 6. 대화 브랜치 테이블 (Conversation Branches)
-- ============================================================================
-- 사용자가 특정 메시지에서 다른 응답을 시도할 때 브랜치 생성
CREATE TABLE IF NOT EXISTS conversation_branches (
    id SERIAL PRIMARY KEY,
    branch_id VARCHAR(255) UNIQUE NOT NULL,
    conversation_id VARCHAR(255) NOT NULL,

    -- 브랜치 정보
    branch_name VARCHAR(255),
    branch_point_message_id VARCHAR(255) NOT NULL, -- 어느 메시지에서 분기했는지
    parent_branch_id VARCHAR(255), -- 부모 브랜치

    -- 브랜치 상태
    is_active BOOLEAN DEFAULT TRUE,
    is_merged BOOLEAN DEFAULT FALSE,

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    merged_at TIMESTAMP,

    -- 메타데이터
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    FOREIGN KEY (branch_point_message_id) REFERENCES messages(message_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_branch_id) REFERENCES conversation_branches(branch_id) ON DELETE SET NULL
);

-- ============================================================================
-- 7. 채팅 세션 분석 테이블
-- ============================================================================
CREATE TABLE IF NOT EXISTS chat_analytics (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(255) NOT NULL,

    -- 시간 기반 메트릭
    analysis_period VARCHAR(50) NOT NULL, -- 'session', 'daily', 'weekly'
    period_start TIMESTAMP NOT NULL,
    period_end TIMESTAMP NOT NULL,

    -- 사용 통계
    total_messages INTEGER DEFAULT 0,
    user_messages INTEGER DEFAULT 0,
    assistant_messages INTEGER DEFAULT 0,

    -- 토큰 사용량
    total_tokens_used INTEGER DEFAULT 0,
    prompt_tokens_used INTEGER DEFAULT 0,
    completion_tokens_used INTEGER DEFAULT 0,
    estimated_cost DECIMAL(10, 6) DEFAULT 0.0,

    -- 품질 메트릭
    average_response_time_ms INTEGER,
    average_message_length INTEGER,
    average_quality_score FLOAT,

    -- 도구 사용
    tools_used JSONB DEFAULT '[]', -- [{'tool': 'web_search', 'count': 5}]
    tool_call_count INTEGER DEFAULT 0,

    -- 사용자 활동
    positive_feedback_count INTEGER DEFAULT 0,
    negative_feedback_count INTEGER DEFAULT 0,
    messages_edited_count INTEGER DEFAULT 0,

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 메타데이터
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

-- ============================================================================
-- 8. 대화 템플릿 테이블
-- ============================================================================
-- 재사용 가능한 대화 템플릿 (예: 코딩 도우미, 리서치 도우미 등)
CREATE TABLE IF NOT EXISTS conversation_templates (
    id SERIAL PRIMARY KEY,
    template_id VARCHAR(255) UNIQUE NOT NULL,

    -- 템플릿 정보
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100), -- 'coding', 'research', 'writing', 'general'

    -- 템플릿 설정
    default_model VARCHAR(100),
    default_system_prompt TEXT,
    default_temperature FLOAT DEFAULT 0.7,
    default_settings JSONB DEFAULT '{}',

    -- 초기 메시지들
    initial_messages JSONB DEFAULT '[]', -- 템플릿으로 시작할 때의 초기 대화

    -- 템플릿 상태
    is_public BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_by VARCHAR(255) NOT NULL,

    -- 사용 통계
    usage_count INTEGER DEFAULT 0,

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 메타데이터
    tags JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (created_by) REFERENCES users(user_id) ON DELETE CASCADE
);

-- ============================================================================
-- 인덱스 생성
-- ============================================================================

-- conversations 테이블 인덱스
CREATE INDEX idx_conversations_user_id ON conversations(user_id);
CREATE INDEX idx_conversations_status ON conversations(status);
CREATE INDEX idx_conversations_created_at ON conversations(created_at DESC);
CREATE INDEX idx_conversations_last_message_at ON conversations(last_message_at DESC);
CREATE INDEX idx_conversations_pinned ON conversations(is_pinned, user_id) WHERE is_pinned = TRUE;
CREATE INDEX idx_conversations_shared ON conversations(is_shared) WHERE is_shared = TRUE;
CREATE INDEX idx_conversations_share_token ON conversations(share_token) WHERE share_token IS NOT NULL;

-- messages 테이블 인덱스
CREATE INDEX idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX idx_messages_sequence ON messages(conversation_id, sequence_number);
CREATE INDEX idx_messages_created_at ON messages(created_at DESC);
CREATE INDEX idx_messages_role ON messages(role);
CREATE INDEX idx_messages_status ON messages(status);
CREATE INDEX idx_messages_parent ON messages(parent_message_id);

-- 전문 검색 인덱스 (pg_trgm)
CREATE INDEX idx_messages_content_trgm ON messages USING gin (content gin_trgm_ops);
CREATE INDEX idx_conversations_title_trgm ON conversations USING gin (title gin_trgm_ops);

-- message_edits 테이블 인덱스
CREATE INDEX idx_message_edits_message_id ON message_edits(message_id);
CREATE INDEX idx_message_edits_edited_at ON message_edits(edited_at DESC);

-- conversation_participants 테이블 인덱스
CREATE INDEX idx_participants_conversation ON conversation_participants(conversation_id);
CREATE INDEX idx_participants_user ON conversation_participants(user_id);
CREATE INDEX idx_participants_active ON conversation_participants(is_active) WHERE is_active = TRUE;

-- conversation_branches 테이블 인덱스
CREATE INDEX idx_branches_conversation ON conversation_branches(conversation_id);
CREATE INDEX idx_branches_branch_point ON conversation_branches(branch_point_message_id);
CREATE INDEX idx_branches_active ON conversation_branches(is_active) WHERE is_active = TRUE;

-- chat_analytics 테이블 인덱스
CREATE INDEX idx_analytics_conversation ON chat_analytics(conversation_id);
CREATE INDEX idx_analytics_period ON chat_analytics(analysis_period, period_start);

-- conversation_templates 테이블 인덱스
CREATE INDEX idx_templates_category ON conversation_templates(category);
CREATE INDEX idx_templates_created_by ON conversation_templates(created_by);
CREATE INDEX idx_templates_public ON conversation_templates(is_public) WHERE is_public = TRUE;

-- ============================================================================
-- 트리거 및 함수
-- ============================================================================

-- conversations updated_at 자동 업데이트
CREATE OR REPLACE FUNCTION update_conversation_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_conversation_updated_at
    BEFORE UPDATE ON conversations
    FOR EACH ROW
    EXECUTE FUNCTION update_conversation_updated_at();

-- messages updated_at 자동 업데이트
CREATE OR REPLACE FUNCTION update_message_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_message_updated_at
    BEFORE UPDATE ON messages
    FOR EACH ROW
    EXECUTE FUNCTION update_message_updated_at();

-- 새 메시지 추가 시 대화 통계 업데이트
CREATE OR REPLACE FUNCTION update_conversation_on_message()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE conversations
        SET
            message_count = message_count + 1,
            last_message_at = NEW.created_at,
            total_tokens_used = total_tokens_used + COALESCE(NEW.total_tokens, 0),
            updated_at = CURRENT_TIMESTAMP
        WHERE conversation_id = NEW.conversation_id;

        -- 참여자의 읽지 않은 메시지 수 증가 (메시지 작성자 제외)
        UPDATE conversation_participants
        SET unread_count = unread_count + 1
        WHERE conversation_id = NEW.conversation_id
          AND is_active = TRUE;

    ELSIF TG_OP = 'DELETE' THEN
        UPDATE conversations
        SET
            message_count = GREATEST(message_count - 1, 0),
            total_tokens_used = GREATEST(total_tokens_used - COALESCE(OLD.total_tokens, 0), 0),
            updated_at = CURRENT_TIMESTAMP
        WHERE conversation_id = OLD.conversation_id;
    END IF;

    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_conversation_on_message
    AFTER INSERT OR DELETE ON messages
    FOR EACH ROW
    EXECUTE FUNCTION update_conversation_on_message();

-- 메시지 시퀀스 번호 자동 생성
CREATE OR REPLACE FUNCTION set_message_sequence_number()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.sequence_number IS NULL THEN
        NEW.sequence_number = (
            SELECT COALESCE(MAX(sequence_number), 0) + 1
            FROM messages
            WHERE conversation_id = NEW.conversation_id
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_set_message_sequence_number
    BEFORE INSERT ON messages
    FOR EACH ROW
    EXECUTE FUNCTION set_message_sequence_number();

-- 대화 제목 자동 생성 (첫 메시지 기반)
CREATE OR REPLACE FUNCTION auto_generate_conversation_title()
RETURNS TRIGGER AS $$
DECLARE
    conv_title TEXT;
BEGIN
    -- 대화의 첫 번째 사용자 메시지인 경우
    IF NEW.role = 'user' AND NEW.sequence_number = 1 THEN
        -- 제목이 비어있으면 첫 50자를 제목으로 설정
        SELECT title INTO conv_title
        FROM conversations
        WHERE conversation_id = NEW.conversation_id;

        IF conv_title IS NULL OR conv_title = '' THEN
            UPDATE conversations
            SET title = LEFT(NEW.content, 50)
            WHERE conversation_id = NEW.conversation_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_auto_generate_conversation_title
    AFTER INSERT ON messages
    FOR EACH ROW
    EXECUTE FUNCTION auto_generate_conversation_title();

-- 템플릿 사용 카운트 증가
CREATE OR REPLACE FUNCTION increment_template_usage()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.metadata ? 'template_id' THEN
        UPDATE conversation_templates
        SET usage_count = usage_count + 1
        WHERE template_id = NEW.metadata->>'template_id';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_increment_template_usage
    AFTER INSERT ON conversations
    FOR EACH ROW
    EXECUTE FUNCTION increment_template_usage();

-- ============================================================================
-- 유틸리티 함수
-- ============================================================================

-- 대화 생성 함수
CREATE OR REPLACE FUNCTION create_conversation(
    p_user_id VARCHAR(255),
    p_conversation_id VARCHAR(255),
    p_model_name VARCHAR(100) DEFAULT 'claude-opus-4-5-20251101',
    p_system_prompt TEXT DEFAULT NULL,
    p_template_id VARCHAR(255) DEFAULT NULL,
    p_mode VARCHAR(50) DEFAULT 'standard'
) RETURNS VARCHAR(255) AS $$
DECLARE
    v_conversation_id VARCHAR(255);
    v_template_settings JSONB;
BEGIN
    -- 템플릿이 지정된 경우 템플릿 설정 가져오기
    IF p_template_id IS NOT NULL THEN
        SELECT
            jsonb_build_object(
                'model', default_model,
                'system_prompt', default_system_prompt,
                'temperature', default_temperature,
                'settings', default_settings
            )
        INTO v_template_settings
        FROM conversation_templates
        WHERE template_id = p_template_id AND is_active = TRUE;
    END IF;

    -- 대화 생성
    INSERT INTO conversations (
        conversation_id,
        user_id,
        model_name,
        system_prompt,
        temperature,
        mode,
        metadata
    ) VALUES (
        p_conversation_id,
        p_user_id,
        COALESCE(v_template_settings->>'model', p_model_name),
        COALESCE(v_template_settings->>'system_prompt', p_system_prompt),
        COALESCE((v_template_settings->>'temperature')::FLOAT, 0.7),
        p_mode,
        CASE
            WHEN p_template_id IS NOT NULL
            THEN jsonb_build_object('template_id', p_template_id)
            ELSE '{}'::jsonb
        END
    )
    RETURNING conversation_id INTO v_conversation_id;

    -- 참여자 추가 (소유자)
    INSERT INTO conversation_participants (
        conversation_id,
        user_id,
        role,
        can_read,
        can_write,
        can_edit,
        can_delete,
        can_share
    ) VALUES (
        v_conversation_id,
        p_user_id,
        'owner',
        TRUE,
        TRUE,
        TRUE,
        TRUE,
        TRUE
    );

    RETURN v_conversation_id;
END;
$$ LANGUAGE plpgsql;

-- 메시지 추가 함수
CREATE OR REPLACE FUNCTION add_message(
    p_conversation_id VARCHAR(255),
    p_message_id VARCHAR(255),
    p_role message_role,
    p_content TEXT,
    p_model_name VARCHAR(100) DEFAULT NULL,
    p_total_tokens INTEGER DEFAULT NULL,
    p_tool_calls JSONB DEFAULT '[]'
) RETURNS VARCHAR(255) AS $$
DECLARE
    v_message_id VARCHAR(255);
BEGIN
    INSERT INTO messages (
        message_id,
        conversation_id,
        role,
        content,
        model_name,
        total_tokens,
        tool_calls,
        status
    ) VALUES (
        p_message_id,
        p_conversation_id,
        p_role,
        p_content,
        p_model_name,
        p_total_tokens,
        p_tool_calls,
        'completed'
    )
    RETURNING message_id INTO v_message_id;

    RETURN v_message_id;
END;
$$ LANGUAGE plpgsql;

-- 대화 검색 함수 (사용자의 모든 활성 대화 조회)
CREATE OR REPLACE FUNCTION get_user_conversations(
    p_user_id VARCHAR(255),
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
)
RETURNS TABLE (
    conversation_id VARCHAR(255),
    title VARCHAR(500),
    model_name VARCHAR(100),
    message_count INTEGER,
    last_message_at TIMESTAMP,
    is_pinned BOOLEAN,
    created_at TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.conversation_id,
        c.title,
        c.model_name,
        c.message_count,
        c.last_message_at,
        c.is_pinned,
        c.created_at
    FROM conversations c
    WHERE c.user_id = p_user_id
      AND c.status = 'active'
      AND c.deleted_at IS NULL
    ORDER BY
        c.is_pinned DESC,
        c.last_message_at DESC NULLS LAST,
        c.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;

-- 대화 메시지 조회 함수
CREATE OR REPLACE FUNCTION get_conversation_messages(
    p_conversation_id VARCHAR(255),
    p_limit INTEGER DEFAULT 100,
    p_before_sequence INTEGER DEFAULT NULL
)
RETURNS TABLE (
    message_id VARCHAR(255),
    role message_role,
    content TEXT,
    sequence_number INTEGER,
    model_name VARCHAR(100),
    total_tokens INTEGER,
    tool_calls JSONB,
    created_at TIMESTAMP,
    status message_status
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.message_id,
        m.role,
        m.content,
        m.sequence_number,
        m.model_name,
        m.total_tokens,
        m.tool_calls,
        m.created_at,
        m.status
    FROM messages m
    WHERE m.conversation_id = p_conversation_id
      AND (p_before_sequence IS NULL OR m.sequence_number < p_before_sequence)
    ORDER BY m.sequence_number DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 뷰
-- ============================================================================

-- 대화 요약 뷰 (통계 포함)
CREATE OR REPLACE VIEW conversation_summary AS
SELECT
    c.conversation_id,
    c.user_id,
    c.title,
    c.model_name,
    c.status,
    c.is_pinned,
    c.message_count,
    c.total_tokens_used,
    c.total_cost,
    c.last_message_at,
    c.created_at,
    COUNT(DISTINCT cp.user_id) FILTER (WHERE cp.is_active = TRUE) as participant_count,
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
LEFT JOIN conversation_participants cp ON c.conversation_id = cp.conversation_id
WHERE c.deleted_at IS NULL
GROUP BY c.conversation_id, c.user_id, c.title, c.model_name, c.status,
         c.is_pinned, c.message_count, c.total_tokens_used, c.total_cost,
         c.last_message_at, c.created_at;

-- 사용자별 채팅 통계 뷰
CREATE OR REPLACE VIEW user_chat_statistics AS
SELECT
    c.user_id,
    COUNT(DISTINCT c.conversation_id) as total_conversations,
    COUNT(DISTINCT c.conversation_id) FILTER (WHERE c.status = 'active') as active_conversations,
    COUNT(DISTINCT c.conversation_id) FILTER (WHERE c.is_pinned = TRUE) as pinned_conversations,
    SUM(c.message_count) as total_messages,
    SUM(c.total_tokens_used) as total_tokens,
    SUM(c.total_cost) as total_cost,
    MAX(c.last_message_at) as last_activity_at,
    MIN(c.created_at) as first_conversation_at
FROM conversations c
WHERE c.deleted_at IS NULL
GROUP BY c.user_id;

-- ============================================================================
-- 코멘트 추가
-- ============================================================================
COMMENT ON TABLE conversations IS '사용자의 채팅 대화방을 관리하는 테이블';
COMMENT ON TABLE messages IS '대화방 내의 모든 메시지 (사용자, AI, 시스템)';
COMMENT ON TABLE message_edits IS '메시지 편집 이력 추적';
COMMENT ON TABLE conversation_participants IS '대화방 참여자 및 권한 관리';
COMMENT ON TABLE conversation_branches IS '대화 분기 관리 (alternative responses)';
COMMENT ON TABLE chat_analytics IS '대화별 사용 통계 및 분석';
COMMENT ON TABLE conversation_templates IS '재사용 가능한 대화 템플릿';

-- ============================================================================
-- 9. Vote 테이블 (메시지 투표)
-- ============================================================================
-- 웹 프론트엔드에서 메시지에 대한 사용자 피드백을 추적
CREATE TABLE IF NOT EXISTS "Vote_v2" (
    chat_id VARCHAR(255) NOT NULL,
    message_id VARCHAR(255) NOT NULL,
    is_upvoted BOOLEAN NOT NULL,

    PRIMARY KEY (chat_id, message_id),
    FOREIGN KEY (chat_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(message_id) ON DELETE CASCADE
);

CREATE INDEX idx_vote_v2_chat_id ON "Vote_v2"(chat_id);
CREATE INDEX idx_vote_v2_message_id ON "Vote_v2"(message_id);

COMMENT ON TABLE "Vote_v2" IS '메시지에 대한 사용자 피드백 (upvote/downvote)';

-- ============================================================================
-- 10. Document 테이블 (Artifacts - 코드, 문서, 스프레드시트 등)
-- ============================================================================
-- 웹 프론트엔드의 Artifact 시스템에서 생성되는 문서들
CREATE TABLE IF NOT EXISTS "Document" (
    id UUID NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    title TEXT NOT NULL,
    content TEXT,
    kind VARCHAR(20) NOT NULL DEFAULT 'text',
    user_id VARCHAR(255) NOT NULL,

    PRIMARY KEY (id, created_at),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,

    -- kind 값 제한
    CONSTRAINT check_document_kind CHECK (kind IN ('text', 'code', 'image', 'sheet'))
);

CREATE INDEX idx_document_user_id ON "Document"(user_id);
CREATE INDEX idx_document_id ON "Document"(id);
CREATE INDEX idx_document_created_at ON "Document"(created_at DESC);

COMMENT ON TABLE "Document" IS 'Artifact 문서 (버전 관리 지원 - id와 created_at로 버전 구분)';

-- ============================================================================
-- 11. Suggestion 테이블 (문서 제안/편집 제안)
-- ============================================================================
-- Document에 대한 AI 생성 편집 제안
CREATE TABLE IF NOT EXISTS "Suggestion" (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL,
    document_created_at TIMESTAMP NOT NULL,
    original_text TEXT NOT NULL,
    suggested_text TEXT NOT NULL,
    description TEXT,
    is_resolved BOOLEAN NOT NULL DEFAULT FALSE,
    user_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (document_id, document_created_at)
        REFERENCES "Document"(id, created_at) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX idx_suggestion_document ON "Suggestion"(document_id, document_created_at);
CREATE INDEX idx_suggestion_user ON "Suggestion"(user_id);
CREATE INDEX idx_suggestion_resolved ON "Suggestion"(is_resolved) WHERE is_resolved = FALSE;

COMMENT ON TABLE "Suggestion" IS '문서에 대한 AI 생성 편집 제안';

-- ============================================================================
-- 12. messages 테이블에 parts 컬럼 추가 (Vercel AI SDK 호환)
-- ============================================================================
-- Vercel AI SDK의 parts 구조를 지원하기 위한 컬럼 추가
-- parts는 content의 구조화된 버전으로, tool-call, tool-result 등을 포함
ALTER TABLE messages
ADD COLUMN IF NOT EXISTS parts JSONB;

COMMENT ON COLUMN messages.parts IS 'Vercel AI SDK parts 구조 (content의 구조화된 버전)';

-- parts 구조 예시:
-- [
--   {"type": "text", "text": "Hello"},
--   {"type": "tool-call", "toolCallId": "...", "toolName": "...", "args": {...}},
--   {"type": "tool-result", "toolCallId": "...", "toolName": "...", "result": {...}}
-- ]

-- ============================================================================
-- 13. users 테이블에 NextAuth 호환 필드 추가
-- ============================================================================
-- NextAuth에서 사용하는 name, image 필드 추가 (이미 있으면 스킵)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'name'
    ) THEN
        ALTER TABLE users ADD COLUMN name VARCHAR(255);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'image'
    ) THEN
        ALTER TABLE users ADD COLUMN image VARCHAR(1000);
    END IF;
END $$;

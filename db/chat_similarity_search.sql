-- Chat Similarity Search Extension
-- 메시지 임베딩 및 유사도 검색 기능

-- ============================================================================
-- 1. 메시지 임베딩 테이블
-- ============================================================================
CREATE TABLE IF NOT EXISTS message_embeddings (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(255) UNIQUE NOT NULL,
    conversation_id VARCHAR(255) NOT NULL,

    -- 임베딩 벡터
    embedding vector(3072), -- Gemini Embedding 2 Flash
    embedding_model VARCHAR(100) DEFAULT 'gemini-embedding-2-flash',

    -- 메시지 메타데이터 (비정규화 - 빠른 검색을 위해)
    content TEXT NOT NULL,
    role VARCHAR(50) NOT NULL,
    sequence_number INTEGER,

    -- 사용자 정보 (비정규화)
    user_id VARCHAR(255),

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 메타데이터
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (message_id) REFERENCES messages(message_id) ON DELETE CASCADE,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

-- ============================================================================
-- 2. 대화 임베딩 요약 테이블 (선택적)
-- ============================================================================
CREATE TABLE IF NOT EXISTS conversation_embeddings (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(255) UNIQUE NOT NULL,

    -- 대화 요약 임베딩
    summary_embedding vector(3072),
    summary_text TEXT,

    -- 통계
    message_count INTEGER DEFAULT 0,
    last_updated_message_id VARCHAR(255),

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

-- ============================================================================
-- 3. 유사 메시지 캐시 테이블 (성능 최적화)
-- ============================================================================
CREATE TABLE IF NOT EXISTS similar_messages_cache (
    id SERIAL PRIMARY KEY,
    query_message_id VARCHAR(255) NOT NULL,
    similar_message_id VARCHAR(255) NOT NULL,

    -- 유사도 점수
    similarity_score FLOAT NOT NULL,
    rank INTEGER NOT NULL,

    -- 캐시 메타데이터
    search_params JSONB DEFAULT '{}', -- limit, threshold 등

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,

    FOREIGN KEY (query_message_id) REFERENCES messages(message_id) ON DELETE CASCADE,
    FOREIGN KEY (similar_message_id) REFERENCES messages(message_id) ON DELETE CASCADE,

    UNIQUE(query_message_id, similar_message_id, rank)
);

-- ============================================================================
-- 인덱스 생성
-- ============================================================================

-- 벡터 유사도 검색 인덱스 (HNSW - Hierarchical Navigable Small World)
--
-- ⚠️ halfvec 캐스팅이 필수다 (2026-08-25, SCHEMA1). pgvector 는 hnsw 에
-- 2000 차원까지만 허용하는데 embedding 은 vector(3072) 다. 캐스팅 없이 쓰면
-- 이 구문이 `column cannot have more than 2000 dimensions` 로 죽고, psql 은
-- ON_ERROR_STOP 으로 멈추므로 **이 파일의 나머지 246줄이 통째로 미적용**된다
-- (함수 6개·뷰 2개·인덱스 10개). 저장은 vector(3072), 인덱싱만 halfvec(3072).
-- 같은 방식이 db/migrations/003 에도 있다.
CREATE INDEX IF NOT EXISTS idx_message_embeddings_vector
ON message_embeddings
USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- IVFFlat 인덱스 (대안 - 데이터가 많을 때)
-- CREATE INDEX IF NOT EXISTS idx_message_embeddings_ivfflat
-- ON message_embeddings
-- USING ivfflat (embedding vector_cosine_ops)
-- WITH (lists = 100);

-- 기본 인덱스
CREATE INDEX IF NOT EXISTS idx_message_embeddings_message_id ON message_embeddings(message_id);
CREATE INDEX IF NOT EXISTS idx_message_embeddings_conversation_id ON message_embeddings(conversation_id);
CREATE INDEX IF NOT EXISTS idx_message_embeddings_user_id ON message_embeddings(user_id);
CREATE INDEX IF NOT EXISTS idx_message_embeddings_role ON message_embeddings(role);
CREATE INDEX IF NOT EXISTS idx_message_embeddings_created_at ON message_embeddings(created_at DESC);

-- conversation_embeddings 인덱스
-- 위와 같은 이유로 halfvec 캐스팅 (summary_embedding 도 vector(3072) 다)
CREATE INDEX IF NOT EXISTS idx_conversation_embeddings_vector
ON conversation_embeddings
USING hnsw ((summary_embedding::halfvec(3072)) halfvec_cosine_ops)
WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_conversation_embeddings_updated ON conversation_embeddings(updated_at DESC);

-- similar_messages_cache 인덱스
CREATE INDEX IF NOT EXISTS idx_similar_cache_query ON similar_messages_cache(query_message_id);
CREATE INDEX IF NOT EXISTS idx_similar_cache_expires ON similar_messages_cache(expires_at);

-- ============================================================================
-- 트리거 및 함수
-- ============================================================================

-- message_embeddings updated_at 자동 업데이트
CREATE OR REPLACE FUNCTION update_message_embeddings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_message_embeddings_updated_at
    BEFORE UPDATE ON message_embeddings
    FOR EACH ROW
    EXECUTE FUNCTION update_message_embeddings_updated_at();

-- 만료된 캐시 자동 삭제 함수
CREATE OR REPLACE FUNCTION cleanup_expired_similar_cache()
RETURNS void AS $$
BEGIN
    DELETE FROM similar_messages_cache
    WHERE expires_at < CURRENT_TIMESTAMP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 유틸리티 함수
-- ============================================================================

-- 유사 메시지 검색 함수
CREATE OR REPLACE FUNCTION find_similar_messages(
    p_embedding vector(3072),
    p_user_id VARCHAR(255) DEFAULT NULL,
    p_conversation_id VARCHAR(255) DEFAULT NULL,
    p_limit INTEGER DEFAULT 10,
    p_similarity_threshold FLOAT DEFAULT 0.7
)
RETURNS TABLE (
    message_id VARCHAR(255),
    conversation_id VARCHAR(255),
    content TEXT,
    role VARCHAR(50),
    similarity_score FLOAT,
    created_at TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        me.message_id,
        me.conversation_id,
        me.content,
        me.role,
        1 - (me.embedding::halfvec(3072) <=> p_embedding::halfvec(3072)) as similarity_score,
        me.created_at
    FROM message_embeddings me
    WHERE (p_user_id IS NULL OR me.user_id = p_user_id)
      AND (p_conversation_id IS NULL OR me.conversation_id = p_conversation_id)
      AND (1 - (me.embedding::halfvec(3072) <=> p_embedding::halfvec(3072))) >= p_similarity_threshold
    ORDER BY me.embedding::halfvec(3072) <=> p_embedding::halfvec(3072)
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- 대화 내 유사 메시지 검색
CREATE OR REPLACE FUNCTION find_similar_messages_in_conversation(
    p_conversation_id VARCHAR(255),
    p_query_text TEXT,
    p_query_embedding vector(3072),
    p_limit INTEGER DEFAULT 5,
    p_exclude_message_id VARCHAR(255) DEFAULT NULL
)
RETURNS TABLE (
    message_id VARCHAR(255),
    content TEXT,
    role VARCHAR(50),
    sequence_number INTEGER,
    similarity_score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        me.message_id,
        me.content,
        me.role,
        me.sequence_number,
        1 - (me.embedding::halfvec(3072) <=> p_query_embedding::halfvec(3072)) as similarity_score
    FROM message_embeddings me
    WHERE me.conversation_id = p_conversation_id
      AND (p_exclude_message_id IS NULL OR me.message_id != p_exclude_message_id)
    ORDER BY me.embedding::halfvec(3072) <=> p_query_embedding::halfvec(3072)
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- 사용자의 모든 대화에서 유사 메시지 검색
CREATE OR REPLACE FUNCTION find_similar_messages_across_conversations(
    p_user_id VARCHAR(255),
    p_query_embedding vector(3072),
    p_limit INTEGER DEFAULT 10,
    p_similarity_threshold FLOAT DEFAULT 0.75
)
RETURNS TABLE (
    message_id VARCHAR(255),
    conversation_id VARCHAR(255),
    conversation_title VARCHAR(500),
    content TEXT,
    role VARCHAR(50),
    similarity_score FLOAT,
    created_at TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        me.message_id,
        me.conversation_id,
        c.title,
        me.content,
        me.role,
        1 - (me.embedding::halfvec(3072) <=> p_query_embedding::halfvec(3072)) as similarity_score,
        me.created_at
    FROM message_embeddings me
    JOIN conversations c ON me.conversation_id = c.conversation_id
    WHERE me.user_id = p_user_id
      AND c.deleted_at IS NULL
      AND (1 - (me.embedding::halfvec(3072) <=> p_query_embedding::halfvec(3072))) >= p_similarity_threshold
    ORDER BY me.embedding::halfvec(3072) <=> p_query_embedding::halfvec(3072)
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- 하이브리드 검색 (텍스트 + 벡터)
CREATE OR REPLACE FUNCTION hybrid_search_messages(
    p_user_id VARCHAR(255),
    p_text_query TEXT,
    p_vector_query vector(3072),
    p_limit INTEGER DEFAULT 10,
    p_text_weight FLOAT DEFAULT 0.3,
    p_vector_weight FLOAT DEFAULT 0.7
)
RETURNS TABLE (
    message_id VARCHAR(255),
    conversation_id VARCHAR(255),
    content TEXT,
    role VARCHAR(50),
    text_score FLOAT,
    vector_score FLOAT,
    combined_score FLOAT,
    created_at TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        me.message_id,
        me.conversation_id,
        me.content,
        me.role,
        ts_rank(to_tsvector('english', me.content), plainto_tsquery('english', p_text_query)) as text_score,
        (1 - (me.embedding::halfvec(3072) <=> p_vector_query::halfvec(3072))) as vector_score,
        (
            p_text_weight * ts_rank(to_tsvector('english', me.content), plainto_tsquery('english', p_text_query)) +
            p_vector_weight * (1 - (me.embedding::halfvec(3072) <=> p_vector_query::halfvec(3072)))
        ) as combined_score,
        me.created_at
    FROM message_embeddings me
    WHERE me.user_id = p_user_id
      AND (
          to_tsvector('english', me.content) @@ plainto_tsquery('english', p_text_query)
          OR (1 - (me.embedding::halfvec(3072) <=> p_vector_query::halfvec(3072))) >= 0.5
      )
    ORDER BY combined_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 뷰
-- ============================================================================

-- 메시지 임베딩 통계 뷰
CREATE OR REPLACE VIEW message_embedding_stats AS
SELECT
    COUNT(*) as total_embeddings,
    COUNT(DISTINCT conversation_id) as conversations_with_embeddings,
    COUNT(DISTINCT user_id) as users_with_embeddings,
    AVG(array_length(embedding::real[], 1)) as avg_dimension,
    MIN(created_at) as first_embedding_at,
    MAX(created_at) as last_embedding_at
FROM message_embeddings;

-- 사용자별 임베딩 통계
CREATE OR REPLACE VIEW user_embedding_stats AS
SELECT
    user_id,
    COUNT(*) as total_embeddings,
    COUNT(DISTINCT conversation_id) as conversations_count,
    MIN(created_at) as first_embedding_at,
    MAX(created_at) as last_embedding_at
FROM message_embeddings
GROUP BY user_id;

-- ============================================================================
-- 초기 설정 및 유지보수
-- ============================================================================

-- 만료된 캐시 정리 (크론 작업으로 주기적 실행 권장)
-- SELECT cleanup_expired_similar_cache();

-- ============================================================================
-- 코멘트 추가
-- ============================================================================
COMMENT ON TABLE message_embeddings IS '메시지 임베딩 벡터 저장 및 유사도 검색';
COMMENT ON TABLE conversation_embeddings IS '대화 요약 임베딩 (선택적)';
COMMENT ON TABLE similar_messages_cache IS '유사 메시지 검색 결과 캐시';

COMMENT ON FUNCTION find_similar_messages IS '임베딩 기반 유사 메시지 검색';
COMMENT ON FUNCTION find_similar_messages_in_conversation IS '특정 대화 내 유사 메시지 검색';
COMMENT ON FUNCTION find_similar_messages_across_conversations IS '사용자의 모든 대화에서 유사 메시지 검색';
COMMENT ON FUNCTION hybrid_search_messages IS '텍스트 + 벡터 하이브리드 검색';

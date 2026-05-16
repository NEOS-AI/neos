-- ============================================================================
-- 마이그레이션: 스마트 캐시 테이블 생성
-- 버전: 003
-- 설명: pgvector 기반 의미론적 캐싱과 동적 TTL을 위한 테이블 생성
-- ============================================================================

-- pgvector 확장이 없으면 생성 (이미 있으면 무시)
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- 1. query_cache 테이블 - 스마트 캐시 엔트리
-- ============================================================================

CREATE TABLE IF NOT EXISTS query_cache (
    id BIGSERIAL PRIMARY KEY,

    -- 쿼리 정보
    query_text TEXT NOT NULL,
    query_hash VARCHAR(64) NOT NULL,
    query_vector vector(3072),  -- Gemini Embedding 2 차원

    -- 분류 정보 (동적 TTL 계산에 사용)
    query_intent VARCHAR(50) NOT NULL,
    complexity_score FLOAT DEFAULT 0.0,

    -- 캐시된 응답
    response_data JSONB NOT NULL,
    response_quality_score FLOAT DEFAULT 0.0,

    -- TTL 관리
    ttl_seconds INTEGER NOT NULL,
    expires_at TIMESTAMP NOT NULL,

    -- 사용 통계
    hit_count INTEGER DEFAULT 0,
    last_accessed_at TIMESTAMP,

    -- 멀티테넌시 (선택적)
    user_id VARCHAR(255),
    session_id VARCHAR(255),

    -- 추가 메타데이터
    cache_metadata JSONB DEFAULT '{}',

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_query_cache_expires_at ON query_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_query_cache_intent ON query_cache(query_intent);
CREATE INDEX IF NOT EXISTS idx_query_cache_hash ON query_cache(query_hash);
CREATE INDEX IF NOT EXISTS idx_query_cache_user_id ON query_cache(user_id);
CREATE INDEX IF NOT EXISTS idx_query_cache_created_at ON query_cache(created_at);

-- halfvec 캐스팅 HNSW (pgvector 0.7.0+): vector(3072) 저장, halfvec(3072) 인덱싱
CREATE INDEX IF NOT EXISTS idx_query_cache_vector
  ON query_cache USING hnsw ((query_vector::halfvec(3072)) halfvec_cosine_ops)
  WITH (m=16, ef_construction=64);

-- ============================================================================
-- 2. cache_statistics 테이블 - 캐시 통계
-- ============================================================================

CREATE TABLE IF NOT EXISTS cache_statistics (
    id BIGSERIAL PRIMARY KEY,

    -- 시간 구간
    time_bucket TIMESTAMP NOT NULL,

    -- 쿼리 유형
    query_intent VARCHAR(50) NOT NULL,

    -- 통계 데이터
    total_requests INTEGER DEFAULT 0,
    cache_hits INTEGER DEFAULT 0,
    cache_misses INTEGER DEFAULT 0,
    semantic_hits INTEGER DEFAULT 0,
    exact_hits INTEGER DEFAULT 0,

    -- 성능 지표
    avg_similarity_score FLOAT DEFAULT 0.0,
    avg_response_time_ms INTEGER DEFAULT 0,
    avg_ttl_remaining INTEGER DEFAULT 0,

    -- 저장 현황
    total_cached_entries INTEGER DEFAULT 0,
    storage_size_bytes BIGINT DEFAULT 0,

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_cache_stats_time_bucket ON cache_statistics(time_bucket);
CREATE INDEX IF NOT EXISTS idx_cache_stats_intent ON cache_statistics(query_intent);
CREATE INDEX IF NOT EXISTS idx_cache_stats_time_intent ON cache_statistics(time_bucket, query_intent);

-- 유니크 제약조건 (같은 시간대 + 의도 조합은 하나만)
CREATE UNIQUE INDEX IF NOT EXISTS idx_cache_stats_unique
    ON cache_statistics(time_bucket, query_intent);

-- ============================================================================
-- 3. 유틸리티 함수들
-- ============================================================================

-- 유사 쿼리 검색 함수
CREATE OR REPLACE FUNCTION find_similar_cached_queries(
    p_query_vector vector(3072),
    p_similarity_threshold FLOAT DEFAULT 0.85,
    p_intent VARCHAR DEFAULT NULL,
    p_user_id VARCHAR DEFAULT NULL,
    p_limit_results INT DEFAULT 5
)
RETURNS TABLE (
    cache_id BIGINT,
    query_text TEXT,
    query_intent VARCHAR,
    response_data JSONB,
    similarity_score FLOAT,
    expires_at TIMESTAMP,
    hit_count INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        qc.id as cache_id,
        qc.query_text,
        qc.query_intent,
        qc.response_data,
        (1 - (qc.query_vector::halfvec(3072) <=> p_query_vector::halfvec(3072)))::FLOAT as similarity_score,
        qc.expires_at,
        qc.hit_count
    FROM query_cache qc
    WHERE qc.expires_at > NOW()
        AND (p_intent IS NULL OR qc.query_intent = p_intent)
        AND (p_user_id IS NULL OR qc.user_id = p_user_id OR qc.user_id IS NULL)
        AND (1 - (qc.query_vector::halfvec(3072) <=> p_query_vector::halfvec(3072))) >= p_similarity_threshold
    ORDER BY qc.query_vector::halfvec(3072) <=> p_query_vector::halfvec(3072)
    LIMIT p_limit_results;
END;
$$ LANGUAGE plpgsql;

-- 만료된 캐시 정리 함수
CREATE OR REPLACE FUNCTION cleanup_expired_cache()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM query_cache WHERE expires_at <= NOW();
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- 캐시 히트 업데이트 함수
CREATE OR REPLACE FUNCTION update_cache_hit(p_cache_id BIGINT)
RETURNS VOID AS $$
BEGIN
    UPDATE query_cache
    SET
        hit_count = hit_count + 1,
        last_accessed_at = NOW(),
        updated_at = NOW()
    WHERE id = p_cache_id;
END;
$$ LANGUAGE plpgsql;

-- 캐시 통계 집계 함수
CREATE OR REPLACE FUNCTION get_cache_statistics_summary(
    p_hours INTEGER DEFAULT 24,
    p_intent VARCHAR DEFAULT NULL
)
RETURNS TABLE (
    total_requests BIGINT,
    total_hits BIGINT,
    exact_hits BIGINT,
    semantic_hits BIGINT,
    cache_misses BIGINT,
    hit_rate_percent FLOAT,
    avg_similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COALESCE(SUM(cs.total_requests), 0)::BIGINT as total_requests,
        COALESCE(SUM(cs.cache_hits), 0)::BIGINT as total_hits,
        COALESCE(SUM(cs.exact_hits), 0)::BIGINT as exact_hits,
        COALESCE(SUM(cs.semantic_hits), 0)::BIGINT as semantic_hits,
        COALESCE(SUM(cs.cache_misses), 0)::BIGINT as cache_misses,
        CASE
            WHEN COALESCE(SUM(cs.total_requests), 0) > 0
            THEN (COALESCE(SUM(cs.cache_hits), 0)::FLOAT / SUM(cs.total_requests) * 100)
            ELSE 0
        END as hit_rate_percent,
        COALESCE(AVG(cs.avg_similarity_score), 0)::FLOAT as avg_similarity
    FROM cache_statistics cs
    WHERE cs.time_bucket >= NOW() - (p_hours || ' hours')::INTERVAL
        AND (p_intent IS NULL OR cs.query_intent = p_intent);
END;
$$ LANGUAGE plpgsql;

-- 의도별 TTL 현황 조회 함수
CREATE OR REPLACE FUNCTION get_ttl_by_intent()
RETURNS TABLE (
    query_intent VARCHAR,
    entry_count BIGINT,
    avg_ttl_seconds FLOAT,
    min_ttl_seconds INTEGER,
    max_ttl_seconds INTEGER,
    avg_remaining_ttl_seconds FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        qc.query_intent,
        COUNT(*)::BIGINT as entry_count,
        AVG(qc.ttl_seconds)::FLOAT as avg_ttl_seconds,
        MIN(qc.ttl_seconds) as min_ttl_seconds,
        MAX(qc.ttl_seconds) as max_ttl_seconds,
        AVG(EXTRACT(EPOCH FROM (qc.expires_at - NOW())))::FLOAT as avg_remaining_ttl_seconds
    FROM query_cache qc
    WHERE qc.expires_at > NOW()
    GROUP BY qc.query_intent
    ORDER BY entry_count DESC;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 4. 자동 정리를 위한 파티션 및 유지보수 설정 (선택적)
-- ============================================================================

-- 코멘트 추가
COMMENT ON TABLE query_cache IS '스마트 캐시 엔트리 - pgvector 기반 의미론적 캐싱과 동적 TTL 지원';
COMMENT ON TABLE cache_statistics IS '캐시 성능 통계 - 시간대별 히트율 및 성능 지표 추적';

COMMENT ON COLUMN query_cache.query_vector IS 'Gemini Embedding 2 Flash (3072 차원) 임베딩 벡터';
COMMENT ON COLUMN query_cache.ttl_seconds IS '쿼리 의도, 복잡도, 품질에 따라 동적으로 계산된 TTL';
COMMENT ON COLUMN query_cache.expires_at IS 'created_at + ttl_seconds로 계산된 만료 시간';

-- ============================================================================
-- 완료
-- ============================================================================

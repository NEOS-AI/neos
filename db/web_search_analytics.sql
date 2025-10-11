-- Web Search Analytics Schema
-- 웹 검색 로그 분석을 위한 함수 및 뷰

-- ============================================================================
-- 분석용 함수
-- ============================================================================

-- 기간별 인기 검색 쿼리 조회 함수
CREATE OR REPLACE FUNCTION get_popular_queries(
    p_engine_name VARCHAR(100) DEFAULT NULL,
    p_period_days INTEGER DEFAULT 7,
    p_limit INTEGER DEFAULT 50
)
RETURNS TABLE (
    query_text TEXT,
    search_count BIGINT,
    unique_users BIGINT,
    avg_quality_score FLOAT,
    avg_execution_time_ms FLOAT,
    success_rate FLOAT,
    first_searched TIMESTAMP,
    last_searched TIMESTAMP,
    engine_name VARCHAR(100)
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        q.query_text,
        COUNT(*)::BIGINT as search_count,
        COUNT(DISTINCT q.user_id)::BIGINT as unique_users,
        ROUND(AVG(q.quality_score)::numeric, 3)::FLOAT as avg_quality_score,
        ROUND(AVG(q.execution_time_ms)::numeric, 2)::FLOAT as avg_execution_time_ms,
        ROUND((COUNT(CASE WHEN q.status = 'completed' THEN 1 END)::numeric / COUNT(*)::numeric), 3)::FLOAT as success_rate,
        MIN(q.executed_at) as first_searched,
        MAX(q.executed_at) as last_searched,
        q.engine_name
    FROM web_search_queries q
    WHERE
        q.executed_at > NOW() - (p_period_days || ' days')::INTERVAL
        AND (p_engine_name IS NULL OR q.engine_name = p_engine_name)
    GROUP BY q.query_text, q.engine_name
    HAVING COUNT(*) > 1  -- 최소 2번 이상 검색된 쿼리만
    ORDER BY search_count DESC, last_searched DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- 검색 엔진별 통계 함수
CREATE OR REPLACE FUNCTION get_engine_statistics(
    p_period_days INTEGER DEFAULT 7
)
RETURNS TABLE (
    engine_name VARCHAR(100),
    total_queries BIGINT,
    unique_queries BIGINT,
    unique_users BIGINT,
    avg_execution_time_ms FLOAT,
    avg_quality_score FLOAT,
    avg_results_count FLOAT,
    success_rate FLOAT,
    failed_queries BIGINT,
    timeout_queries BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        q.engine_name,
        COUNT(*)::BIGINT as total_queries,
        COUNT(DISTINCT q.query_text)::BIGINT as unique_queries,
        COUNT(DISTINCT q.user_id)::BIGINT as unique_users,
        ROUND(AVG(q.execution_time_ms)::numeric, 2)::FLOAT as avg_execution_time_ms,
        ROUND(AVG(q.quality_score)::numeric, 3)::FLOAT as avg_quality_score,
        ROUND(AVG(q.results_returned_count)::numeric, 2)::FLOAT as avg_results_count,
        ROUND((COUNT(CASE WHEN q.status = 'completed' THEN 1 END)::numeric / COUNT(*)::numeric), 3)::FLOAT as success_rate,
        COUNT(CASE WHEN q.status = 'failed' THEN 1 END)::BIGINT as failed_queries,
        COUNT(CASE WHEN q.timeout_occurred = TRUE THEN 1 END)::BIGINT as timeout_queries
    FROM web_search_queries q
    WHERE q.executed_at > NOW() - (p_period_days || ' days')::INTERVAL
    GROUP BY q.engine_name
    ORDER BY total_queries DESC;
END;
$$ LANGUAGE plpgsql;

-- 시간대별 검색 트렌드 함수
CREATE OR REPLACE FUNCTION get_search_trends(
    p_engine_name VARCHAR(100) DEFAULT NULL,
    p_period_days INTEGER DEFAULT 7,
    p_interval TEXT DEFAULT 'hour'  -- 'hour', 'day', 'week'
)
RETURNS TABLE (
    time_bucket TIMESTAMP,
    search_count BIGINT,
    unique_queries BIGINT,
    avg_quality_score FLOAT,
    engine_name VARCHAR(100)
) AS $$
DECLARE
    v_interval_expr TEXT;
BEGIN
    -- 인터벌 표현식 결정
    CASE p_interval
        WHEN 'hour' THEN v_interval_expr := '1 hour';
        WHEN 'day' THEN v_interval_expr := '1 day';
        WHEN 'week' THEN v_interval_expr := '1 week';
        ELSE v_interval_expr := '1 hour';
    END CASE;

    RETURN QUERY EXECUTE format('
        SELECT
            date_trunc(%L, q.executed_at) as time_bucket,
            COUNT(*)::BIGINT as search_count,
            COUNT(DISTINCT q.query_text)::BIGINT as unique_queries,
            ROUND(AVG(q.quality_score)::numeric, 3)::FLOAT as avg_quality_score,
            q.engine_name
        FROM web_search_queries q
        WHERE
            q.executed_at > NOW() - interval %L
            AND ($1 IS NULL OR q.engine_name = $1)
        GROUP BY date_trunc(%L, q.executed_at), q.engine_name
        ORDER BY time_bucket DESC
    ', p_interval, p_period_days || ' days', p_interval)
    USING p_engine_name;
END;
$$ LANGUAGE plpgsql;

-- 쿼리 유사도 분석 함수 (해시 기반)
CREATE OR REPLACE FUNCTION get_similar_queries(
    p_query_hash VARCHAR(64),
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    query_text TEXT,
    query_hash VARCHAR(64),
    search_count BIGINT,
    last_searched TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        q.query_text,
        q.query_hash,
        COUNT(*)::BIGINT as search_count,
        MAX(q.executed_at) as last_searched
    FROM web_search_queries q
    WHERE q.query_hash = p_query_hash
    GROUP BY q.query_text, q.query_hash
    ORDER BY search_count DESC, last_searched DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- 사용자별 검색 패턴 함수
CREATE OR REPLACE FUNCTION get_user_search_patterns(
    p_user_id VARCHAR(255),
    p_period_days INTEGER DEFAULT 30
)
RETURNS TABLE (
    query_text TEXT,
    search_count BIGINT,
    engines_used TEXT[],
    avg_quality_score FLOAT,
    first_searched TIMESTAMP,
    last_searched TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        q.query_text,
        COUNT(*)::BIGINT as search_count,
        ARRAY_AGG(DISTINCT q.engine_name)::TEXT[] as engines_used,
        ROUND(AVG(q.quality_score)::numeric, 3)::FLOAT as avg_quality_score,
        MIN(q.executed_at) as first_searched,
        MAX(q.executed_at) as last_searched
    FROM web_search_queries q
    WHERE
        q.user_id = p_user_id
        AND q.executed_at > NOW() - (p_period_days || ' days')::INTERVAL
    GROUP BY q.query_text
    ORDER BY search_count DESC, last_searched DESC;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 분석용 뷰
-- ============================================================================

-- 일일 통계 뷰
CREATE OR REPLACE VIEW daily_search_statistics AS
SELECT
    DATE(executed_at) as search_date,
    engine_name,
    COUNT(*) as total_queries,
    COUNT(DISTINCT query_text) as unique_queries,
    COUNT(DISTINCT user_id) as unique_users,
    ROUND(AVG(execution_time_ms)::numeric, 2) as avg_execution_time_ms,
    ROUND(AVG(quality_score)::numeric, 3) as avg_quality_score,
    COUNT(CASE WHEN status = 'completed' THEN 1 END) as successful_queries,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_queries,
    COUNT(CASE WHEN timeout_occurred = TRUE THEN 1 END) as timeout_queries
FROM web_search_queries
WHERE executed_at > NOW() - INTERVAL '90 days'
GROUP BY DATE(executed_at), engine_name
ORDER BY search_date DESC, engine_name;

-- 주간 통계 뷰
CREATE OR REPLACE VIEW weekly_search_statistics AS
SELECT
    DATE_TRUNC('week', executed_at)::DATE as week_start,
    engine_name,
    COUNT(*) as total_queries,
    COUNT(DISTINCT query_text) as unique_queries,
    COUNT(DISTINCT user_id) as unique_users,
    ROUND(AVG(execution_time_ms)::numeric, 2) as avg_execution_time_ms,
    ROUND(AVG(quality_score)::numeric, 3) as avg_quality_score,
    COUNT(CASE WHEN status = 'completed' THEN 1 END) as successful_queries,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_queries
FROM web_search_queries
WHERE executed_at > NOW() - INTERVAL '365 days'
GROUP BY DATE_TRUNC('week', executed_at), engine_name
ORDER BY week_start DESC, engine_name;

-- 월간 통계 뷰
CREATE OR REPLACE VIEW monthly_search_statistics AS
SELECT
    DATE_TRUNC('month', executed_at)::DATE as month_start,
    engine_name,
    COUNT(*) as total_queries,
    COUNT(DISTINCT query_text) as unique_queries,
    COUNT(DISTINCT user_id) as unique_users,
    ROUND(AVG(execution_time_ms)::numeric, 2) as avg_execution_time_ms,
    ROUND(AVG(quality_score)::numeric, 3) as avg_quality_score,
    COUNT(CASE WHEN status = 'completed' THEN 1 END) as successful_queries,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_queries
FROM web_search_queries
GROUP BY DATE_TRUNC('month', executed_at), engine_name
ORDER BY month_start DESC, engine_name;

-- 인기 검색어 뷰 (지난 7일)
CREATE OR REPLACE VIEW popular_queries_7d AS
SELECT
    query_text,
    engine_name,
    COUNT(*) as search_count,
    COUNT(DISTINCT user_id) as unique_users,
    ROUND(AVG(quality_score)::numeric, 3) as avg_quality_score,
    MAX(executed_at) as last_searched
FROM web_search_queries
WHERE executed_at > NOW() - INTERVAL '7 days'
GROUP BY query_text, engine_name
HAVING COUNT(*) > 1
ORDER BY search_count DESC
LIMIT 100;

-- 인기 검색어 뷰 (지난 30일)
CREATE OR REPLACE VIEW popular_queries_30d AS
SELECT
    query_text,
    engine_name,
    COUNT(*) as search_count,
    COUNT(DISTINCT user_id) as unique_users,
    ROUND(AVG(quality_score)::numeric, 3) as avg_quality_score,
    MAX(executed_at) as last_searched
FROM web_search_queries
WHERE executed_at > NOW() - INTERVAL '30 days'
GROUP BY query_text, engine_name
HAVING COUNT(*) > 1
ORDER BY search_count DESC
LIMIT 100;

-- 검색 품질 분석 뷰
CREATE OR REPLACE VIEW search_quality_analysis AS
SELECT
    engine_name,
    DATE(executed_at) as search_date,
    COUNT(*) as total_queries,
    ROUND(AVG(quality_score)::numeric, 3) as avg_quality_score,
    ROUND(AVG(results_returned_count)::numeric, 2) as avg_results_count,
    ROUND(AVG(execution_time_ms)::numeric, 2) as avg_execution_time_ms,
    COUNT(CASE WHEN quality_score >= 0.8 THEN 1 END) as high_quality_queries,
    COUNT(CASE WHEN quality_score < 0.5 THEN 1 END) as low_quality_queries
FROM web_search_queries
WHERE
    executed_at > NOW() - INTERVAL '30 days'
    AND quality_score IS NOT NULL
GROUP BY engine_name, DATE(executed_at)
ORDER BY search_date DESC, engine_name;

-- 사용자 활동 분석 뷰
CREATE OR REPLACE VIEW user_activity_analysis AS
SELECT
    user_id,
    COUNT(*) as total_searches,
    COUNT(DISTINCT query_text) as unique_queries,
    COUNT(DISTINCT engine_name) as engines_used,
    ROUND(AVG(quality_score)::numeric, 3) as avg_quality_score,
    MIN(executed_at) as first_search,
    MAX(executed_at) as last_search,
    DATE_PART('day', MAX(executed_at) - MIN(executed_at))::INTEGER as active_days
FROM web_search_queries
WHERE
    user_id IS NOT NULL
    AND executed_at > NOW() - INTERVAL '90 days'
GROUP BY user_id
HAVING COUNT(*) > 5
ORDER BY total_searches DESC;

-- ============================================================================
-- 인덱스 추가 (분석 성능 최적화)
-- ============================================================================

-- 기간별 조회를 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_web_search_queries_date_engine
    ON web_search_queries (DATE(executed_at), engine_name);

-- 사용자별 조회를 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_web_search_queries_user_date
    ON web_search_queries (user_id, executed_at DESC)
    WHERE user_id IS NOT NULL;

-- 품질 점수 분석을 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_web_search_queries_quality
    ON web_search_queries (quality_score)
    WHERE quality_score IS NOT NULL;

-- 쿼리 텍스트 검색을 위한 인덱스 (GIN)
CREATE INDEX IF NOT EXISTS idx_web_search_queries_text_gin
    ON web_search_queries USING gin(to_tsvector('simple', query_text));

-- ============================================================================
-- 코멘트 추가
-- ============================================================================

COMMENT ON FUNCTION get_popular_queries IS '기간별 인기 검색 쿼리 조회 (엔진별 필터링 가능)';
COMMENT ON FUNCTION get_engine_statistics IS '검색 엔진별 통계 조회';
COMMENT ON FUNCTION get_search_trends IS '시간대별 검색 트렌드 조회';
COMMENT ON FUNCTION get_similar_queries IS '유사 쿼리 조회 (해시 기반)';
COMMENT ON FUNCTION get_user_search_patterns IS '사용자별 검색 패턴 분석';

COMMENT ON VIEW daily_search_statistics IS '일일 검색 통계';
COMMENT ON VIEW weekly_search_statistics IS '주간 검색 통계';
COMMENT ON VIEW monthly_search_statistics IS '월간 검색 통계';
COMMENT ON VIEW popular_queries_7d IS '지난 7일간 인기 검색어';
COMMENT ON VIEW popular_queries_30d IS '지난 30일간 인기 검색어';
COMMENT ON VIEW search_quality_analysis IS '검색 품질 분석';
COMMENT ON VIEW user_activity_analysis IS '사용자 활동 분석';

-- Web Search Log Schema
-- 웹 검색 쿼리 및 결과를 기록하는 데이터베이스 스키마
-- ParadeDB BM25 인덱스를 활용한 검색 쿼리 인덱싱 포함

-- ============================================================================
-- 1. 검색 엔진 정보 테이블
-- ============================================================================
CREATE TABLE IF NOT EXISTS search_engines (
    id SERIAL PRIMARY KEY,
    engine_name VARCHAR(100) UNIQUE NOT NULL, -- 'tavily', 'mcp_brave', 'mcp_exa', 'custom' 등
    engine_type VARCHAR(50) NOT NULL, -- 'web', 'academic', 'news', 'data' 등
    engine_version VARCHAR(50),
    base_url TEXT,
    rate_limit_per_minute INTEGER,
    max_results_per_query INTEGER,
    supports_async BOOLEAN DEFAULT TRUE,

    -- 엔진 설정 및 메타데이터
    configuration JSONB DEFAULT '{}', -- API 키, 옵션 등 (민감정보 제외)
    capabilities JSONB DEFAULT '{}', -- 지원 기능 목록

    -- 통계 정보
    total_queries_executed BIGINT DEFAULT 0,
    total_results_returned BIGINT DEFAULT 0,
    average_response_time_ms INTEGER,
    success_rate FLOAT DEFAULT 1.0,

    -- 상태 관리
    is_active BOOLEAN DEFAULT TRUE,
    is_deprecated BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deprecated_at TIMESTAMP,

    -- 메타데이터
    metadata JSONB DEFAULT '{}'
);

-- ============================================================================
-- 2. 검색 쿼리 로그 테이블 (메인 테이블)
-- ============================================================================
CREATE TABLE IF NOT EXISTS web_search_queries (
    id SERIAL PRIMARY KEY,
    query_id VARCHAR(255) UNIQUE NOT NULL, -- UUID 형식

    -- 검색 쿼리 정보
    query_text TEXT NOT NULL, -- 실제 검색 쿼리
    query_hash VARCHAR(64) NOT NULL, -- 쿼리 중복 체크용 해시 (SHA-256)
    query_language VARCHAR(10), -- 'ko', 'en', 'ja' 등
    query_intent VARCHAR(100), -- 'informational', 'transactional', 'navigational' 등

    -- 검색 엔진 정보
    engine_id INTEGER NOT NULL,
    engine_name VARCHAR(100) NOT NULL, -- 비정규화 (빠른 조회)

    -- 사용자 및 세션 정보
    user_id VARCHAR(255),
    session_id VARCHAR(255),

    -- 검색 실행 정보
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    execution_time_ms INTEGER, -- 검색 실행 시간
    timeout_occurred BOOLEAN DEFAULT FALSE,

    -- 검색 파라미터
    search_params JSONB DEFAULT '{}', -- max_results, filters, 등

    -- 결과 통계
    total_results_count INTEGER DEFAULT 0,
    results_returned_count INTEGER DEFAULT 0,

    -- 상태 및 품질
    status VARCHAR(50) DEFAULT 'completed', -- 'completed', 'failed', 'timeout', 'cached'
    error_message TEXT,
    quality_score FLOAT, -- 결과 품질 점수 (0-1)

    -- 캐시 정보
    was_cached BOOLEAN DEFAULT FALSE,
    cache_hit_at TIMESTAMP,

    -- 추적 및 디버깅
    trace_id VARCHAR(255), -- 분산 추적용
    parent_query_id VARCHAR(255), -- 연관 쿼리 추적

    -- 메타데이터
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (engine_id) REFERENCES search_engines(id) ON DELETE RESTRICT,
    FOREIGN KEY (parent_query_id) REFERENCES web_search_queries(query_id) ON DELETE SET NULL
);

-- ============================================================================
-- 3. 검색 결과 테이블 (시간에 따른 변화 추적)
-- ============================================================================
CREATE TABLE IF NOT EXISTS web_search_results (
    id SERIAL PRIMARY KEY,
    result_id VARCHAR(255) UNIQUE NOT NULL, -- UUID 형식
    query_id VARCHAR(255) NOT NULL,

    -- 결과 식별 정보
    result_url TEXT NOT NULL,
    url_hash VARCHAR(64) NOT NULL, -- URL 중복 체크용 해시
    result_position INTEGER, -- 검색 결과 순위

    -- 결과 내용
    result_title TEXT,
    result_content TEXT, -- 스니펫 또는 전체 내용
    result_summary TEXT, -- AI 요약본

    -- 결과 메타데이터
    author VARCHAR(500),
    published_date TIMESTAMP,
    last_modified_date TIMESTAMP,
    domain VARCHAR(255),

    -- 점수 및 품질
    relevance_score FLOAT, -- 검색 엔진 제공 점수
    quality_score FLOAT, -- 자체 품질 평가
    confidence_score FLOAT, -- 신뢰도 점수

    -- 결과 타입 및 분류
    content_type VARCHAR(100), -- 'article', 'product', 'news', 'academic', 'video' 등
    content_category VARCHAR(100),

    -- 추가 구조화된 데이터
    structured_data JSONB DEFAULT '{}', -- schema.org, Open Graph 등
    extracted_entities JSONB DEFAULT '[]', -- NER 결과
    extracted_keywords JSONB DEFAULT '[]',

    -- 버전 관리 (동일 URL의 시간별 변화 추적)
    result_version INTEGER DEFAULT 1,
    is_latest_version BOOLEAN DEFAULT TRUE,
    content_hash VARCHAR(64), -- 내용 변화 감지용

    -- 타임스탬프
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- 메타데이터
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (query_id) REFERENCES web_search_queries(query_id) ON DELETE CASCADE
);

-- ============================================================================
-- 4. 검색 결과 변경 이력 테이블
-- ============================================================================
CREATE TABLE IF NOT EXISTS web_search_result_history (
    id SERIAL PRIMARY KEY,
    result_id VARCHAR(255) NOT NULL,

    -- 변경 정보
    change_type VARCHAR(50) NOT NULL, -- 'content_update', 'title_change', 'metadata_update', 'removed'
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- 변경 전후 데이터
    old_data JSONB,
    new_data JSONB,

    -- 변경 감지 방법
    detection_method VARCHAR(100), -- 'scheduled_check', 'realtime_monitor', 'user_trigger'

    -- 메타데이터
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (result_id) REFERENCES web_search_results(result_id) ON DELETE CASCADE
);

-- ============================================================================
-- 5. 검색 결과 관계 테이블 (결과 간 연관성)
-- ============================================================================
CREATE TABLE IF NOT EXISTS web_search_result_relations (
    id SERIAL PRIMARY KEY,
    source_result_id VARCHAR(255) NOT NULL,
    target_result_id VARCHAR(255) NOT NULL,

    relation_type VARCHAR(50) NOT NULL, -- 'duplicate', 'similar', 'related', 'updated_version'
    similarity_score FLOAT,

    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (source_result_id) REFERENCES web_search_results(result_id) ON DELETE CASCADE,
    FOREIGN KEY (target_result_id) REFERENCES web_search_results(result_id) ON DELETE CASCADE,

    UNIQUE (source_result_id, target_result_id, relation_type)
);

-- ============================================================================
-- 6. 검색 성능 메트릭 테이블
-- ============================================================================
CREATE TABLE IF NOT EXISTS web_search_metrics (
    id SERIAL PRIMARY KEY,
    query_id VARCHAR(255) NOT NULL,

    -- 성능 메트릭
    api_call_time_ms INTEGER,
    result_processing_time_ms INTEGER,
    total_time_ms INTEGER,

    -- 리소스 사용
    memory_used_mb FLOAT,
    network_bytes_sent INTEGER,
    network_bytes_received INTEGER,

    -- 품질 메트릭
    results_relevance_avg FLOAT,
    results_diversity_score FLOAT,
    user_satisfaction_score FLOAT, -- 사용자 피드백 기반

    -- 에러 및 재시도
    retry_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,

    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (query_id) REFERENCES web_search_queries(query_id) ON DELETE CASCADE
);

-- ============================================================================
-- 인덱스 생성
-- ============================================================================

-- 검색 엔진 인덱스
CREATE INDEX idx_search_engines_name ON search_engines(engine_name);
CREATE INDEX idx_search_engines_type ON search_engines(engine_type);
CREATE INDEX idx_search_engines_active ON search_engines(is_active) WHERE is_active = TRUE;

-- 검색 쿼리 인덱스
CREATE INDEX idx_web_search_queries_executed_at ON web_search_queries(executed_at DESC);
CREATE INDEX idx_web_search_queries_engine_id ON web_search_queries(engine_id);
CREATE INDEX idx_web_search_queries_user_session ON web_search_queries(user_id, session_id);
CREATE INDEX idx_web_search_queries_status ON web_search_queries(status);
CREATE INDEX idx_web_search_queries_hash ON web_search_queries(query_hash);
CREATE INDEX idx_web_search_queries_parent ON web_search_queries(parent_query_id);

-- 검색 결과 인덱스
CREATE INDEX idx_web_search_results_query_id ON web_search_results(query_id);
CREATE INDEX idx_web_search_results_url_hash ON web_search_results(url_hash);
CREATE INDEX idx_web_search_results_domain ON web_search_results(domain);
CREATE INDEX idx_web_search_results_captured_at ON web_search_results(captured_at DESC);
CREATE INDEX idx_web_search_results_latest ON web_search_results(result_url, is_latest_version) WHERE is_latest_version = TRUE;
CREATE INDEX idx_web_search_results_content_type ON web_search_results(content_type);

-- 검색 결과 변경 이력 인덱스
CREATE INDEX idx_web_search_result_history_result_id ON web_search_result_history(result_id);
CREATE INDEX idx_web_search_result_history_changed_at ON web_search_result_history(changed_at DESC);
CREATE INDEX idx_web_search_result_history_type ON web_search_result_history(change_type);

-- 검색 결과 관계 인덱스
CREATE INDEX idx_web_search_result_relations_source ON web_search_result_relations(source_result_id);
CREATE INDEX idx_web_search_result_relations_target ON web_search_result_relations(target_result_id);

-- 검색 메트릭 인덱스
CREATE INDEX idx_web_search_metrics_query_id ON web_search_metrics(query_id);
CREATE INDEX idx_web_search_metrics_recorded_at ON web_search_metrics(recorded_at DESC);

-- ============================================================================
-- ParadeDB BM25 전문 검색 인덱스 (검색 쿼리 텍스트)
-- ============================================================================
-- ParadeDB의 pg_search 확장이 설치되어 있어야 합니다
-- CREATE EXTENSION IF NOT EXISTS pg_search;

-- 검색 쿼리에 대한 BM25 인덱스
-- CALL paradedb.create_bm25(
--     index_name => 'search_queries_bm25_idx',
--     table_name => 'web_search_queries',
--     key_field => 'id',
--     text_fields => paradedb.field('query_text', tokenizer => paradedb.tokenizer('default'))
-- );

-- 검색 결과 타이틀과 콘텐츠에 대한 BM25 인덱스
-- CALL paradedb.create_bm25(
--     index_name => 'search_results_bm25_idx',
--     table_name => 'web_search_results',
--     key_field => 'id',
--     text_fields => '{
--         "result_title": {"tokenizer": "default"},
--         "result_content": {"tokenizer": "default"}
--     }'
-- );

-- ============================================================================
-- 트리거 및 함수
-- ============================================================================

-- 검색 엔진 통계 업데이트 트리거
CREATE OR REPLACE FUNCTION update_search_engine_stats()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE search_engines
        SET
            total_queries_executed = total_queries_executed + 1,
            total_results_returned = total_results_returned + COALESCE(NEW.results_returned_count, 0),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = NEW.engine_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_search_engine_stats
    AFTER INSERT ON web_search_queries
    FOR EACH ROW
    EXECUTE FUNCTION update_search_engine_stats();

-- 검색 엔진 updated_at 자동 업데이트
CREATE OR REPLACE FUNCTION update_search_engine_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_search_engine_updated_at
    BEFORE UPDATE ON search_engines
    FOR EACH ROW
    EXECUTE FUNCTION update_search_engine_updated_at();

-- 검색 결과 버전 관리 트리거
CREATE OR REPLACE FUNCTION manage_search_result_versions()
RETURNS TRIGGER AS $$
BEGIN
    -- 동일 URL의 기존 최신 버전을 is_latest_version = FALSE로 변경
    UPDATE web_search_results
    SET is_latest_version = FALSE
    WHERE result_url = NEW.result_url
      AND is_latest_version = TRUE
      AND result_id != NEW.result_id;

    -- 새 레코드의 버전 번호 설정
    NEW.result_version = (
        SELECT COALESCE(MAX(result_version), 0) + 1
        FROM web_search_results
        WHERE result_url = NEW.result_url
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_manage_search_result_versions
    BEFORE INSERT ON web_search_results
    FOR EACH ROW
    EXECUTE FUNCTION manage_search_result_versions();

-- 검색 결과 변경 감지 및 이력 기록 트리거
CREATE OR REPLACE FUNCTION track_search_result_changes()
RETURNS TRIGGER AS $$
DECLARE
    change_detected BOOLEAN := FALSE;
    change_data JSONB := '{}';
BEGIN
    -- 타이틀 변경 감지
    IF OLD.result_title IS DISTINCT FROM NEW.result_title THEN
        change_detected := TRUE;
        change_data := jsonb_set(
            change_data,
            '{title}',
            jsonb_build_object('old', OLD.result_title, 'new', NEW.result_title)
        );
    END IF;

    -- 콘텐츠 변경 감지 (해시 비교)
    IF OLD.content_hash IS DISTINCT FROM NEW.content_hash THEN
        change_detected := TRUE;
        change_data := jsonb_set(
            change_data,
            '{content}',
            jsonb_build_object('old_hash', OLD.content_hash, 'new_hash', NEW.content_hash)
        );
    END IF;

    -- 변경이 감지되면 이력 기록
    IF change_detected THEN
        INSERT INTO web_search_result_history (
            result_id,
            change_type,
            old_data,
            new_data,
            detection_method
        ) VALUES (
            NEW.result_id,
            'content_update',
            to_jsonb(OLD),
            change_data,
            'auto_trigger'
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_track_search_result_changes
    AFTER UPDATE ON web_search_results
    FOR EACH ROW
    EXECUTE FUNCTION track_search_result_changes();

-- ============================================================================
-- 유틸리티 함수
-- ============================================================================

-- 쿼리 해시 생성 함수
CREATE OR REPLACE FUNCTION generate_query_hash(query_text TEXT)
RETURNS VARCHAR(64) AS $$
BEGIN
    RETURN encode(digest(lower(trim(query_text)), 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- URL 해시 생성 함수
CREATE OR REPLACE FUNCTION generate_url_hash(url TEXT)
RETURNS VARCHAR(64) AS $$
BEGIN
    RETURN encode(digest(url, 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 검색 엔진 등록 함수
CREATE OR REPLACE FUNCTION register_search_engine(
    p_engine_name VARCHAR(100),
    p_engine_type VARCHAR(50),
    p_engine_version VARCHAR(50) DEFAULT NULL,
    p_configuration JSONB DEFAULT '{}'
) RETURNS INTEGER AS $$
DECLARE
    v_engine_id INTEGER;
BEGIN
    INSERT INTO search_engines (
        engine_name,
        engine_type,
        engine_version,
        configuration
    ) VALUES (
        p_engine_name,
        p_engine_type,
        p_engine_version,
        p_configuration
    )
    ON CONFLICT (engine_name)
    DO UPDATE SET
        engine_type = EXCLUDED.engine_type,
        engine_version = EXCLUDED.engine_version,
        configuration = EXCLUDED.configuration,
        updated_at = CURRENT_TIMESTAMP
    RETURNING id INTO v_engine_id;

    RETURN v_engine_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 뷰
-- ============================================================================

-- 검색 엔진 성능 개요 뷰
CREATE OR REPLACE VIEW search_engine_performance AS
SELECT
    e.id,
    e.engine_name,
    e.engine_type,
    e.is_active,
    e.total_queries_executed,
    e.total_results_returned,
    e.success_rate,
    ROUND(AVG(q.execution_time_ms)::numeric, 2) as avg_execution_time_ms,
    ROUND(AVG(q.quality_score)::numeric, 3) as avg_quality_score,
    COUNT(CASE WHEN q.status = 'failed' THEN 1 END) as failed_queries_count,
    COUNT(CASE WHEN q.status = 'completed' THEN 1 END) as successful_queries_count,
    MAX(q.executed_at) as last_used_at
FROM search_engines e
LEFT JOIN web_search_queries q ON e.id = q.engine_id
    AND q.executed_at > CURRENT_TIMESTAMP - INTERVAL '30 days'
GROUP BY e.id, e.engine_name, e.engine_type, e.is_active,
         e.total_queries_executed, e.total_results_returned, e.success_rate;

-- 최근 검색 쿼리 요약 뷰
CREATE OR REPLACE VIEW recent_search_queries AS
SELECT
    q.query_id,
    q.query_text,
    q.engine_name,
    q.user_id,
    q.executed_at,
    q.execution_time_ms,
    q.total_results_count,
    q.status,
    q.quality_score,
    COUNT(r.id) as stored_results_count
FROM web_search_queries q
LEFT JOIN web_search_results r ON q.query_id = r.query_id
WHERE q.executed_at > CURRENT_TIMESTAMP - INTERVAL '7 days'
GROUP BY q.query_id, q.query_text, q.engine_name, q.user_id,
         q.executed_at, q.execution_time_ms, q.total_results_count,
         q.status, q.quality_score
ORDER BY q.executed_at DESC;

-- URL별 최신 검색 결과 뷰
CREATE OR REPLACE VIEW latest_search_results_by_url AS
SELECT DISTINCT ON (result_url)
    result_id,
    query_id,
    result_url,
    result_title,
    result_content,
    result_summary,
    domain,
    relevance_score,
    quality_score,
    content_type,
    captured_at,
    result_version
FROM web_search_results
WHERE is_latest_version = TRUE
ORDER BY result_url, captured_at DESC;

-- ============================================================================
-- 기본 검색 엔진 등록
-- ============================================================================
INSERT INTO search_engines (engine_name, engine_type, engine_version, configuration) VALUES
    ('tavily', 'web', '1.0', '{"supports_realtime": true, "max_depth": 3}'::jsonb),
    ('mcp_brave', 'web', '1.0', '{"provider": "mcp", "supports_advanced_search": true}'::jsonb),
    ('mcp_exa', 'academic', '1.0', '{"provider": "mcp", "specialization": "research"}'::jsonb)
ON CONFLICT (engine_name) DO NOTHING;

-- ============================================================================
-- 코멘트 추가
-- ============================================================================
COMMENT ON TABLE search_engines IS '검색 엔진 정보 및 설정을 관리하는 테이블';
COMMENT ON TABLE web_search_queries IS '웹 검색 쿼리 실행 로그 및 메타데이터';
COMMENT ON TABLE web_search_results IS '검색 결과 데이터 및 버전 관리';
COMMENT ON TABLE web_search_result_history IS '검색 결과의 시간별 변경 이력';
COMMENT ON TABLE web_search_result_relations IS '검색 결과 간 관계 (중복, 유사도 등)';
COMMENT ON TABLE web_search_metrics IS '검색 성능 및 품질 메트릭';

-- 데이터베이스 스키마 설계
-- schema.sql

-- 확장 설치
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 사용자 테이블
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    preferences JSONB DEFAULT '{}'
);

-- insert base user for cli
INSERT INTO users (user_id) VALUES ('cli_user') ON CONFLICT (user_id) DO NOTHING;

-- 쿼리 히스토리 테이블
CREATE TABLE IF NOT EXISTS query_history (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255),
    original_query TEXT NOT NULL,
    processed_query TEXT,
    query_vector vector(3072), -- Gemini Embedding 2 차원
    query_intent VARCHAR(100),
    search_results JSONB,
    response_quality_score FLOAT DEFAULT 0.0,
    execution_time_ms INTEGER,
    tools_used TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- 연관 검색어 테이블
CREATE TABLE IF NOT EXISTS related_queries (
    id SERIAL PRIMARY KEY,
    source_query_id INTEGER,
    related_query_id INTEGER,
    similarity_score FLOAT,
    relation_type VARCHAR(50), -- 'semantic', 'sequential', 'collaborative'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_query_id) REFERENCES query_history(id),
    FOREIGN KEY (related_query_id) REFERENCES query_history(id)
);

-- 인기 검색어 집계 테이블
CREATE TABLE IF NOT EXISTS trending_queries (
    id SERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,
    query_vector vector(3072),
    search_count INTEGER DEFAULT 1,
    last_searched TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    time_period VARCHAR(20), -- 'hourly', 'daily', 'weekly'
    category VARCHAR(100)
);

-- 세션 기반 검색 패턴
CREATE TABLE IF NOT EXISTS search_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255),
    query_sequence JSONB, -- 쿼리 순서와 시간 정보
    session_intent VARCHAR(100),
    total_queries INTEGER DEFAULT 0,
    session_duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_query_created_at ON query_history(created_at);
CREATE INDEX IF NOT EXISTS idx_query_user_id ON query_history(user_id);
CREATE INDEX IF NOT EXISTS idx_trending_period ON trending_queries(time_period, last_searched);
CREATE INDEX IF NOT EXISTS idx_session_user ON search_sessions(user_id, created_at);

-- 트리그램 인덱스 (텍스트 유사성 검색용)
CREATE INDEX IF NOT EXISTS idx_query_text_trgm ON query_history USING gin (original_query gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_trending_text_trgm ON trending_queries USING gin (query_text gin_trgm_ops);

-- 벡터 인덱스: halfvec 캐스팅으로 HNSW (pgvector 0.7.0+, 4000차원까지 지원)
-- vector(3072) 컬럼을 halfvec(3072)로 캐스팅해 인덱싱 — 저장은 full-precision 유지
CREATE INDEX IF NOT EXISTS idx_query_vector ON query_history USING hnsw ((query_vector::halfvec(3072)) halfvec_cosine_ops) WITH (m=16, ef_construction=64);
CREATE INDEX IF NOT EXISTS idx_trending_vector ON trending_queries USING hnsw ((query_vector::halfvec(3072)) halfvec_cosine_ops) WITH (m=16, ef_construction=64);

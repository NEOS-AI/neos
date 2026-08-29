-- ============================================================================
-- Phase: Advanced Tool Search
-- tool_registry 테이블 생성 - 도구 메타데이터 저장 및 하이브리드 검색 지원
--
-- 참고: search_vector는 GENERATED ALWAYS AS 대신 트리거로 관리한다.
-- to_tsvector(regconfig, text)는 PostgreSQL 15 이하에서 generated column의
-- immutability 검사를 통과하지 못하는 경우가 있어 트리거 방식이 더 안전하다.
-- ============================================================================

-- pgvector 확장 확인 (이미 존재할 가능성 높음)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tool_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,              -- 도구 고유 이름
    display_name VARCHAR(255),                      -- 표시용 이름
    description TEXT NOT NULL,                      -- 도구 설명 (검색 대상)
    schema JSONB,                                   -- Anthropic tool input_schema
    category VARCHAR(100),                          -- 카테고리 (search, analysis, document, data, general)
    tags TEXT[],                                    -- 검색 보조 태그
    source_type VARCHAR(50) NOT NULL,               -- 'skill' | 'mcp_tool' | 'artifact_tool' | 'custom'
    defer_loading BOOLEAN DEFAULT TRUE,             -- false=코어 도구, true=검색 대상
    is_active BOOLEAN DEFAULT TRUE,                 -- 활성화 여부

    -- 검색 인덱스
    embedding vector(1536),                         -- 도구 설명 임베딩 (pgvector)
    search_vector tsvector,                         -- BM25 검색용 (트리거로 자동 관리)

    -- 메타데이터
    usage_count INTEGER DEFAULT 0,                  -- 사용 횟수 (코어 도구 자동 선정용)
    last_used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- search_vector 자동 갱신 트리거
-- name(A) > description(B) > tags(C) 가중치로 BM25 정확도를 높인다.
-- ============================================================================
CREATE OR REPLACE FUNCTION tool_registry_update_search_vector()
RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(array_to_string(NEW.tags, ' '), '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tool_registry_search_vector_trigger ON tool_registry;
CREATE TRIGGER tool_registry_search_vector_trigger
BEFORE INSERT OR UPDATE ON tool_registry
FOR EACH ROW EXECUTE FUNCTION tool_registry_update_search_vector();

-- ============================================================================
-- 인덱스
-- ============================================================================

-- HNSW 인덱스 (소수 도구에서도 효과적, ivfflat보다 적합)
CREATE INDEX IF NOT EXISTS idx_tool_registry_embedding ON tool_registry
    USING hnsw (embedding vector_cosine_ops);

-- GIN 인덱스 (full-text search)
CREATE INDEX IF NOT EXISTS idx_tool_registry_search_vector ON tool_registry
    USING gin (search_vector);

-- 코어 도구 조회 최적화
CREATE INDEX IF NOT EXISTS idx_tool_registry_defer_loading ON tool_registry (defer_loading)
    WHERE is_active = TRUE;

-- 카테고리 필터링
CREATE INDEX IF NOT EXISTS idx_tool_registry_category ON tool_registry (category);

-- source_type 필터링
CREATE INDEX IF NOT EXISTS idx_tool_registry_source_type ON tool_registry (source_type);

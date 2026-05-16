-- ============================================================================
-- Migration 028: document_chunks 테이블 생성
-- ============================================================================
-- 배경:
--   document_chunks 테이블에 대한 ALTER/SELECT/UPDATE 쿼리가 여러 마이그레이션
--   (007, 014, 020, 027)과 Python 코드 전반에 존재하지만 CREATE TABLE이 없었음.
--   이 마이그레이션은 모든 이전 ALTER 마이그레이션의 최종 상태를 반영한
--   완전한 테이블 정의를 포함한다.
--
-- 멱등성:
--   CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS 를 사용하므로
--   이미 테이블이 존재하는 기존 환경에서 실행해도 오류 없이 스킵됨.
--
-- FK 순서:
--   document_id → documents(id) 제약은 029_create_documents.sql 끝에서 추가됨.
--   새 환경에서는 029를 먼저 실행하거나, 028 실행 후 029 실행 시 FK가 자동 보완됨.
-- ============================================================================

-- pgvector 확장이 없으면 로드
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- 테이블 생성
-- ============================================================================
CREATE TABLE IF NOT EXISTS document_chunks (
    id                       SERIAL PRIMARY KEY,

    -- 부모 문서 참조 (FK fk_document_chunks_document_id 는 029_create_documents.sql 에서 추가)
    document_id              INTEGER NOT NULL,

    -- 청크 내용
    chunk_index              INTEGER NOT NULL,       -- 문서 내 청크 순서 (0-based)
    chunk_text               TEXT    NOT NULL,       -- 원본 청크 텍스트
    contextual_text          TEXT,                  -- Contextual Retrieval: 컨텍스트 + 청크 결합본 (migration 020)
    contextual_search_vector TSVECTOR,              -- BM25 검색용 ts_vector, 트리거가 자동 갱신 (migration 020)
    chunk_size               INTEGER,               -- 문자 수

    -- 원본 문서 내 위치
    page_number              INTEGER,
    start_offset             INTEGER,
    end_offset               INTEGER,

    -- 임베딩 (Gemini Embedding 2 — 3072차원, migration 027에서 1536→3072 변경)
    embedding                VECTOR(3072),

    -- Parent-child 청킹 지원 (migration 014)
    parent_chunk_id          INTEGER REFERENCES document_chunks(id) ON DELETE SET NULL,
    chunking_strategy        VARCHAR(20) DEFAULT 'sentence',  -- fixed | sentence | semantic | parent_child

    -- 청크 분류 메타데이터
    chunk_type               VARCHAR(50),           -- paragraph | heading | list | table | code
    heading_hierarchy        TEXT[],                -- 상위 헤딩 경로 (예: ['Chapter 1', 'Section 1.2'])
    extra_metadata           JSONB DEFAULT '{}',

    -- 임베딩 프로바이더 추적 (migration 007)
    embedding_provider       VARCHAR(50)  DEFAULT 'gemini',
    embedding_model          VARCHAR(100) DEFAULT 'gemini-embedding-2-flash',

    created_at               TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- contextual_search_vector 자동 갱신 트리거
-- (migration 020과 동일한 함수/트리거 — CREATE OR REPLACE로 멱등성 보장)
-- ============================================================================
CREATE OR REPLACE FUNCTION update_chunk_contextual_search_vector()
RETURNS trigger AS $$
BEGIN
    NEW.contextual_search_vector :=
        to_tsvector('english', coalesce(NEW.contextual_text, NEW.chunk_text, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS chunk_contextual_search_vector_trigger ON document_chunks;
CREATE TRIGGER chunk_contextual_search_vector_trigger
BEFORE INSERT OR UPDATE OF chunk_text, contextual_text ON document_chunks
FOR EACH ROW EXECUTE FUNCTION update_chunk_contextual_search_vector();

-- ============================================================================
-- 인덱스
-- ============================================================================

-- 기본 조회 인덱스
CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
    ON document_chunks(document_id);

CREATE INDEX IF NOT EXISTS idx_document_chunks_chunk_index
    ON document_chunks(chunk_index);

-- 임베딩 프로바이더별 조회 (migration 007)
CREATE INDEX IF NOT EXISTS idx_document_chunks_provider
    ON document_chunks(embedding_provider);

-- Parent-child 청킹 조회 (migration 014)
CREATE INDEX IF NOT EXISTS idx_document_chunks_parent
    ON document_chunks(parent_chunk_id);

CREATE INDEX IF NOT EXISTS idx_document_chunks_strategy
    ON document_chunks(chunking_strategy);

-- HNSW 벡터 유사도 검색 (migration 027 — halfvec 캐스팅으로 4000차원 제한 우회)
-- 저장: full-precision vector(3072), 인덱싱: half-precision halfvec(3072)
SET maintenance_work_mem = '1GB';
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding
    ON document_chunks USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- BM25 전문 검색 (migration 020)
CREATE INDEX IF NOT EXISTS idx_document_chunks_contextual_fts
    ON document_chunks USING gin(contextual_search_vector);

-- Contextual Retrieval 존재 여부 부분 인덱스 (migration 020)
CREATE INDEX IF NOT EXISTS idx_document_chunks_has_contextual
    ON document_chunks(document_id)
    WHERE contextual_text IS NOT NULL;

DO $$
BEGIN
    RAISE NOTICE '================================================================';
    RAISE NOTICE 'Migration 028 완료: document_chunks 테이블 생성';
    RAISE NOTICE '  - 19개 컬럼 (ORM 모델 + migration 007/014/020/027 반영)';
    RAISE NOTICE '  - 8개 인덱스 (B-tree × 6, HNSW × 1, GIN × 1)';
    RAISE NOTICE '  - contextual_search_vector 자동 갱신 트리거';
    RAISE NOTICE '  - document_id FK는 029_create_documents.sql 에서 추가됨';
    RAISE NOTICE '================================================================';
END $$;

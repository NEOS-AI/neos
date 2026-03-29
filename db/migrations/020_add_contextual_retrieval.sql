-- ============================================================================
-- Migration 020: Contextual Retrieval 지원을 위한 스키마 확장
-- ============================================================================
-- 변경 내용:
--   1. document_chunks.contextual_text TEXT 컬럼 추가
--   2. document_chunks.contextual_search_vector tsvector 컬럼 추가 (BM25용)
--   3. contextual_search_vector 자동 갱신 트리거 생성
--   4. GIN 인덱스 생성 (BM25 검색 성능)
--   5. 부분 인덱스 생성 (contextual_text 존재 여부 필터)
--   6. 기존 청크에 대해 contextual_search_vector 초기화

DO $$
BEGIN
    IF EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'document_chunks'
    ) THEN

        -- contextual_text 컬럼 추가
        IF NOT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'document_chunks'
              AND column_name = 'contextual_text'
        ) THEN
            ALTER TABLE document_chunks ADD COLUMN contextual_text TEXT;
            RAISE NOTICE 'Added contextual_text column to document_chunks';
        END IF;

        -- contextual_search_vector 컬럼 추가 (BM25용 tsvector)
        IF NOT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'document_chunks'
              AND column_name = 'contextual_search_vector'
        ) THEN
            ALTER TABLE document_chunks ADD COLUMN contextual_search_vector tsvector;
            RAISE NOTICE 'Added contextual_search_vector column to document_chunks';
        END IF;

    END IF;
END $$;

-- contextual_search_vector 자동 갱신 트리거
-- contextual_text가 있으면 contextual_text 기반, 없으면 chunk_text 기반
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

-- GIN 인덱스: BM25 검색 성능
CREATE INDEX IF NOT EXISTS idx_document_chunks_contextual_fts
    ON document_chunks USING gin(contextual_search_vector);

-- 부분 인덱스: contextual_text 존재 여부 필터
CREATE INDEX IF NOT EXISTS idx_document_chunks_has_contextual
    ON document_chunks(document_id)
    WHERE contextual_text IS NOT NULL;

-- 기존 청크에 대해 contextual_search_vector 초기화
UPDATE document_chunks
SET contextual_search_vector = to_tsvector('english', coalesce(chunk_text, ''))
WHERE contextual_search_vector IS NULL;

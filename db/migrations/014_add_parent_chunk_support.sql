-- Migration 014: Add parent chunk support for parent-child chunking
-- Phase 2.8: Advanced Chunking Strategies

DO $$
BEGIN
    -- document_chunks 테이블에 parent_chunk_id 컬럼 추가
    IF EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'document_chunks'
    ) THEN
        -- parent_chunk_id: 부모 청크 참조 (parent-child 전략용)
        IF NOT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'document_chunks'
            AND column_name = 'parent_chunk_id'
        ) THEN
            ALTER TABLE document_chunks
            ADD COLUMN parent_chunk_id INTEGER REFERENCES document_chunks(id) ON DELETE CASCADE;

            CREATE INDEX IF NOT EXISTS idx_document_chunks_parent ON document_chunks(parent_chunk_id);

            RAISE NOTICE 'Added parent_chunk_id column to document_chunks';
        END IF;

        -- chunking_strategy: 사용된 청킹 전략 기록
        IF NOT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'document_chunks'
            AND column_name = 'chunking_strategy'
        ) THEN
            ALTER TABLE document_chunks
            ADD COLUMN chunking_strategy VARCHAR(20) DEFAULT 'sentence';

            CREATE INDEX IF NOT EXISTS idx_document_chunks_strategy ON document_chunks(chunking_strategy);

            RAISE NOTICE 'Added chunking_strategy column to document_chunks';
        END IF;
    ELSE
        RAISE NOTICE 'document_chunks table does not exist, skipping migration';
    END IF;
END $$;

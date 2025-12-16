-- Migration 006: 다중 임베딩 Provider 지원
-- Google Gemini를 포함한 여러 임베딩 provider를 지원하기 위한 메타데이터 추가
--
-- 주요 변경사항:
-- 1. 임베딩 테이블에 provider 및 model 메타데이터 컬럼 추가
-- 2. 기존 데이터는 'openai'로 자동 태그
-- 3. Provider별 인덱스 추가
-- 4. Embedding provider 설정 테이블 추가

-- ============================================================================
-- Step 1: message_embeddings 테이블 업데이트
-- ============================================================================

-- message_embeddings에 provider 및 model 컬럼 추가
ALTER TABLE message_embeddings
ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR(50) DEFAULT 'openai',
ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100) DEFAULT 'text-embedding-3-small';

-- Provider별 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_message_embeddings_provider
ON message_embeddings(embedding_provider);

-- Provider와 conversation을 함께 사용하는 복합 인덱스
CREATE INDEX IF NOT EXISTS idx_message_embeddings_provider_conversation
ON message_embeddings(embedding_provider, conversation_id);

COMMENT ON COLUMN message_embeddings.embedding_provider IS
'임베딩 provider (openai, gemini 등)';

COMMENT ON COLUMN message_embeddings.embedding_model IS
'사용된 임베딩 모델 (text-embedding-3-small, gemini-embedding-001 등)';

-- ============================================================================
-- Step 2: conversation_embeddings 테이블 업데이트 (존재하는 경우)
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'conversation_embeddings') THEN
        ALTER TABLE conversation_embeddings
        ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR(50) DEFAULT 'openai',
        ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100) DEFAULT 'text-embedding-3-small';

        CREATE INDEX IF NOT EXISTS idx_conversation_embeddings_provider
        ON conversation_embeddings(embedding_provider);
    END IF;
END $$;

-- ============================================================================
-- Step 3: document_chunks 테이블 업데이트
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'document_chunks') THEN
        ALTER TABLE document_chunks
        ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR(50) DEFAULT 'openai',
        ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100) DEFAULT 'text-embedding-3-small';

        CREATE INDEX IF NOT EXISTS idx_document_chunks_provider
        ON document_chunks(embedding_provider);
    END IF;
END $$;

-- ============================================================================
-- Step 4: knowledge_graphs 테이블 업데이트
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'knowledge_graphs') THEN
        ALTER TABLE knowledge_graphs
        ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR(50) DEFAULT 'openai',
        ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100) DEFAULT 'text-embedding-3-small';

        CREATE INDEX IF NOT EXISTS idx_knowledge_graphs_provider
        ON knowledge_graphs(embedding_provider);
    END IF;
END $$;

-- ============================================================================
-- Step 5: query_history 테이블 업데이트
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'query_history') THEN
        ALTER TABLE query_history
        ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR(50) DEFAULT 'openai',
        ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100) DEFAULT 'text-embedding-3-small';

        CREATE INDEX IF NOT EXISTS idx_query_history_provider
        ON query_history(embedding_provider);
    END IF;
END $$;

-- ============================================================================
-- Step 6: trending_queries 테이블 업데이트
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'trending_queries') THEN
        ALTER TABLE trending_queries
        ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR(50) DEFAULT 'openai',
        ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100) DEFAULT 'text-embedding-3-small';

        CREATE INDEX IF NOT EXISTS idx_trending_queries_provider
        ON trending_queries(embedding_provider);
    END IF;
END $$;

-- ============================================================================
-- Step 7: smart_cache 테이블 업데이트
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'smart_cache') THEN
        ALTER TABLE smart_cache
        ADD COLUMN IF NOT EXISTS embedding_provider VARCHAR(50) DEFAULT 'openai',
        ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100) DEFAULT 'text-embedding-3-small';

        CREATE INDEX IF NOT EXISTS idx_smart_cache_provider
        ON smart_cache(embedding_provider);
    END IF;
END $$;

-- ============================================================================
-- Step 8: 임베딩 Provider 설정 테이블 생성
-- ============================================================================

CREATE TABLE IF NOT EXISTS embedding_provider_configs (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(50) NOT NULL UNIQUE,
    model VARCHAR(100) NOT NULL,
    dimension INTEGER NOT NULL,
    is_default BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE embedding_provider_configs IS
'임베딩 provider별 설정 정보';

COMMENT ON COLUMN embedding_provider_configs.provider IS
'Provider 이름 (openai, gemini 등)';

COMMENT ON COLUMN embedding_provider_configs.dimension IS
'임베딩 차원 크기';

COMMENT ON COLUMN embedding_provider_configs.is_default IS
'기본 provider 여부';

-- 기본 설정 데이터 삽입
INSERT INTO embedding_provider_configs (provider, model, dimension, is_default, description)
VALUES
    ('openai', 'text-embedding-3-small', 1536, TRUE, 'OpenAI text-embedding-3-small model'),
    ('gemini', 'gemini-embedding-001', 1536, FALSE, 'Google Gemini embedding model (configured to 1536 dimensions for OpenAI compatibility)')
ON CONFLICT (provider) DO NOTHING;

-- ============================================================================
-- Step 9: 업데이트 트리거 생성 (updated_at 자동 갱신)
-- ============================================================================

CREATE OR REPLACE FUNCTION update_embedding_provider_config_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_embedding_provider_config_updated_at
ON embedding_provider_configs;

CREATE TRIGGER trigger_update_embedding_provider_config_updated_at
    BEFORE UPDATE ON embedding_provider_configs
    FOR EACH ROW
    EXECUTE FUNCTION update_embedding_provider_config_updated_at();

-- ============================================================================
-- 완료 메시지
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '==========================================================';
    RAISE NOTICE 'Migration 006 completed successfully!';
    RAISE NOTICE '';
    RAISE NOTICE 'Changes:';
    RAISE NOTICE '- Added embedding_provider and embedding_model columns to embedding tables';
    RAISE NOTICE '- Created indexes for provider-based queries';
    RAISE NOTICE '- Created embedding_provider_configs table';
    RAISE NOTICE '- Existing embeddings are tagged as "openai" by default';
    RAISE NOTICE '';
    RAISE NOTICE 'Note: Gemini embeddings configured to use 1536 dimensions';
    RAISE NOTICE '      for compatibility with existing OpenAI embeddings.';
    RAISE NOTICE '==========================================================';
END $$;

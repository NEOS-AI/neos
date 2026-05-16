-- Migration 027: OpenAI 1536차원 → Gemini Embedding 2 3072차원 마이그레이션
-- 실행 전: 서비스 중단, DB 백업, 재임베딩 스크립트 준비
-- 실행 후: python scripts/reembed_to_gemini.py --table all --batch-size 100

-- ============================================================
-- Step 1: 기존 벡터 인덱스 제거 (차원 변경 전 필수)
-- 인덱스명은 각 마이그레이션 파일에서 확인한 실제 이름
-- ============================================================
BEGIN;

-- query_history: init.sql에서 생성된 인덱스
DROP INDEX IF EXISTS idx_query_vector;

-- trending_queries: init.sql에서 생성된 인덱스
DROP INDEX IF EXISTS idx_trending_vector;

-- query_cache: migration 006에서 HNSW로 업그레이드된 인덱스
-- (테이블명 주의: smart_cache가 아니라 query_cache)
DROP INDEX IF EXISTS idx_query_cache_vector_hnsw;

-- kg_entities: migration 015에서 생성된 인덱스
-- (knowledge_graphs 테이블과 별개의 독립 테이블)
DROP INDEX IF EXISTS idx_kg_entities_embedding;

-- tool_registry: migration 019에서 생성된 인덱스
DROP INDEX IF EXISTS idx_tool_registry_embedding;

-- long_term_memories: migration 012에서 생성된 인덱스
DROP INDEX IF EXISTS idx_ltm_embedding;

-- message_embeddings: chat_similarity_search.sql에서 생성된 인덱스
DROP INDEX IF EXISTS idx_message_embeddings_vector;

-- conversation_embeddings: chat_similarity_search.sql에서 생성된 인덱스
DROP INDEX IF EXISTS idx_conversation_embeddings_vector;

-- evidence_claims: migration 016에서 생성된 인덱스
-- (테이블명 주의: evidence_nodes가 아니라 evidence_claims)
DROP INDEX IF EXISTS idx_evidence_claims_embedding;

COMMIT;

-- ============================================================
-- Step 2: 벡터 컬럼 차원 변경 (기존 데이터 NULL로 초기화)
-- 각 테이블과 컬럼명을 실제 스키마와 일치시킴
-- ============================================================
BEGIN;

-- models.py QueryHistory.__tablename__ = "query_history"
ALTER TABLE query_history
  ALTER COLUMN query_vector TYPE vector(3072) USING NULL::vector(3072);

-- models.py TrendingQuery.__tablename__ = "trending_queries"
ALTER TABLE trending_queries
  ALTER COLUMN query_vector TYPE vector(3072) USING NULL::vector(3072);

-- models.py DocumentChunk.__tablename__ = "document_chunks"
ALTER TABLE document_chunks
  ALTER COLUMN embedding TYPE vector(3072) USING NULL::vector(3072);

-- models.py KnowledgeGraph.__tablename__ = "knowledge_graphs" (entity_embedding 컬럼)
ALTER TABLE knowledge_graphs
  ALTER COLUMN entity_embedding TYPE vector(3072) USING NULL::vector(3072);

-- migration 015에서 생성된 kg_entities 테이블 (knowledge_graphs와 별개!)
-- models.py에는 없고 순수 SQL로 관리되는 테이블
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'kg_entities') THEN
    ALTER TABLE kg_entities
      ALTER COLUMN embedding TYPE vector(3072) USING NULL::vector(3072);
  END IF;
END $$;

-- models.py QueryCacheEntry.__tablename__ = "query_cache" (smart_cache가 아님!)
ALTER TABLE query_cache
  ALTER COLUMN query_vector TYPE vector(3072) USING NULL::vector(3072);

-- models.py ToolRegistry.__tablename__ = "tool_registry"
ALTER TABLE tool_registry
  ALTER COLUMN embedding TYPE vector(3072) USING NULL::vector(3072);

-- migration 012에서 생성된 테이블 (models.py에 별도 ORM 없음)
ALTER TABLE long_term_memories
  ALTER COLUMN embedding TYPE vector(3072) USING NULL::vector(3072);

-- chat_similarity_search.sql에서 생성된 테이블들
ALTER TABLE message_embeddings
  ALTER COLUMN embedding TYPE vector(3072) USING NULL::vector(3072);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'conversation_embeddings') THEN
    ALTER TABLE conversation_embeddings
      ALTER COLUMN summary_embedding TYPE vector(3072) USING NULL::vector(3072);
  END IF;
END $$;

-- migration 016에서 생성된 테이블 (evidence_nodes가 아니라 evidence_claims!)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'evidence_claims') THEN
    ALTER TABLE evidence_claims
      ALTER COLUMN embedding TYPE vector(3072) USING NULL::vector(3072);
  END IF;
END $$;

COMMIT;

-- ============================================================
-- Step 3: HNSW 인덱스 재생성 (halfvec 캐스팅, pgvector 0.7.0+)
-- vector(3072) 컬럼을 halfvec(3072)로 캐스팅해 인덱싱
-- — 저장은 full-precision 유지, 인덱스만 half-precision (4000차원까지 지원)
-- NULL 벡터는 인덱싱 안 됨 — 재임베딩 후 자동으로 포함됨
-- ============================================================
SET maintenance_work_mem = '2GB';

CREATE INDEX IF NOT EXISTS idx_query_vector
  ON query_history USING hnsw ((query_vector::halfvec(3072)) halfvec_cosine_ops)
  WITH (m=16, ef_construction=64);

CREATE INDEX IF NOT EXISTS idx_trending_vector
  ON trending_queries USING hnsw ((query_vector::halfvec(3072)) halfvec_cosine_ops)
  WITH (m=16, ef_construction=64);

CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding
  ON document_chunks USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
  WITH (m=16, ef_construction=64);

CREATE INDEX IF NOT EXISTS idx_knowledge_graphs_entity_embedding
  ON knowledge_graphs USING hnsw ((entity_embedding::halfvec(3072)) halfvec_cosine_ops)
  WITH (m=16, ef_construction=64);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'kg_entities') THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_kg_entities_embedding ON kg_entities USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops) WITH (m=16, ef_construction=64)';
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_query_cache_vector_hnsw
  ON query_cache USING hnsw ((query_vector::halfvec(3072)) halfvec_cosine_ops)
  WITH (m=16, ef_construction=64);

CREATE INDEX IF NOT EXISTS idx_tool_registry_embedding
  ON tool_registry USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
  WITH (m=16, ef_construction=64);

CREATE INDEX IF NOT EXISTS idx_ltm_embedding
  ON long_term_memories USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
  WITH (m=16, ef_construction=64);

CREATE INDEX IF NOT EXISTS idx_message_embeddings_vector
  ON message_embeddings USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
  WITH (m=16, ef_construction=64);

CREATE INDEX IF NOT EXISTS idx_conversation_embeddings_vector
  ON conversation_embeddings USING hnsw ((summary_embedding::halfvec(3072)) halfvec_cosine_ops)
  WITH (m=16, ef_construction=64);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'evidence_claims') THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_evidence_claims_embedding ON evidence_claims USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops) WITH (m=16, ef_construction=64)';
  END IF;
END $$;

-- ============================================================
-- Step 4: embedding_provider_configs 테이블 업데이트
-- ============================================================
BEGIN;

INSERT INTO embedding_provider_configs (provider, model, dimension, is_default, description)
VALUES (
  'gemini',
  'gemini-embedding-2-flash',
  3072,
  TRUE,
  'Google Gemini Embedding 2 Flash — multimodal (text/image/video), 3072-dim'
)
ON CONFLICT (provider) DO UPDATE
  SET model = EXCLUDED.model,
      dimension = EXCLUDED.dimension,
      is_default = EXCLUDED.is_default,
      updated_at = NOW();

UPDATE embedding_provider_configs
  SET is_default = FALSE, updated_at = NOW()
  WHERE provider = 'openai';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE '=================================================================';
  RAISE NOTICE 'Migration 027 완료: vector(1536) → vector(3072)';
  RAISE NOTICE '다음 단계: python scripts/reembed_to_gemini.py --table all';
  RAISE NOTICE '=================================================================';
END $$;

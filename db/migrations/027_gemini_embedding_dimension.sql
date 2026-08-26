-- Migration 027: OpenAI 1536차원 → Gemini Embedding 2 3072차원 마이그레이션
-- 실행 전: 서비스 중단, DB 백업, 재임베딩 스크립트 준비
-- 실행 후: python scripts/reembed_to_gemini.py --table all --batch-size 100
--
-- ⚠️ 이 파일은 **ORM 테이블에 의존한다** (2026-08-25, SCHEMA1).
-- `knowledge_graphs` 는 `db/` 의 어떤 SQL 도 만들지 않는다 -- SQLAlchemy
-- `Base.metadata.create_all` 만 만드는 ORM 전용 테이블이다. 그래서 순수 SQL 로만
-- 부트스트랩한 신선한 DB 에서는 이 파일이 그 테이블에서 죽었고, 죽는 지점이
-- Step 2 라서 **Step 3(인덱스 재생성) 전체가 미적용**됐다. 결과는 006 과 같은
-- 고장이다 -- Step 1 이 드롭한 벡터 인덱스 9개가 되살아나지 않는다.
-- 아래 ORM 의존 구문에는 전부 IF EXISTS 가드를 두르고 건너뛴 사실을 NOTICE 로
-- 남긴다. **조용히 건너뛰지 않는다.**

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
-- 003/006 이 쓰는 이름도 함께 드롭한다. Step 3 이 `_hnsw` 쪽을 정본으로 다시
-- 만드는데 이것을 남기면 **같은 표현식 인덱스가 두 벌** 남아 쓰기 비용만 두 배가
-- 된다 (2026-08-25, SCHEMA1).
DROP INDEX IF EXISTS idx_query_cache_vector;

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
-- Step 1.5: 벡터 컬럼에 의존하는 뷰를 정의째 보관하고 드롭한다
--
-- PostgreSQL 은 뷰가 참조하는 컬럼의 타입을 바꾸지 못한다
-- (`cannot alter type of a column used by a view or rule`).
-- `chat_similarity_search.sql` 의 `message_embedding_stats` 가
-- `AVG(array_length(embedding::real[], 1))` 로 정확히 그 컬럼을 쓴다.
--
-- 뷰 정의를 여기 **복제하지 않는다.** 복제하면 원본과 갈라지고, 갈라지면
-- 어느 쪽이 정본인지 알 수 없게 된다 (로드맵 §7 FE6 이 두 언어로 구현된
-- 강등 판정에 대해 이름 붙인 그 문제다). 대신 `pg_get_viewdef()` 로 지금
-- 정의를 읽어 두고 Step 3 뒤에 그대로 되돌린다.
--
-- ⚠️ 한계: 뷰 위에 얹힌 뷰(중첩)는 CASCADE 로 함께 사라지지만 복원 목록에는
-- 들어오지 않는다. 현재 대상 뷰 둘은 중첩이 아니다 -- 중첩 뷰를 새로 만들면
-- 이 블록을 재귀 탐지로 고쳐야 한다.
-- ============================================================
-- 앞선 실행의 잔여를 남기지 않는다. 남기면 **옛 정의**로 복원해 버린다.
DROP TABLE IF EXISTS _027_saved_views;
CREATE TEMP TABLE _027_saved_views (view_name TEXT, view_def TEXT);

DO $$
DECLARE
  rec RECORD;
BEGIN
  FOR rec IN
    SELECT DISTINCT
           v.oid::regclass::text AS view_name,
           pg_get_viewdef(v.oid, true) AS view_def
      FROM pg_class v
      JOIN pg_rewrite r ON r.ev_class = v.oid
      JOIN pg_depend d ON d.objid = r.oid
      JOIN pg_class t ON t.oid = d.refobjid
     WHERE v.relkind = 'v'
       AND t.oid <> v.oid
       AND t.relname = ANY (ARRAY[
             'query_history', 'trending_queries', 'document_chunks',
             'knowledge_graphs', 'kg_entities', 'query_cache',
             'tool_registry', 'long_term_memories', 'message_embeddings',
             'conversation_embeddings', 'evidence_claims'
           ])
  LOOP
    INSERT INTO _027_saved_views VALUES (rec.view_name, rec.view_def);
    RAISE NOTICE '027: 뷰 %를 잠시 드롭한다 (Step 3 뒤에 복원)', rec.view_name;
    EXECUTE format('DROP VIEW IF EXISTS %s CASCADE', rec.view_name);
  END LOOP;
END $$;

-- ============================================================
-- Step 2: 벡터 컬럼 차원 변경 (1536 → 3072, 기존 데이터는 NULL 로 초기화)
--
-- 대상을 표로 들고 루프를 돈다. 흩어진 ALTER 11개를 그대로 두지 않는 이유가
-- 둘이다 (2026-08-25, SCHEMA1).
--
-- (1) **재실행이 데이터를 지웠다.** `ALTER COLUMN ... TYPE vector(3072) USING
--     NULL::vector(3072)` 는 컬럼이 **이미 vector(3072) 여도** 테이블을 재작성하며
--     USING 을 적용한다 -- 즉 두 번째 실행부터는 차원 변경이 아니라 순수한 삭제다.
--     실측으로 확인했다(임시 테이블, non-null 1 → 0). `tests/conftest.py` 가 세션마다
--     `db/migrations/*.sql` 를 적용하므로, 개발 DB 에 임베딩이 쌓인 뒤 pytest 를
--     한 번 돌리면 전부 사라진다. 그래서 **이미 3072 면 건너뛴다.**
--
-- (2) 테이블 존재 가드가 일부에만 있었다. `knowledge_graphs` 는 ORM 전용이라
--     순수 SQL 부트스트랩에서 없는데 가드가 없어 여기서 죽었고, 죽는 지점이
--     Step 2 라 **Step 3 이 통째로 미적용**됐다(006 과 같은 고장).
--
-- 대상 목록은 손으로 든다 -- 어느 컬럼이 Gemini 임베딩을 담는지는 스키마가
-- 말해 주지 않는다. 단 Step 1·3 의 인덱스 목록과 짝이 맞아야 한다.
-- ============================================================
DO $$
DECLARE
  rec RECORD;
  current_type TEXT;
BEGIN
  FOR rec IN
    SELECT * FROM (VALUES
      ('query_history',           'query_vector'),      -- init.sql
      ('trending_queries',        'query_vector'),      -- init.sql
      ('document_chunks',         'embedding'),         -- 028
      ('knowledge_graphs',        'entity_embedding'),  -- ORM 전용 (create_all)
      ('kg_entities',             'embedding'),         -- 015 (knowledge_graphs 와 별개!)
      ('query_cache',             'query_vector'),      -- 003 (smart_cache 가 아니다)
      ('tool_registry',           'embedding'),         -- 019
      ('long_term_memories',      'embedding'),         -- 012
      ('message_embeddings',      'embedding'),         -- chat_similarity_search.sql
      ('conversation_embeddings', 'summary_embedding'), -- chat_similarity_search.sql
      ('evidence_claims',         'embedding')          -- 016 (evidence_nodes 가 아니다)
    ) AS t(table_name, column_name)
  LOOP
    SELECT format_type(a.atttypid, a.atttypmod)
      INTO current_type
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname = rec.table_name
       AND a.attname = rec.column_name
       AND a.attnum > 0
       AND NOT a.attisdropped;

    IF current_type IS NULL THEN
      RAISE NOTICE '027: %.% 가 없어 건너뛴다', rec.table_name, rec.column_name;
      CONTINUE;
    END IF;

    IF current_type = 'vector(3072)' THEN
      RAISE NOTICE '027: %.% 는 이미 3072 다 -- 건너뛴다 (재실행이 데이터를 지우지 않게)',
        rec.table_name, rec.column_name;
      CONTINUE;
    END IF;

    RAISE NOTICE '027: %.% 를 % → vector(3072) 로 바꾼다 (기존 값은 NULL 이 된다)',
      rec.table_name, rec.column_name, current_type;
    EXECUTE format(
      'ALTER TABLE %I ALTER COLUMN %I TYPE vector(3072) USING NULL::vector(3072)',
      rec.table_name, rec.column_name
    );
  END LOOP;
END $$;

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

-- knowledge_graphs 는 ORM 전용이라 Step 2 와 같은 가드가 필요하다.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'knowledge_graphs') THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_knowledge_graphs_entity_embedding ON knowledge_graphs USING hnsw ((entity_embedding::halfvec(3072)) halfvec_cosine_ops) WITH (m=16, ef_construction=64)';
  ELSE
    RAISE NOTICE '027: knowledge_graphs 인덱스를 건너뛴다 (테이블 없음)';
  END IF;
END $$;

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
-- Step 3.5: Step 1.5 에서 드롭한 뷰를 원래 정의로 되돌린다
-- ============================================================
DO $$
DECLARE
  rec RECORD;
BEGIN
  FOR rec IN SELECT view_name, view_def FROM _027_saved_views LOOP
    EXECUTE format('CREATE OR REPLACE VIEW %s AS %s', rec.view_name, rec.view_def);
    RAISE NOTICE '027: 뷰 %를 복원했다', rec.view_name;
  END LOOP;
END $$;

DROP TABLE IF EXISTS _027_saved_views;

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

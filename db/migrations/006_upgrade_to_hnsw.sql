-- Migration 006: query_cache 벡터 인덱스를 HNSW 로 맞춘다 (멱등)
--
-- ⚠️ 이 파일은 2026-08-25 에 다시 쓰였다 (SCHEMA1). 원문은 아래 「원문이 무엇을
-- 했고 왜 틀렸나」에 남긴다 -- 지우면 다음 사람이 같은 것을 되살린다.
--
-- 원문이 무엇을 했고 왜 틀렸나
-- ---------------------------------------------------------------------
-- 원문은 `idx_query_cache_vector`(IVFFlat 이라 가정)를 DROP 하고
-- `idx_query_cache_vector_hnsw` 를 `hnsw (query_vector vector_cosine_ops)` 로
-- 만들었다. 그런데 `query_vector` 는 **vector(3072)** 이고 pgvector 는 hnsw 에
-- 2000 차원까지만 허용한다. 그래서 이 마이그레이션은 신선한 DB 에서 항상 실패했고,
-- 실패의 대가는 셋이었다 (2026-08-25 실측):
--
--   1. 003 이 만들어 둔 **정상 작동하는 인덱스를 지웠다.** 003 은 이미 이 문제를
--      halfvec 캐스팅으로 풀어 놨다 -- 해법이 같은 저장소 003 번 파일에 주석까지
--      달려 있었다. 즉 원문은 업그레이드가 아니라 **회귀**였다
--   2. `CREATE INDEX CONCURRENTLY` 가 실패하면서 **INVALID 인덱스가 잔류**했다
--   3. 그 INVALID 인덱스가 009 의 `ADD COLUMN ... GENERATED STORED` 테이블
--      재작성을 깨뜨려 009 까지 전량 미적용으로 만들었다. 009 는 자체 결함이
--      없다 -- 단독 재적용은 성공한다
--
-- 그래서 지금 이 파일이 하는 일
-- ---------------------------------------------------------------------
-- 목표 상태를 003 과 **같은 정의**로 못박고, 거기서 벗어난 것만 고친다.
-- 003 뒤에 곧바로 적용되면 아무것도 하지 않는다(no-op). 원문을 이미 겪은 DB 에
-- 적용하면 잔해를 치우고 인덱스를 되살린다.
--
-- ⚠️ CONCURRENTLY 를 쓰지 않는다. DO 블록 안에서는 불가능하고, 이 파일은 이제
-- 신규 배포와 치유가 용도라 잠금 시간보다 **멱등성**이 중요하다. 큰 테이블에
-- 온라인으로 적용해야 하면 아래 정의를 손으로 CONCURRENTLY 로 실행할 것.

DO $$
DECLARE
    target_definition CONSTANT TEXT :=
        'CREATE INDEX IF NOT EXISTS idx_query_cache_vector ON query_cache '
        'USING hnsw ((query_vector::halfvec(3072)) halfvec_cosine_ops) '
        'WITH (m = 16, ef_construction = 64)';
    existing_is_hnsw BOOLEAN;
BEGIN
    IF to_regclass('public.query_cache') IS NULL THEN
        RAISE NOTICE 'query_cache 가 없다 -- 003 이 먼저 적용돼야 한다. 건너뛴다';
        RETURN;
    END IF;

    -- (2) 원문이 남긴 INVALID 잔해. 이름이 다르므로 정본 인덱스와 충돌하지 않고
    --     조용히 남아 009 를 깨뜨린다.
    DROP INDEX IF EXISTS idx_query_cache_vector_hnsw;

    SELECT indexdef LIKE '%hnsw%'
      INTO existing_is_hnsw
      FROM pg_indexes
     WHERE schemaname = 'public'
       AND tablename = 'query_cache'
       AND indexname = 'idx_query_cache_vector';

    IF existing_is_hnsw IS TRUE THEN
        RETURN;  -- 이미 목표 상태 (003 직후의 정상 경로)
    END IF;

    -- 없거나(NULL), 옛 IVFFlat 이면 정본 정의로 다시 만든다.
    IF existing_is_hnsw IS FALSE THEN
        DROP INDEX idx_query_cache_vector;
    END IF;

    EXECUTE target_definition;
END
$$;

ANALYZE query_cache;

-- =====================================================
-- HNSW 파라미터 메모 (원문에서 보존)
-- =====================================================
--   m = 16               : 층당 최대 연결 수. 낮으면 빌드가 빠르고 부정확하다
--   ef_construction = 64 : 빌드 시 정확도/속도 트레이드오프
--
-- 질의 시점 파라미터는 세션마다 설정한다:
--   SET hnsw.ef_search = 40;
--
-- halfvec 캐스팅을 쓰는 이유: 저장은 vector(3072) 로 하고 인덱싱만
-- halfvec(3072) 로 한다. pgvector 0.7.0+ 가 필요하며 003 과 같은 방식이다.

-- ============================================================================
-- Migration 029: documents 테이블 생성
-- ============================================================================
-- 배경:
--   documents 테이블을 생성하는 CREATE TABLE이 어디에도 없었음.
--   init.sql과 001~028 마이그레이션 파일 모두 확인 결과 누락.
--   이 마이그레이션은 ORM 모델(Document 클래스)을 완전히 반영하며,
--   documents 테이블에는 별도의 ALTER TABLE 마이그레이션이 없으므로
--   ORM 모델이 곧 최종 상태임.
--
-- 멱등성:
--   CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS 를 사용하므로
--   이미 테이블이 존재하는 기존 환경에서 실행해도 오류 없이 스킵됨.
--
-- 선행 조건:
--   users 테이블이 먼저 존재해야 함 (FK user_id → users.user_id).
--   users 테이블은 db/init.sql 에서 생성됨.
--
-- FK 보완:
--   이 마이그레이션 끝에서 028_create_document_chunks.sql 에서 보류된
--   document_chunks.document_id → documents(id) FK 제약을 추가함.
-- ============================================================================

-- ============================================================================
-- 테이블 생성
-- ============================================================================
CREATE TABLE IF NOT EXISTS documents (
    id                   SERIAL PRIMARY KEY,

    -- 소유자
    user_id              VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    -- 파일 정보
    filename             VARCHAR(500) NOT NULL,          -- 저장된 파일명
    original_filename    VARCHAR(500) NOT NULL,          -- 업로드 원본 파일명
    file_size            INTEGER,                        -- 바이트 단위 파일 크기
    mime_type            VARCHAR(100),                   -- MIME 타입 (예: application/pdf)
    file_hash            VARCHAR(64),                    -- SHA-256 해시 (중복 업로드 감지용)

    -- 스토리지 정보 (S3 / RustFS / local)
    storage_provider     VARCHAR(50)   DEFAULT 's3',     -- 's3' | 'rustfs' | 'local'
    storage_bucket       VARCHAR(255),
    storage_key          VARCHAR(1000) NOT NULL,         -- 버킷 내 객체 키 (경로)
    storage_url          VARCHAR(2000),                  -- 직접 접근 가능한 URL

    -- 문서 메타데이터
    title                VARCHAR(500),
    author               VARCHAR(255),
    language             VARCHAR(10),                    -- ISO 639-1 (예: 'ko', 'en')
    page_count           INTEGER,
    word_count           INTEGER,

    -- 파이프라인 처리 상태
    processing_status    VARCHAR(50)  DEFAULT 'pending', -- pending | processing | completed | failed
    processing_error     TEXT,                           -- 실패 시 오류 메시지

    -- 지식 그래프 추출 여부
    kg_extracted         BOOLEAN     DEFAULT FALSE,
    kg_extraction_date   TIMESTAMP,

    -- 임베딩 처리 여부 (벡터 검색 가능 여부)
    embedding_processed  BOOLEAN     DEFAULT FALSE,
    embedding_date       TIMESTAMP,

    -- FTS 인덱싱 여부 (전문 검색 가능 여부)
    fts_indexed          BOOLEAN     DEFAULT FALSE,
    fts_index_date       TIMESTAMP,

    -- 확장 메타데이터
    extra_metadata       JSONB       DEFAULT '{}',

    -- 타임스탬프
    created_at           TIMESTAMP   DEFAULT NOW(),
    updated_at           TIMESTAMP   DEFAULT NOW()
);

-- ============================================================================
-- updated_at 자동 갱신 트리거
-- ============================================================================
CREATE OR REPLACE FUNCTION update_documents_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS documents_updated_at_trigger ON documents;
CREATE TRIGGER documents_updated_at_trigger
BEFORE UPDATE ON documents
FOR EACH ROW EXECUTE FUNCTION update_documents_updated_at();

-- ============================================================================
-- 인덱스
-- ============================================================================

-- 사용자별 문서 목록 조회 (가장 빈번한 쿼리 패턴)
CREATE INDEX IF NOT EXISTS idx_documents_user_id
    ON documents(user_id);

-- 처리 상태 필터 (processing_status IN ('pending','processing') 폴링)
CREATE INDEX IF NOT EXISTS idx_documents_processing_status
    ON documents(processing_status);

-- 최신순 정렬 (created_at DESC)
CREATE INDEX IF NOT EXISTS idx_documents_created_at
    ON documents(created_at DESC);

-- 벡터 검색 대상 문서 필터 (document_service.py 에서 WHERE embedding_processed = true)
CREATE INDEX IF NOT EXISTS idx_documents_embedding_processed
    ON documents(embedding_processed)
    WHERE embedding_processed = TRUE;

-- 중복 업로드 감지 (file_hash 유니크)
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_file_hash
    ON documents(file_hash)
    WHERE file_hash IS NOT NULL;

-- 사용자 + 상태 복합 조회 (목록 API의 주요 쿼리 패턴)
CREATE INDEX IF NOT EXISTS idx_documents_user_status
    ON documents(user_id, processing_status);

-- ============================================================================
-- FK 보완: document_chunks.document_id → documents(id)
-- (028_create_document_chunks.sql 에서 보류된 제약을 여기서 추가)
-- ============================================================================
DO $$
BEGIN
    -- document_chunks 테이블이 존재하고 FK가 아직 없는 경우에만 추가
    IF EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'document_chunks'
    ) AND NOT EXISTS (
        SELECT FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_document_chunks_document_id'
          AND table_name    = 'document_chunks'
          AND table_schema  = 'public'
    ) THEN
        ALTER TABLE document_chunks
            ADD CONSTRAINT fk_document_chunks_document_id
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE;
        RAISE NOTICE 'Added FK: document_chunks.document_id → documents(id)';
    END IF;
END $$;

DO $$
BEGIN
    RAISE NOTICE '================================================================';
    RAISE NOTICE 'Migration 029 완료: documents 테이블 생성';
    RAISE NOTICE '  - 27개 컬럼 (ORM Document 모델 완전 반영)';
    RAISE NOTICE '  - 6개 인덱스 (일반 × 4, 부분 × 1, 유니크 부분 × 1)';
    RAISE NOTICE '  - updated_at 자동 갱신 트리거';
    RAISE NOTICE '  - document_chunks.document_id FK 제약 추가 (보류분 해소)';
    RAISE NOTICE '================================================================';
END $$;

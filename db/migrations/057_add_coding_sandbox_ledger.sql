-- 코딩 SandboxProvider(B2)의 durable NEOS ledger.
--
-- 관리형 할당 평면(045 `coding_managed_sandboxes`)과는 **별개**다. 그 테이블은
-- admission/quota 가 사는 할당 원장이고, 이 테이블은 코딩 루프가 여는 샌드박스
-- 하나하나의 owner / generation / revision / idempotency / destroy 확인을 적는다.
-- vendor metadata/tag 는 재발견 인덱스일 뿐 SoT 가 아니다
-- (docs/MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md §6, §8.1).
--
-- 규칙:
--   * 행은 provider create **전에** 기록한다 (state = 'creating').
--   * 모든 변경은 owner_id + generation + version 을 대조한다.
--   * destroy 결과가 불명확하면 'destroy_pending' 에 남는다. 요청 전송을 삭제
--     확인으로 적지 않는다 -- 'destroyed' 는 destroy_confirmed_at 과 함께만 온다.
--   * provider 참조는 AES-GCM 으로 봉인한 BYTEA 다 (neos/coding/managed/crypto.py).
--
-- owner_id 는 coding task id 이지만 FK 를 걸지 않는다: SandboxProvider 계약의
-- owner 는 task 에 한정되지 않고, 샌드박스 원장 행은 task 가 지워진 뒤에도
-- 정리 확인이 끝날 때까지 남아 있어야 한다.

BEGIN;

CREATE TABLE IF NOT EXISTS coding_sandbox_ledger (
    sandbox_id VARCHAR(64) PRIMARY KEY,
    owner_id VARCHAR(255) NOT NULL,
    task_id VARCHAR(255) NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    generation INTEGER NOT NULL CHECK (generation > 0),
    allocation_id VARCHAR(64) NOT NULL UNIQUE,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    ownership_digest VARCHAR(128) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    provider_ref BYTEA,
    image_digest VARCHAR(255) NOT NULL,
    sandboxd_digest VARCHAR(80) NOT NULL,
    profile VARCHAR(64) NOT NULL,
    network_policy JSONB NOT NULL,
    region VARCHAR(64) NOT NULL,
    limits JSONB NOT NULL,
    state VARCHAR(24) NOT NULL CHECK (state IN (
        'creating', 'running', 'suspended', 'quarantined', 'failed',
        'destroy_pending', 'destroyed'
    )),
    source_snapshot_id VARCHAR(64),
    resume_snapshot_ref BYTEA,
    resume_snapshot_expires_at TIMESTAMPTZ,
    workspace_revision BIGINT NOT NULL DEFAULT 0
        CHECK (workspace_revision >= 0),
    stream_cursors JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_code VARCHAR(64),
    expires_at TIMESTAMPTZ NOT NULL,
    version BIGINT NOT NULL CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    destroy_requested_at TIMESTAMPTZ,
    destroy_confirmed_at TIMESTAMPTZ,
    UNIQUE (owner_id, task_id, ordinal),
    CHECK (expires_at > created_at),
    CHECK ((state = 'destroyed') = (destroy_confirmed_at IS NOT NULL)),
    CHECK (state <> 'destroyed' OR provider_ref IS NULL),
    CHECK (state <> 'destroy_pending' OR destroy_requested_at IS NOT NULL)
);

-- 리퍼(destroy_pending 재확인)와 격리 차단 조회.
CREATE INDEX IF NOT EXISTS idx_coding_sandbox_ledger_attention
    ON coding_sandbox_ledger (state, updated_at)
    WHERE state IN ('creating', 'quarantined', 'destroy_pending');

CREATE INDEX IF NOT EXISTS idx_coding_sandbox_ledger_owner
    ON coding_sandbox_ledger (owner_id, task_id, state);

-- provider snapshot 은 portable archive 가 아니다. provider snapshot id 와 NEOS
-- checksum / owner / generation / TTL 을 여기 따로 둔다 (§2.1 restore, §6-6).
CREATE TABLE IF NOT EXISTS coding_sandbox_ledger_snapshots (
    snapshot_id VARCHAR(64) PRIMARY KEY,
    sandbox_id VARCHAR(64) NOT NULL
        REFERENCES coding_sandbox_ledger(sandbox_id) ON DELETE RESTRICT,
    owner_id VARCHAR(255) NOT NULL,
    generation INTEGER NOT NULL CHECK (generation > 0),
    provider VARCHAR(32) NOT NULL,
    provider_snapshot_ref BYTEA NOT NULL,
    workspace_revision BIGINT NOT NULL CHECK (workspace_revision >= 0),
    content_checksum VARCHAR(80) NOT NULL,
    image_digest VARCHAR(255) NOT NULL,
    profile VARCHAR(64) NOT NULL,
    region VARCHAR(64) NOT NULL,
    limits JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    CHECK (expires_at IS NULL OR expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS idx_coding_sandbox_ledger_snapshots_sandbox
    ON coding_sandbox_ledger_snapshots (sandbox_id, created_at DESC);

COMMIT;

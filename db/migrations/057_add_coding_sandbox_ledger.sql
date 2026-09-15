-- 관리형 코딩 SandboxProvider(B2)의 durable runtime ledger.
--
-- 관리형 할당 평면(045 `coding_managed_sandboxes`)이 admission / quota / vendor
-- object 생성 / cleanup 을 소유한다. 이 마이그레이션은 **그 할당에 붙는** 코딩
-- 런타임만 적는다 -- 두 번째 할당 원장이 아니다. vendor metadata/tag 는 재발견
-- 인덱스일 뿐 SoT 가 아니다 (docs/MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md §6, §8.1).
--
-- 규칙:
--   * runtime 행은 할당 **전에** 'intent' 로 기록한다. 할당 어댑터는 intent 없이
--     vendor object 를 만들지 않는다.
--   * physical 행은 vendor create **전에** 'creating' 으로 기록한다.
--   * 할당 generation(admission 세대)과 incarnation(vendor object 교체)은 다른
--     값이다. Modal cold resume 은 incarnation 만 올리고, 같은 트랜잭션에서
--     045 의 provider_ref 봉인을 새 object 로 바꾼다.
--   * destroy 결과가 불명확하면 'destroy_pending' 에 남는다. 'destroyed' 는
--     destroy_confirmed_at 과 함께만 온다.
--   * provider 참조는 AES-GCM 으로 봉인한 BYTEA 다 (neos/coding/managed/crypto.py).
--     ref 로 행을 찾아야 하는 곳은 키 있는 색인(ref_index)을 쓴다 -- 평문 ref 는
--     어디에도 저장하지 않는다.

BEGIN;

CREATE TABLE IF NOT EXISTS coding_managed_runtime (
    sandbox_id VARCHAR(64) PRIMARY KEY,
    allocation_id VARCHAR(64) NOT NULL UNIQUE
        REFERENCES coding_managed_sandboxes(allocation_id) ON DELETE RESTRICT,
    allocation_generation INTEGER NOT NULL CHECK (allocation_generation > 0),
    tenant_id VARCHAR(255) NOT NULL,
    task_id VARCHAR(64) NOT NULL
        REFERENCES coding_tasks(task_id) ON DELETE RESTRICT,
    owner_id VARCHAR(255) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    image_digest VARCHAR(255) NOT NULL,
    sandboxd_digest VARCHAR(80) NOT NULL,
    profile VARCHAR(64) NOT NULL,
    network_policy JSONB NOT NULL,
    region VARCHAR(64) NOT NULL,
    limits JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    state VARCHAR(24) NOT NULL CHECK (state IN (
        'intent', 'running', 'suspended', 'quarantined', 'failed', 'detached'
    )),
    incarnation INTEGER NOT NULL CHECK (incarnation > 0),
    stream_epoch INTEGER NOT NULL CHECK (stream_epoch > 0),
    workspace_revision BIGINT NOT NULL DEFAULT 0
        CHECK (workspace_revision >= 0),
    stream_cursors JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_snapshot_id VARCHAR(64),
    resume_snapshot_ref BYTEA,
    resume_snapshot_expires_at TIMESTAMPTZ,
    error_code VARCHAR(64),
    version BIGINT NOT NULL CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CHECK (expires_at > created_at),
    CHECK (resume_snapshot_expires_at IS NULL OR resume_snapshot_ref IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_coding_managed_runtime_task
    ON coding_managed_runtime (task_id, state);

CREATE TABLE IF NOT EXISTS coding_managed_physical_objects (
    sandbox_id VARCHAR(64) NOT NULL
        REFERENCES coding_managed_runtime(sandbox_id) ON DELETE RESTRICT,
    incarnation INTEGER NOT NULL CHECK (incarnation > 0),
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    ownership_digest VARCHAR(128) NOT NULL,
    provider_ref BYTEA,
    ref_index VARCHAR(64) UNIQUE,
    state VARCHAR(24) NOT NULL CHECK (state IN (
        'creating', 'active', 'destroy_pending', 'destroyed'
    )),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    destroy_requested_at TIMESTAMPTZ,
    destroy_confirmed_at TIMESTAMPTZ,
    PRIMARY KEY (sandbox_id, incarnation),
    CHECK ((provider_ref IS NULL) = (ref_index IS NULL)),
    CHECK ((state = 'destroyed') = (destroy_confirmed_at IS NOT NULL)),
    CHECK (state <> 'destroy_pending' OR destroy_requested_at IS NOT NULL),
    CHECK (state <> 'active' OR provider_ref IS NOT NULL)
);

-- 논리 샌드박스당 살아 있는 vendor object 는 하나다.
CREATE UNIQUE INDEX IF NOT EXISTS idx_coding_managed_physical_active
    ON coding_managed_physical_objects (sandbox_id)
    WHERE state = 'active';

-- 리퍼(destroy_pending 재확인).
CREATE INDEX IF NOT EXISTS idx_coding_managed_physical_attention
    ON coding_managed_physical_objects (state, updated_at)
    WHERE state IN ('creating', 'destroy_pending');

-- provider snapshot 은 portable archive 가 아니다. provider snapshot id 와 NEOS
-- checksum / 출처 allocation / incarnation / TTL 을 따로 둔다 (§2.1 restore, §6-6).
CREATE TABLE IF NOT EXISTS coding_managed_runtime_snapshots (
    snapshot_id VARCHAR(64) PRIMARY KEY,
    sandbox_id VARCHAR(64) NOT NULL
        REFERENCES coding_managed_runtime(sandbox_id) ON DELETE RESTRICT,
    allocation_id VARCHAR(64) NOT NULL,
    task_id VARCHAR(64) NOT NULL,
    incarnation INTEGER NOT NULL CHECK (incarnation > 0),
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

CREATE INDEX IF NOT EXISTS idx_coding_managed_runtime_snapshots_task
    ON coding_managed_runtime_snapshots (task_id, created_at DESC);

COMMIT;

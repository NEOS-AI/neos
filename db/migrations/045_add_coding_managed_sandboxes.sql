BEGIN;

CREATE TABLE coding_sandbox_admissions (
    admission_id VARCHAR(64) PRIMARY KEY,
    idempotency_key VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(255) NOT NULL,
    task_id VARCHAR(64) NOT NULL
        REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    provider VARCHAR(64) NOT NULL,
    region VARCHAR(64) NOT NULL,
    policy_version VARCHAR(64) NOT NULL,
    decision VARCHAR(16) NOT NULL
        CHECK (decision IN ('admitted', 'denied')),
    reason VARCHAR(32) NOT NULL CHECK (reason IN (
        'allowed', 'kill_switch', 'tenant_not_allowed',
        'repository_not_allowed', 'quota_exceeded', 'budget_exceeded',
        'provider_degraded', 'provider_unavailable', 'region_unavailable'
    )),
    reservation_id VARCHAR(64),
    reservation_expires_at TIMESTAMPTZ,
    reserved_active_seconds BIGINT NOT NULL DEFAULT 0
        CHECK (reserved_active_seconds >= 0),
    reserved_archive_bytes BIGINT NOT NULL DEFAULT 0
        CHECK (reserved_archive_bytes >= 0),
    reserved_cost_micros BIGINT NOT NULL DEFAULT 0
        CHECK (reserved_cost_micros >= 0),
    reservation_state VARCHAR(16) NOT NULL DEFAULT 'unreserved'
        CHECK (reservation_state IN (
            'unreserved', 'reserved', 'settled', 'released'
        )),
    actual_active_seconds BIGINT NOT NULL DEFAULT 0
        CHECK (actual_active_seconds >= 0),
    actual_archive_bytes BIGINT NOT NULL DEFAULT 0
        CHECK (actual_archive_bytes >= 0),
    actual_cost_micros BIGINT NOT NULL DEFAULT 0
        CHECK (actual_cost_micros >= 0),
    reservation_settled_at TIMESTAMPTZ,
    reservation_released_at TIMESTAMPTZ,
    reevaluate_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (tenant_id, idempotency_key),
    CHECK (
        (decision = 'admitted' AND reservation_id IS NOT NULL
            AND reservation_expires_at IS NOT NULL
            AND reservation_state IN ('reserved', 'settled', 'released'))
        OR (decision = 'denied' AND reservation_id IS NULL
            AND reservation_expires_at IS NULL
            AND reservation_state = 'unreserved')
    )
);

CREATE TABLE coding_managed_sandboxes (
    allocation_id VARCHAR(64) PRIMARY KEY,
    admission_id VARCHAR(64) NOT NULL UNIQUE
        REFERENCES coding_sandbox_admissions(admission_id) ON DELETE RESTRICT,
    tenant_id VARCHAR(255) NOT NULL,
    task_id VARCHAR(64) NOT NULL
        REFERENCES coding_tasks(task_id) ON DELETE RESTRICT,
    run_id VARCHAR(64) NOT NULL
        REFERENCES coding_runs(run_id) ON DELETE RESTRICT,
    provider VARCHAR(64) NOT NULL,
    region VARCHAR(64) NOT NULL,
    provider_ref BYTEA,
    ownership_digest VARCHAR(128),
    state VARCHAR(32) NOT NULL CHECK (state IN (
        'requested', 'admitted', 'allocating', 'active', 'suspended',
        'recovery_pending', 'manual_recovery_required', 'cleanup_pending',
        'cleanup_retry', 'cleaned', 'failed'
    )),
    generation INTEGER NOT NULL CHECK (generation > 0),
    fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
    lease_expires_at TIMESTAMPTZ,
    absolute_expires_at TIMESTAMPTZ NOT NULL,
    version BIGINT NOT NULL CHECK (version > 0),
    error_code VARCHAR(32) CHECK (error_code IS NULL OR error_code IN (
        'provider_timeout', 'provider_rate_limited', 'provider_server_error',
        'provider_auth_error', 'provider_capacity', 'provider_not_found',
        'quota_exceeded', 'policy_denied', 'cleanup_unconfirmed',
        'archive_invalid', 'other'
    )),
    snapshot_ref VARCHAR(512),
    archive_ref VARCHAR(512),
    image_identity VARCHAR(255),
    toolchain_identity VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    cleaned_at TIMESTAMPTZ,
    CHECK (absolute_expires_at > created_at),
    CHECK (lease_expires_at IS NULL OR lease_expires_at <= absolute_expires_at),
    CHECK (state = 'cleaned' OR cleaned_at IS NULL),
    CHECK (
        state <> 'cleaned' OR (
            provider_ref IS NULL AND ownership_digest IS NULL
            AND lease_expires_at IS NULL AND cleaned_at IS NOT NULL
        )
    )
);

CREATE UNIQUE INDEX idx_coding_managed_sandboxes_current_task
ON coding_managed_sandboxes(task_id)
WHERE cleaned_at IS NULL
  AND state NOT IN ('cleaned', 'failed');

CREATE TABLE coding_sandbox_cleanup_attempts (
    cleanup_attempt_id VARCHAR(64) PRIMARY KEY,
    allocation_id VARCHAR(64) NOT NULL
        REFERENCES coding_managed_sandboxes(allocation_id) ON DELETE CASCADE,
    claimed_fencing_token BIGINT NOT NULL CHECK (claimed_fencing_token > 0),
    outcome VARCHAR(32) NOT NULL CHECK (outcome IN (
        'cleaned', 'retry', 'unconfirmed'
    )),
    error_code VARCHAR(32) CHECK (error_code IS NULL OR error_code IN (
        'provider_timeout', 'provider_rate_limited', 'provider_server_error',
        'provider_auth_error', 'provider_capacity', 'provider_not_found',
        'quota_exceeded', 'policy_denied', 'cleanup_unconfirmed',
        'archive_invalid', 'other'
    )),
    next_retry_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ
);

CREATE INDEX idx_coding_sandbox_cleanup_attempts_pending
    ON coding_sandbox_cleanup_attempts(allocation_id, next_retry_at)
    WHERE finished_at IS NULL;

COMMIT;

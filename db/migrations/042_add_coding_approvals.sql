BEGIN;

CREATE TABLE IF NOT EXISTS coding_approvals (
    approval_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL
        REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id VARCHAR(64) NOT NULL
        REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    tool_call_id VARCHAR(128) NOT NULL,
    checkpoint_id VARCHAR(64) NOT NULL
        REFERENCES coding_checkpoints(checkpoint_id) ON DELETE CASCADE,
    tool_name VARCHAR(128) NOT NULL,
    risk VARCHAR(32) NOT NULL
        CHECK (risk IN ('workspace_write', 'command')),
    workspace_revision VARCHAR(128) NOT NULL,
    request_hash CHAR(64) NOT NULL
        CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    display_summary JSONB NOT NULL
        CHECK (jsonb_typeof(display_summary) = 'object'),
    status VARCHAR(32) NOT NULL
        CHECK (status IN (
            'pending', 'approved', 'denied', 'expired', 'invalidated'
        )),
    requested_by VARCHAR(255) NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    decision VARCHAR(16)
        CHECK (decision IS NULL OR decision IN ('approve', 'deny')),
    decided_by VARCHAR(255),
    decided_at TIMESTAMPTZ,
    UNIQUE (task_id, run_id, tool_call_id),
    CHECK (expires_at > requested_at),
    CHECK (
        (status = 'pending'
            AND decision IS NULL
            AND decided_by IS NULL
            AND decided_at IS NULL)
        OR (status = 'approved'
            AND decision = 'approve'
            AND decided_by IS NOT NULL
            AND decided_at IS NOT NULL)
        OR (status = 'denied'
            AND decision = 'deny'
            AND decided_by IS NOT NULL
            AND decided_at IS NOT NULL)
        OR (status IN ('expired', 'invalidated')
            AND decision IS NULL
            AND decided_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_coding_approvals_pending_expiry
    ON coding_approvals (expires_at, approval_id)
    WHERE status = 'pending';

COMMIT;

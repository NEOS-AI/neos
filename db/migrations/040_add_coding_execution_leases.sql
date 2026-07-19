CREATE TABLE IF NOT EXISTS coding_run_leases (
    task_id VARCHAR(64) PRIMARY KEY
        REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id VARCHAR(64) NOT NULL
        REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    worker_id VARCHAR(128) NOT NULL,
    fencing_token BIGINT NOT NULL CHECK (fencing_token > 0),
    acquired_at TIMESTAMPTZ NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    UNIQUE (task_id, run_id, fencing_token)
);

ALTER TABLE coding_steering_requests
    ADD COLUMN IF NOT EXISTS claimed_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS claim_expires_at TIMESTAMPTZ;

ALTER TABLE coding_tool_executions
    ADD COLUMN IF NOT EXISTS worker_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS fencing_token BIGINT,
    ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS claim_expires_at TIMESTAMPTZ;

ALTER TABLE coding_tool_executions
    DROP CONSTRAINT IF EXISTS coding_tool_executions_status_check;
ALTER TABLE coding_tool_executions
    ADD CONSTRAINT coding_tool_executions_status_check
    CHECK (status IN ('claimed', 'completed', 'failed'));

CREATE INDEX IF NOT EXISTS idx_coding_run_leases_expiry
    ON coding_run_leases(expires_at);
CREATE INDEX IF NOT EXISTS idx_coding_steering_claimable
    ON coding_steering_requests(task_id, claim_expires_at, requested_at)
    WHERE status IN ('pending', 'claimed');

CREATE TABLE IF NOT EXISTS coding_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    status VARCHAR(32) NOT NULL,
    resume_from_checkpoint_id VARCHAR(64),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    UNIQUE (task_id, attempt)
);

CREATE TABLE IF NOT EXISTS coding_checkpoints (
    checkpoint_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id VARCHAR(64) NOT NULL REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    seq BIGINT NOT NULL,
    loop_state_json JSONB NOT NULL,
    workspace_revision VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (task_id, seq)
);

ALTER TABLE coding_events
    ADD COLUMN IF NOT EXISTS checkpoint_id VARCHAR(64)
    REFERENCES coding_checkpoints(checkpoint_id);

ALTER TABLE coding_runs
    ADD CONSTRAINT fk_coding_runs_resume_checkpoint
    FOREIGN KEY (resume_from_checkpoint_id)
    REFERENCES coding_checkpoints(checkpoint_id);

CREATE TABLE IF NOT EXISTS coding_phases (
    phase_id VARCHAR(128) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id VARCHAR(64) NOT NULL REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    phase_kind VARCHAR(32) NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    status VARCHAR(32) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    UNIQUE (task_id, phase_kind, attempt)
);

CREATE TABLE IF NOT EXISTS coding_tool_executions (
    task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    tool_call_id VARCHAR(128) NOT NULL,
    run_id VARCHAR(64) NOT NULL REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL,
    result_json JSONB,
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (task_id, tool_call_id),
    UNIQUE (task_id, tool_call_id)
);

CREATE TABLE IF NOT EXISTS coding_steering_requests (
    steering_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    mode VARCHAR(32) NOT NULL,
    instruction TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    applied_checkpoint_id VARCHAR(64) REFERENCES coding_checkpoints(checkpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_coding_runs_task_attempt
    ON coding_runs(task_id, attempt DESC);
CREATE INDEX IF NOT EXISTS idx_coding_checkpoints_task_seq
    ON coding_checkpoints(task_id, seq DESC);
CREATE INDEX IF NOT EXISTS idx_coding_steering_pending
    ON coding_steering_requests(task_id, requested_at)
    WHERE status = 'pending';

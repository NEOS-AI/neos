CREATE TABLE IF NOT EXISTS coding_sandbox_bindings (
    task_id VARCHAR(64) PRIMARY KEY REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id VARCHAR(64) NOT NULL REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    sandbox_id VARCHAR(128) NOT NULL UNIQUE,
    provider VARCHAR(32) NOT NULL,
    image_digest VARCHAR(255),
    workspace_revision VARCHAR(128) NOT NULL,
    latest_snapshot_id VARCHAR(128),
    health_state VARCHAR(32) NOT NULL,
    mutation_count INTEGER NOT NULL DEFAULT 0 CHECK (mutation_count >= 0),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (task_id)
);

CREATE TABLE IF NOT EXISTS channel_coding_bindings (
    session_id VARCHAR(255) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    owner_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_channel_coding_bindings_task
    ON channel_coding_bindings(task_id);

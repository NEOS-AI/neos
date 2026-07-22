BEGIN;

CREATE TABLE IF NOT EXISTS coding_text_parts (
    part_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL,
    first_seq BIGINT NOT NULL,
    last_seq BIGINT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('streaming', 'completed', 'interrupted')),
    content TEXT NOT NULL DEFAULT '',
    content_bytes BIGINT NOT NULL DEFAULT 0 CHECK (content_bytes >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (task_id, turn_id),
    CHECK (first_seq > 0 AND last_seq >= first_seq)
);

CREATE INDEX IF NOT EXISTS idx_coding_text_parts_task_first_seq
    ON coding_text_parts(task_id, first_seq, part_id);

CREATE INDEX IF NOT EXISTS idx_coding_text_parts_task_status
    ON coding_text_parts(task_id, status);

COMMIT;

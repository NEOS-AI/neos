BEGIN;

CREATE TABLE IF NOT EXISTS coding_tasks (
    task_id VARCHAR(64) PRIMARY KEY,
    owner_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    last_seq BIGINT NOT NULL DEFAULT 0 CHECK (last_seq >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_coding_tasks_owner_activity
    ON coding_tasks(owner_id, last_activity_at DESC)
    WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS coding_events (
    event_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    seq BIGINT NOT NULL CHECK (seq > 0),
    version SMALLINT NOT NULL DEFAULT 1 CHECK (version > 0),
    event_type VARCHAR(128) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    run_id VARCHAR(64) NULL,
    turn_id VARCHAR(64) NULL,
    tool_call_id VARCHAR(128) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (task_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_coding_events_task_seq
    ON coding_events(task_id, seq);
CREATE INDEX IF NOT EXISTS idx_coding_events_run_created
    ON coding_events(run_id, created_at)
    WHERE run_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS coding_event_outbox (
    outbox_id VARCHAR(64) PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL UNIQUE
        REFERENCES coding_events(event_id) ON DELETE CASCADE,
    task_id VARCHAR(64) NOT NULL
        REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    seq BIGINT NOT NULL CHECK (seq > 0),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at TIMESTAMPTZ NULL,
    published_at TIMESTAMPTZ NULL,
    last_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coding_outbox_eligible
    ON coding_event_outbox(next_attempt_at, created_at)
    WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_coding_outbox_task_seq
    ON coding_event_outbox(task_id, seq);

COMMIT;

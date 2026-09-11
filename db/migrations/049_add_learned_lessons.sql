CREATE TABLE IF NOT EXISTS learned_lessons (
    lesson_id VARCHAR(64) PRIMARY KEY,
    namespace VARCHAR(255) NOT NULL,
    title VARCHAR(255) NOT NULL,
    body TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    pinned BOOLEAN NOT NULL DEFAULT FALSE,
    kind VARCHAR(32) NOT NULL DEFAULT 'fact',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_learned_lessons_ns_status
    ON learned_lessons(namespace, status);

-- Migration 011: Add independent research_sessions table
--
-- Decouples session management from langgraph_checkpoints internal schema.
-- Previously, session metadata was read directly from checkpoint_data JSONB,
-- which is fragile and version-dependent. This table provides stable,
-- independently managed session metadata.

CREATE TABLE IF NOT EXISTS research_sessions (
    session_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id    TEXT NOT NULL UNIQUE,     -- langgraph checkpoint thread_id reference (ON CONFLICT 사용을 위해 UNIQUE 필수)
    user_id      TEXT NOT NULL,
    original_query TEXT,
    status       TEXT NOT NULL DEFAULT 'active',  -- active, completed, failed
    metadata     JSONB DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_research_sessions_user ON research_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_research_sessions_thread ON research_sessions(thread_id);
CREATE INDEX IF NOT EXISTS idx_research_sessions_status ON research_sessions(user_id, status);

-- Update research_session_branches to reference the new table
-- (backwards-compatible: no FK constraint to avoid blocking if old data exists)

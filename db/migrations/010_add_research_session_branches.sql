-- Migration 010: Add Research Session Branches table
--
-- Stores branching metadata for research sessions.
-- The actual checkpoint data is in langgraph_checkpoints table.

CREATE TABLE IF NOT EXISTS research_session_branches (
    id                SERIAL PRIMARY KEY,
    branch_session_id VARCHAR(255) UNIQUE NOT NULL,
    parent_session_id VARCHAR(255) NOT NULL,
    user_id           VARCHAR(255) NOT NULL,
    branch_query      TEXT,
    title             VARCHAR(500),
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rsb_user_id ON research_session_branches(user_id);
CREATE INDEX IF NOT EXISTS idx_rsb_parent_session ON research_session_branches(parent_session_id);

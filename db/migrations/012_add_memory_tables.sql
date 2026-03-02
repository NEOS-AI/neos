-- Migration 012: Add memory system tables (Phase 2.1)
--
-- 3-tier memory architecture:
-- 1. Short-term: Redis (no SQL needed)
-- 2. Long-term: pgvector semantic search for user knowledge
-- 3. Episodic: Timestamped research session history

-- Long-term memories: user knowledge, preferences, learned facts
CREATE TABLE IF NOT EXISTS long_term_memories (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    key VARCHAR(512) NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, key)
);

CREATE INDEX IF NOT EXISTS idx_ltm_user ON long_term_memories(user_id);
CREATE INDEX IF NOT EXISTS idx_ltm_embedding ON long_term_memories
    USING hnsw(embedding vector_cosine_ops);

-- Episodic memories: complete research sessions with results
CREATE TABLE IF NOT EXISTS episodic_memories (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255),
    query TEXT NOT NULL,
    key_findings TEXT,
    sources_used JSONB DEFAULT '[]',
    quality_score FLOAT DEFAULT 0.0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_em_user_time ON episodic_memories(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_em_session ON episodic_memories(session_id);

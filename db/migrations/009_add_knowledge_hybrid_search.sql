-- Migration 009: Add BM25 + Dense Vector Hybrid Search (RRF)
--
-- Adds tsvector column for BM25 text search on query_cache table,
-- and a PostgreSQL function for Reciprocal Rank Fusion (RRF) scoring.

-- 1. Add tsvector column for BM25 search
ALTER TABLE query_cache ADD COLUMN IF NOT EXISTS
    content_tsvector tsvector
    GENERATED ALWAYS AS (
        to_tsvector('english', COALESCE(query_text, ''))
    ) STORED;

-- 2. Create GIN index for fast text search
CREATE INDEX IF NOT EXISTS idx_query_cache_tsvector
    ON query_cache USING GIN (content_tsvector);

-- 3. RRF (Reciprocal Rank Fusion) hybrid search function
CREATE OR REPLACE FUNCTION knowledge_hybrid_search_rrf(
    p_query        TEXT,
    p_query_vector vector,
    p_alpha        FLOAT DEFAULT 0.5,   -- 0=pure keyword, 1=pure semantic
    p_top_n        INT   DEFAULT 50,    -- candidate count
    p_rrf_k        INT   DEFAULT 60     -- RRF constant (standard value)
)
RETURNS TABLE (
    cache_id       INTEGER,
    query_text     TEXT,
    response_data  JSONB,
    rrf_score      FLOAT,
    bm25_rank      INTEGER,
    vector_rank    INTEGER
) AS $$
WITH bm25_results AS (
    SELECT
        qc.id,
        qc.query_text,
        qc.response_data,
        ROW_NUMBER() OVER (
            ORDER BY ts_rank_cd(qc.content_tsvector, plainto_tsquery('english', p_query)) DESC
        )::INTEGER AS bm25_rank
    FROM query_cache qc
    WHERE qc.content_tsvector @@ plainto_tsquery('english', p_query)
      AND qc.expires_at > NOW()
    LIMIT p_top_n
),
vector_results AS (
    SELECT
        qc.id,
        qc.query_text,
        qc.response_data,
        ROW_NUMBER() OVER (
            ORDER BY qc.query_vector <=> p_query_vector ASC
        )::INTEGER AS vector_rank
    FROM query_cache qc
    WHERE qc.query_vector IS NOT NULL
      AND qc.expires_at > NOW()
    LIMIT p_top_n
),
combined AS (
    SELECT
        COALESCE(b.id, v.id) AS id,
        COALESCE(b.query_text, v.query_text) AS query_text,
        COALESCE(b.response_data, v.response_data) AS response_data,
        COALESCE(b.bm25_rank, p_top_n + 1) AS bm25_rank,
        COALESCE(v.vector_rank, p_top_n + 1) AS vector_rank,
        -- RRF score: weighted combination
        (1.0 - p_alpha) * (1.0 / (p_rrf_k + COALESCE(b.bm25_rank, p_top_n + 1)))
        + p_alpha         * (1.0 / (p_rrf_k + COALESCE(v.vector_rank, p_top_n + 1)))
        AS rrf_score
    FROM bm25_results b
    FULL OUTER JOIN vector_results v ON b.id = v.id
)
SELECT
    c.id::INTEGER AS cache_id,
    c.query_text,
    c.response_data,
    c.rrf_score::FLOAT,
    c.bm25_rank::INTEGER,
    c.vector_rank::INTEGER
FROM combined c
ORDER BY c.rrf_score DESC
LIMIT p_top_n;
$$ LANGUAGE SQL STABLE;

-- 4. Comment
COMMENT ON FUNCTION knowledge_hybrid_search_rrf IS
    'Hybrid search combining BM25 (tsvector) and dense vector (pgvector) using Reciprocal Rank Fusion. Alpha controls the weight: 0=pure keyword, 1=pure semantic.';

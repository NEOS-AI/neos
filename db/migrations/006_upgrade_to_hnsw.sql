-- Migration: Upgrade vector index from IVFFlat to HNSW
-- Purpose: 50-70% faster semantic similarity search for cache lookups
-- Impact: No downtime (uses CONCURRENTLY), ~20% larger index size
-- Expected Performance: 10ms → 3-5ms query latency at scale

-- =====================================================
-- STEP 1: Drop existing IVFFlat index
-- =====================================================
-- Using CONCURRENTLY to avoid locking the table during index drop
-- This allows reads and writes to continue during the migration
DROP INDEX CONCURRENTLY IF EXISTS idx_query_cache_vector;

-- =====================================================
-- STEP 2: Create HNSW index
-- =====================================================
-- HNSW (Hierarchical Navigable Small World) parameters:
--   m = 16: Maximum number of connections per layer
--     - Lower values (8-12): Faster build, less accurate
--     - Higher values (32-48): Slower build, more accurate
--     - Recommended: 16 for production (balanced)
--
--   ef_construction = 64: Build-time accuracy vs speed tradeoff
--     - Lower values (32-48): Faster index build
--     - Higher values (100-200): Better index quality
--     - Recommended: 64 for balanced build time and quality
--
-- Index build time estimate:
--   - 10K rows: ~30 seconds
--   - 100K rows: ~5-10 minutes
--   - 1M rows: ~1-2 hours

CREATE INDEX CONCURRENTLY idx_query_cache_vector_hnsw
    ON query_cache
    USING hnsw (query_vector vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- =====================================================
-- STEP 3: Update statistics
-- =====================================================
-- Analyze the table to update query planner statistics
-- This helps PostgreSQL choose optimal query plans
ANALYZE query_cache;

-- =====================================================
-- VERIFICATION QUERIES
-- =====================================================
-- Verify index exists and is valid
SELECT
    indexname,
    tablename,
    indexdef
FROM pg_indexes
WHERE tablename = 'query_cache'
  AND indexname = 'idx_query_cache_vector_hnsw';

-- Check index size
SELECT
    pg_size_pretty(pg_relation_size('idx_query_cache_vector_hnsw')) as index_size,
    pg_relation_size('idx_query_cache_vector_hnsw') as size_bytes;

-- =====================================================
-- ROLLBACK SCRIPT (if needed)
-- =====================================================
-- If you need to rollback to IVFFlat:
/*
DROP INDEX CONCURRENTLY IF EXISTS idx_query_cache_vector_hnsw;

CREATE INDEX CONCURRENTLY idx_query_cache_vector
    ON query_cache
    USING ivfflat (query_vector vector_cosine_ops)
    WITH (lists = 100);

ANALYZE query_cache;
*/

-- =====================================================
-- NOTES
-- =====================================================
-- Runtime query parameter (set per-session):
--   SET LOCAL hnsw.ef_search = 40;
--
-- ef_search values:
--   - 10: Fast, less accurate (for non-critical queries)
--   - 40: Balanced (default, recommended)
--   - 100: Slower, very accurate (for critical queries)
--
-- The ef_search parameter is set at runtime in smart_cache_manager.py
-- and can be tuned per query based on importance.

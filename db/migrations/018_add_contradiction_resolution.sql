-- ============================================================================
-- Phase 4.1: Active Contradiction Resolution
-- evidence_contradictions 테이블에 해결(resolution) 컬럼 추가
-- ============================================================================

ALTER TABLE evidence_contradictions
    ADD COLUMN IF NOT EXISTS resolution_status VARCHAR(50) DEFAULT 'unresolved',
    ADD COLUMN IF NOT EXISTS resolution_reasoning TEXT,
    ADD COLUMN IF NOT EXISTS resolution_confidence FLOAT DEFAULT 0.0,
    ADD COLUMN IF NOT EXISTS winner_claim_id INT REFERENCES evidence_claims(claim_id),
    ADD COLUMN IF NOT EXISTS resolved_by VARCHAR(100),  -- 'llm_judge_gpt4o_mini', 'human', etc.
    ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_contradictions_status
    ON evidence_contradictions(resolution_status);

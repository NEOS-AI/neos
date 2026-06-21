-- Migration 034: Bi-temporal validity for evidence claims.

ALTER TABLE evidence_claims
    ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS replaced_by_claim_id INT REFERENCES evidence_claims(claim_id),
    ADD COLUMN IF NOT EXISTS invalidation_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_evidence_claims_current_valid
    ON evidence_claims(user_id, valid_from DESC)
    WHERE valid_to IS NULL;

CREATE INDEX IF NOT EXISTS idx_evidence_claims_valid_range
    ON evidence_claims(user_id, valid_from, valid_to);

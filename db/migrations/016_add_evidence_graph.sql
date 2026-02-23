-- ============================================================================
-- Phase 3.2: Persistent Evidence Graph
-- ============================================================================

-- 주장(Claim) 테이블 — FactChecker의 Claim 클래스 확장
CREATE TABLE IF NOT EXISTS evidence_claims (
    claim_id SERIAL PRIMARY KEY,
    claim_text TEXT NOT NULL,
    claim_type VARCHAR(50) NOT NULL,  -- fact, opinion, statistic, prediction
    confidence FLOAT DEFAULT 0.5,
    verification_status VARCHAR(50) DEFAULT 'unverified',  -- verified, disputed, unverified
    embedding vector(1536),
    user_id VARCHAR(255),
    session_id VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_claims_user ON evidence_claims(user_id);
CREATE INDEX IF NOT EXISTS idx_evidence_claims_session ON evidence_claims(session_id);
CREATE INDEX IF NOT EXISTS idx_evidence_claims_embedding ON evidence_claims
    USING hnsw(embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_evidence_claims_status ON evidence_claims(verification_status);

-- 증거 소스 테이블
CREATE TABLE IF NOT EXISTS evidence_sources (
    source_id SERIAL PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_title TEXT,
    source_type VARCHAR(50),  -- academic, news, government, wiki, etc.
    credibility_score FLOAT DEFAULT 0.5,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_url)
);

CREATE INDEX IF NOT EXISTS idx_evidence_sources_url ON evidence_sources(source_url);

-- 증거 체인 (claim-source 관계)
CREATE TABLE IF NOT EXISTS evidence_chains (
    chain_id SERIAL PRIMARY KEY,
    claim_id INT NOT NULL REFERENCES evidence_claims(claim_id) ON DELETE CASCADE,
    source_id INT NOT NULL REFERENCES evidence_sources(source_id) ON DELETE CASCADE,
    evidence_type VARCHAR(50) NOT NULL,  -- supporting, contradicting, contextual
    confidence FLOAT DEFAULT 0.5,
    supporting_claims INT[] DEFAULT '{}',
    contradicting_claims INT[] DEFAULT '{}',
    evidence_snippet TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(claim_id, source_id, evidence_type)
);

CREATE INDEX IF NOT EXISTS idx_evidence_chains_claim ON evidence_chains(claim_id);
CREATE INDEX IF NOT EXISTS idx_evidence_chains_source ON evidence_chains(source_id);

-- 모순 테이블
CREATE TABLE IF NOT EXISTS evidence_contradictions (
    contradiction_id SERIAL PRIMARY KEY,
    claim_id_1 INT NOT NULL REFERENCES evidence_claims(claim_id) ON DELETE CASCADE,
    claim_id_2 INT NOT NULL REFERENCES evidence_claims(claim_id) ON DELETE CASCADE,
    contradiction_type VARCHAR(100),
    severity VARCHAR(20),  -- low, medium, high
    explanation TEXT,
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (claim_id_1 < claim_id_2),
    UNIQUE(claim_id_1, claim_id_2)
);

CREATE INDEX IF NOT EXISTS idx_contradictions_claim1 ON evidence_contradictions(claim_id_1);
CREATE INDEX IF NOT EXISTS idx_contradictions_claim2 ON evidence_contradictions(claim_id_2);

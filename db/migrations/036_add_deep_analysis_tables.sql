-- Migration 036: Deep Analysis Harness (M0-M1)
-- PostgreSQL port of docs/DEEP_ANALYSIS_HARNESS_DESIGN.md.

CREATE TABLE IF NOT EXISTS deep_analysis_runs (
    id                   VARCHAR(8)   PRIMARY KEY,
    root_question        TEXT         NOT NULL,
    profile              VARCHAR(20)  NOT NULL DEFAULT 'default'
                         CHECK (profile IN ('dev', 'default')),
    status               VARCHAR(20)  NOT NULL DEFAULT 'running'
                         CHECK (status IN ('running', 'completed', 'failed')),
    user_id              VARCHAR(255) REFERENCES users(user_id) ON DELETE SET NULL,
    conversation_id      VARCHAR(255) REFERENCES conversations(conversation_id) ON DELETE SET NULL,
    assistant_message_id VARCHAR(255),
    report_path          TEXT,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Base.metadata.create_all() may have created the ORM table first. The legacy
-- conversations table is not part of Base.metadata, so backfill its FK here.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_da_runs_conversation'
    ) THEN
        ALTER TABLE deep_analysis_runs
            ADD CONSTRAINT fk_da_runs_conversation
            FOREIGN KEY (conversation_id)
            REFERENCES conversations(conversation_id)
            ON DELETE SET NULL;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS deep_analysis_questions (
    id           VARCHAR(8)  NOT NULL,
    run_id       VARCHAR(8)  NOT NULL REFERENCES deep_analysis_runs(id) ON DELETE CASCADE,
    parent_id    VARCHAR(8),
    text         TEXT        NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open', 'investigating', 'resolved', 'split', 'abandoned')),
    depth        INTEGER     NOT NULL CHECK (depth >= 0),
    value_est    REAL        NOT NULL CHECK (value_est >= 0 AND value_est <= 1),
    confidence   REAL        NOT NULL DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 1),
    spent_tokens INTEGER     NOT NULL DEFAULT 0 CHECK (spent_tokens >= 0),
    cap_tokens   INTEGER     NOT NULL CHECK (cap_tokens > 0),
    fail_streak  INTEGER     NOT NULL DEFAULT 0 CHECK (fail_streak >= 0),
    PRIMARY KEY (run_id, id),
    FOREIGN KEY (run_id, parent_id)
        REFERENCES deep_analysis_questions(run_id, id)
);

CREATE INDEX IF NOT EXISTS idx_da_questions_run_status
    ON deep_analysis_questions (run_id, status);

CREATE TABLE IF NOT EXISTS deep_analysis_claims (
    id          VARCHAR(8)  NOT NULL,
    run_id      VARCHAR(8)  NOT NULL REFERENCES deep_analysis_runs(id) ON DELETE CASCADE,
    question_id VARCHAR(8)  NOT NULL,
    text        TEXT        NOT NULL,
    hash        VARCHAR(16) NOT NULL,
    status      VARCHAR(12) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'verified', 'rejected', 'unverified')),
    confidence  REAL        NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    PRIMARY KEY (run_id, id),
    UNIQUE (run_id, hash),
    FOREIGN KEY (run_id, question_id)
        REFERENCES deep_analysis_questions(run_id, id)
);

CREATE INDEX IF NOT EXISTS idx_da_claims_run_question
    ON deep_analysis_claims (run_id, question_id);

CREATE TABLE IF NOT EXISTS deep_analysis_blobs (
    run_id       VARCHAR(8)  NOT NULL REFERENCES deep_analysis_runs(id) ON DELETE CASCADE,
    content_hash VARCHAR(16) NOT NULL,
    url          TEXT        NOT NULL,
    http_status  INTEGER     NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_text     TEXT,
    PRIMARY KEY (run_id, content_hash)
);

CREATE TABLE IF NOT EXISTS deep_analysis_evidence (
    id          VARCHAR(8)  PRIMARY KEY,
    run_id      VARCHAR(8)  NOT NULL REFERENCES deep_analysis_runs(id) ON DELETE CASCADE,
    claim_id    VARCHAR(8)  NOT NULL,
    source_url  TEXT        NOT NULL,
    excerpt     TEXT        NOT NULL,
    raw_ref     VARCHAR(16) NOT NULL,
    det_grade   VARCHAR(40),
    agent_grade VARCHAR(20),
    FOREIGN KEY (run_id, claim_id)
        REFERENCES deep_analysis_claims(run_id, id) ON DELETE CASCADE,
    FOREIGN KEY (run_id, raw_ref)
        REFERENCES deep_analysis_blobs(run_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_da_evidence_run_claim
    ON deep_analysis_evidence (run_id, claim_id);

CREATE TABLE IF NOT EXISTS deep_analysis_feedback (
    id        BIGSERIAL   PRIMARY KEY,
    run_id    VARCHAR(8)  NOT NULL REFERENCES deep_analysis_runs(id) ON DELETE CASCADE,
    claim_id  VARCHAR(8)  NOT NULL,
    code      VARCHAR(40) NOT NULL,
    detail    TEXT        NOT NULL,
    salvage   TEXT,
    attempt   INTEGER     NOT NULL CHECK (attempt > 0),
    resolved  INTEGER     NOT NULL DEFAULT 0 CHECK (resolved IN (0, 1)),
    FOREIGN KEY (run_id, claim_id)
        REFERENCES deep_analysis_claims(run_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_da_feedback_run_claim
    ON deep_analysis_feedback (run_id, claim_id, resolved);

CREATE TABLE IF NOT EXISTS deep_analysis_events (
    seq     BIGSERIAL   PRIMARY KEY,
    run_id  VARCHAR(8)  NOT NULL REFERENCES deep_analysis_runs(id) ON DELETE CASCADE,
    ts      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    kind    VARCHAR(40) NOT NULL,
    qid     VARCHAR(8),
    payload TEXT        NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_da_events_run_qid_kind
    ON deep_analysis_events (run_id, qid, kind);

CREATE OR REPLACE FUNCTION deep_analysis_events_reject_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'deep_analysis_events is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS deep_analysis_events_append_only ON deep_analysis_events;
CREATE TRIGGER deep_analysis_events_append_only
    BEFORE UPDATE OR DELETE ON deep_analysis_events
    FOR EACH ROW
    EXECUTE FUNCTION deep_analysis_events_reject_mutation();

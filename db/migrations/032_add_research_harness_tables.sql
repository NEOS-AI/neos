-- Migration 032: Dedicated Research Harness persistence
--
-- Raw check evidence is controlled by RESEARCH_HARNESS_EVIDENCE_STORAGE_POLICY.
-- The application default is summary-only storage; redacted or full evidence
-- should only be enabled after an explicit review of runtime data sensitivity.

CREATE TABLE IF NOT EXISTS research_harness_runs (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(255) UNIQUE NOT NULL,
    session_id VARCHAR(255),
    report_id VARCHAR(255),
    user_id VARCHAR(255),
    mode VARCHAR(50) NOT NULL,
    verdict VARCHAR(50) NOT NULL,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    risk_level VARCHAR(50),
    threshold DOUBLE PRECISION,
    repair_attempts INTEGER NOT NULL DEFAULT 0,
    failed_checks JSONB NOT NULL DEFAULT '[]',
    contract JSONB NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research_harness_check_results (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(255) NOT NULL,
    check_name VARCHAR(255) NOT NULL,
    passed BOOLEAN NOT NULL,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    severity VARCHAR(50) NOT NULL,
    summary TEXT,
    evidence JSONB NOT NULL DEFAULT '[]',
    failed_items JSONB NOT NULL DEFAULT '[]',
    repairable BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_research_harness_check_run
        FOREIGN KEY (run_id)
        REFERENCES research_harness_runs(run_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_research_harness_runs_session
    ON research_harness_runs(session_id);

CREATE INDEX IF NOT EXISTS idx_research_harness_runs_report
    ON research_harness_runs(report_id);

CREATE INDEX IF NOT EXISTS idx_research_harness_runs_verdict
    ON research_harness_runs(verdict);

CREATE INDEX IF NOT EXISTS idx_research_harness_checks_run
    ON research_harness_check_results(run_id);

CREATE INDEX IF NOT EXISTS idx_research_harness_checks_name
    ON research_harness_check_results(check_name);

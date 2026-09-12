CREATE TABLE IF NOT EXISTS subagent_runs (
    run_id                 VARCHAR(64) PRIMARY KEY,          -- sa_{hex}
    parent_kind            VARCHAR(32)  NOT NULL,            -- coding | deep_analysis
    parent_id              VARCHAR(64)  NOT NULL,
    parent_run_id          VARCHAR(64)  NOT NULL,
    parent_tool_call_id    VARCHAR(128) NOT NULL,
    lineage_kind           VARCHAR(32)  NOT NULL DEFAULT 'delegate',
    spec                   VARCHAR(32)  NOT NULL,
    status                 VARCHAR(32)  NOT NULL,            -- pending|running|completed|failed|killed
    provider               VARCHAR(32)  NOT NULL,
    model                  VARCHAR(128) NOT NULL,
    max_turns              INTEGER      NOT NULL CHECK (max_turns BETWEEN 1 AND 8),
    turn_count             INTEGER      NOT NULL DEFAULT 0,
    tool_count             INTEGER      NOT NULL DEFAULT 0,
    input_tokens           INTEGER      NOT NULL DEFAULT 0,
    output_tokens          INTEGER      NOT NULL DEFAULT 0,
    cost_micros            BIGINT       NOT NULL DEFAULT 0,
    briefing_json          JSONB        NOT NULL,
    error_code             VARCHAR(64),
    sandbox_mode           VARCHAR(32)  NOT NULL DEFAULT 'none',
    created_at             TIMESTAMPTZ  NOT NULL,
    updated_at             TIMESTAMPTZ  NOT NULL,
    completed_at           TIMESTAMPTZ,
    UNIQUE (parent_kind, parent_id, parent_tool_call_id),
    CHECK (lineage_kind IN ('delegate', 'compression', 'branch')),
    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'killed')),
    CHECK (parent_kind IN ('coding', 'deep_analysis'))
);

CREATE TABLE IF NOT EXISTS subagent_checkpoints (
    checkpoint_id   VARCHAR(64) PRIMARY KEY,                 -- sc_{hex}
    run_id          VARCHAR(64) NOT NULL
                    REFERENCES subagent_runs(run_id) ON DELETE CASCADE,
    seq             BIGINT      NOT NULL,
    loop_state_json JSONB       NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    UNIQUE (run_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_subagent_runs_parent
    ON subagent_runs (parent_kind, parent_id, status);
CREATE INDEX IF NOT EXISTS idx_subagent_ckpts_run_seq
    ON subagent_checkpoints (run_id, seq DESC);

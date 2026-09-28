-- GEPA opt runs, examples, candidates, scores, and overlays.
-- Idempotent. State is JSON rows, not a serialized interpreter dump.

CREATE TABLE IF NOT EXISTS gepa_opt_runs (
    run_id uuid PRIMARY KEY,
    owner_namespace text NOT NULL,
    surface text NOT NULL,
    engine_label text NOT NULL,
    pareto_enabled boolean NOT NULL,
    merge_enabled boolean NOT NULL CHECK (merge_enabled = false),
    status text NOT NULL,
    seed_candidate_id uuid NULL,
    best_candidate_id uuid NULL,
    max_evals integer NOT NULL,
    max_token_cost integer NOT NULL,
    evals_used integer NOT NULL DEFAULT 0,
    reflector_tokens_used integer NOT NULL DEFAULT 0,
    iteration integer NOT NULL DEFAULT 0,
    component_cursor integer NOT NULL DEFAULT 0,
    celery_task_id text NULL,
    error_code text NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz NULL
);

CREATE TABLE IF NOT EXISTS gepa_opt_examples (
    example_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES gepa_opt_runs (run_id),
    owner_namespace text NOT NULL,
    split text NOT NULL,
    ordinal integer NOT NULL,
    payload jsonb NOT NULL,
    UNIQUE (run_id, split, ordinal)
);

CREATE TABLE IF NOT EXISTS gepa_opt_candidates (
    candidate_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES gepa_opt_runs (run_id),
    owner_namespace text NOT NULL,
    parent_id uuid NULL,
    iteration integer NOT NULL,
    proposal_kind text NOT NULL,
    components jsonb NOT NULL,
    accepted boolean NOT NULL,
    reject_reason text NULL,
    val_mean double precision NULL,
    test_mean double precision NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, iteration, proposal_kind)
);

CREATE TABLE IF NOT EXISTS gepa_opt_example_scores (
    score_id uuid PRIMARY KEY,
    candidate_id uuid NOT NULL REFERENCES gepa_opt_candidates (candidate_id),
    example_id uuid NOT NULL REFERENCES gepa_opt_examples (example_id),
    owner_namespace text NOT NULL,
    split text NOT NULL,
    phase text NOT NULL,
    score double precision NOT NULL,
    side_info jsonb NOT NULL,
    UNIQUE (candidate_id, example_id, phase)
);

CREATE TABLE IF NOT EXISTS gepa_opt_overlays (
    overlay_id uuid PRIMARY KEY,
    owner_namespace text NOT NULL,
    surface text NOT NULL,
    status text NOT NULL,
    candidate_id uuid NOT NULL REFERENCES gepa_opt_candidates (candidate_id),
    run_id uuid NOT NULL REFERENCES gepa_opt_runs (run_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    approved_at timestamptz NULL,
    approved_by varchar(255) NULL,
    archived_at timestamptz NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS gepa_opt_overlays_one_approved
    ON gepa_opt_overlays (owner_namespace, surface)
    WHERE status = 'approved';

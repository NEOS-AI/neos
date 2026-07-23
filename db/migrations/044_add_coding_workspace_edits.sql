BEGIN;

CREATE TABLE IF NOT EXISTS coding_workspace_edits (
    edit_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    base_revision TEXT NOT NULL,
    resulting_revision TEXT,
    status TEXT NOT NULL CHECK (status IN ('prepared', 'committed', 'reconcile_required', 'applied')),
    content_digest TEXT NOT NULL,
    content_bytes BIGINT NOT NULL CHECK (content_bytes >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    committed_at TIMESTAMPTZ,
    applied_checkpoint_id TEXT REFERENCES coding_checkpoints(checkpoint_id)
        ON DELETE SET NULL,
    CHECK (
        status NOT IN ('committed', 'applied')
        OR (resulting_revision IS NOT NULL AND committed_at IS NOT NULL)
    ),
    CHECK (
        status != 'applied'
        OR applied_checkpoint_id IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_coding_workspace_edits_pending
    ON coding_workspace_edits(task_id, status, committed_at, edit_id);

COMMIT;

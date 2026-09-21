-- K25′ (2026-09-14): designed-graph subagent nodes run children with
-- parent_kind = 'workflow'. 055 pinned the CHECK to coding | deep_analysis,
-- so the first workflow child INSERT would fail without this.
--
-- 058, not 057: a parallel sandbox-ledger migration may take 057.
ALTER TABLE subagent_runs
    DROP CONSTRAINT IF EXISTS subagent_runs_parent_kind_check;
ALTER TABLE subagent_runs
    ADD CONSTRAINT subagent_runs_parent_kind_check
    CHECK (parent_kind IN ('coding', 'deep_analysis', 'workflow'));

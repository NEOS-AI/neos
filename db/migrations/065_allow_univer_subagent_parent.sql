-- Univer parent kind. 064 pinned CHECK to coding | deep_analysis | workflow | fsi.
ALTER TABLE subagent_runs
    DROP CONSTRAINT IF EXISTS subagent_runs_parent_kind_check;
ALTER TABLE subagent_runs
    ADD CONSTRAINT subagent_runs_parent_kind_check
    CHECK (parent_kind IN ('coding', 'deep_analysis', 'workflow', 'fsi', 'univer'));

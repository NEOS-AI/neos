-- Point run and parent ids at candidate rows. Both tables already exist.

ALTER TABLE gepa_opt_runs
    DROP CONSTRAINT IF EXISTS gepa_opt_runs_seed_candidate_fk;
ALTER TABLE gepa_opt_runs
    ADD CONSTRAINT gepa_opt_runs_seed_candidate_fk
    FOREIGN KEY (seed_candidate_id) REFERENCES gepa_opt_candidates (candidate_id);

ALTER TABLE gepa_opt_runs
    DROP CONSTRAINT IF EXISTS gepa_opt_runs_best_candidate_fk;
ALTER TABLE gepa_opt_runs
    ADD CONSTRAINT gepa_opt_runs_best_candidate_fk
    FOREIGN KEY (best_candidate_id) REFERENCES gepa_opt_candidates (candidate_id);

ALTER TABLE gepa_opt_candidates
    DROP CONSTRAINT IF EXISTS gepa_opt_candidates_parent_fk;
ALTER TABLE gepa_opt_candidates
    ADD CONSTRAINT gepa_opt_candidates_parent_fk
    FOREIGN KEY (parent_id) REFERENCES gepa_opt_candidates (candidate_id);

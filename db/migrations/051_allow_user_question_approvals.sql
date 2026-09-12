BEGIN;

ALTER TABLE coding_approvals
    DROP CONSTRAINT IF EXISTS coding_approvals_risk_check;
ALTER TABLE coding_approvals
    ADD CONSTRAINT coding_approvals_risk_check
    CHECK (risk IN ('workspace_write', 'command', 'user_question'));

COMMIT;

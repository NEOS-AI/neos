ALTER TABLE coding_tool_executions
    DROP CONSTRAINT IF EXISTS coding_tool_executions_status_check;
ALTER TABLE coding_tool_executions
    ADD CONSTRAINT coding_tool_executions_status_check
    CHECK (status IN ('claimed', 'completed', 'failed', 'delegated'));

-- Migration 033: Thinking Engine trace and task DAG persistence.

CREATE TABLE IF NOT EXISTS thinking_engine_traces (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(255) UNIQUE NOT NULL,
    run_id VARCHAR(255),
    session_id VARCHAR(255),
    report_id VARCHAR(255),
    user_id VARCHAR(255),
    event_type VARCHAR(255) NOT NULL,
    node_id VARCHAR(255) NOT NULL,
    sequence INTEGER NOT NULL DEFAULT 0,
    data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_thinking_engine_traces_run
    ON thinking_engine_traces(run_id);

CREATE INDEX IF NOT EXISTS idx_thinking_engine_traces_session
    ON thinking_engine_traces(session_id);

CREATE INDEX IF NOT EXISTS idx_thinking_engine_traces_event_type
    ON thinking_engine_traces(event_type);

CREATE TABLE IF NOT EXISTS thinking_engine_task_nodes (
    id SERIAL PRIMARY KEY,
    task_node_id VARCHAR(255) UNIQUE NOT NULL,
    parent_task_node_id VARCHAR(255),
    run_id VARCHAR(255),
    session_id VARCHAR(255),
    report_id VARCHAR(255),
    user_id VARCHAR(255),
    description TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    depends_on JSONB NOT NULL DEFAULT '[]',
    artifact_ref TEXT,
    harness_run_id VARCHAR(255),
    rollback_generation INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_thinking_engine_task_nodes_run
    ON thinking_engine_task_nodes(run_id);

CREATE INDEX IF NOT EXISTS idx_thinking_engine_task_nodes_session
    ON thinking_engine_task_nodes(session_id);

CREATE INDEX IF NOT EXISTS idx_thinking_engine_task_nodes_status
    ON thinking_engine_task_nodes(status);

CREATE INDEX IF NOT EXISTS idx_thinking_engine_task_nodes_parent
    ON thinking_engine_task_nodes(parent_task_node_id);

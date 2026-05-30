-- Mission Runtime audit and resume tables.

CREATE TABLE IF NOT EXISTS missions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id VARCHAR(255) NOT NULL UNIQUE,
    session_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) REFERENCES users(user_id) ON DELETE SET NULL,
    original_query TEXT NOT NULL,
    intent VARCHAR(100),
    autonomy_level INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(50) NOT NULL,
    mission_type VARCHAR(50) NOT NULL,
    plan_hash VARCHAR(128),
    validation_contract_hash VARCHAR(128),
    plan_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    contract_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mission_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id VARCHAR(255) NOT NULL REFERENCES missions(mission_id) ON DELETE CASCADE,
    task_id VARCHAR(255) NOT NULL,
    parent_task_id VARCHAR(255),
    description TEXT NOT NULL,
    required_capability VARCHAR(100) NOT NULL,
    suggested_agent VARCHAR(100),
    depends_on JSONB NOT NULL DEFAULT '[]'::jsonb,
    expected_output_type VARCHAR(100),
    expected_artifact TEXT,
    risk_level VARCHAR(50) NOT NULL DEFAULT 'low',
    status VARCHAR(50) NOT NULL,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_mission_task UNIQUE (mission_id, task_id)
);

CREATE TABLE IF NOT EXISTS validation_contracts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id VARCHAR(255) NOT NULL UNIQUE,
    mission_id VARCHAR(255) NOT NULL REFERENCES missions(mission_id) ON DELETE CASCADE,
    contract_hash VARCHAR(128) NOT NULL,
    contract_json JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS validator_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    validator_run_id VARCHAR(255) NOT NULL UNIQUE,
    mission_id VARCHAR(255) NOT NULL REFERENCES missions(mission_id) ON DELETE CASCADE,
    task_id VARCHAR(255),
    validator_type VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    findings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    repair_suggestion TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mission_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id VARCHAR(255) NOT NULL REFERENCES missions(mission_id) ON DELETE CASCADE,
    task_id VARCHAR(255),
    event_name VARCHAR(100) NOT NULL,
    correlation_id VARCHAR(255),
    role VARCHAR(50),
    event_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mission_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id VARCHAR(255) NOT NULL REFERENCES missions(mission_id) ON DELETE CASCADE,
    task_id VARCHAR(255),
    artifact_type VARCHAR(100) NOT NULL,
    artifact_ref TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_missions_user_status ON missions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_missions_session ON missions(session_id);
CREATE INDEX IF NOT EXISTS idx_mission_tasks_mission_status ON mission_tasks(mission_id, status);
CREATE INDEX IF NOT EXISTS idx_validator_runs_mission ON validator_runs(mission_id);
CREATE INDEX IF NOT EXISTS idx_mission_events_mission_created ON mission_events(mission_id, created_at);

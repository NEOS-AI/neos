-- 커스텀 워크플로우 기능을 위한 테이블 생성

-- MCP 서버 테이블
CREATE TABLE IF NOT EXISTS mcp_servers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    url VARCHAR(512) NOT NULL,
    description TEXT,
    server_type VARCHAR(100),
    config JSONB DEFAULT '{}',
    capabilities JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    outdated_at TIMESTAMP DEFAULT NULL
);

-- 워크플로우 상태 타입
DO $$ BEGIN
    CREATE TYPE workflow_status AS ENUM ('draft', 'active', 'inactive', 'archived');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 커스텀 워크플로우 테이블
CREATE TABLE IF NOT EXISTS custom_workflows (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    created_by VARCHAR(255) NOT NULL,
    config JSONB DEFAULT '{}',
    nodes JSONB DEFAULT '[]',
    edges JSONB DEFAULT '[]',
    status workflow_status DEFAULT 'draft',
    version INTEGER DEFAULT 1,
    tags JSONB DEFAULT '[]',
    execution_count INTEGER DEFAULT 0,
    last_executed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 워크플로우-MCP 서버 관계 테이블
CREATE TABLE IF NOT EXISTS workflow_mcp_servers (
    id SERIAL PRIMARY KEY,
    workflow_id INTEGER NOT NULL REFERENCES custom_workflows(id) ON DELETE CASCADE,
    mcp_server_id INTEGER NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
    node_name VARCHAR(255),
    tool_config JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workflow_id, mcp_server_id, node_name)
);

-- 워크플로우 실행 기록 테이블
CREATE TABLE IF NOT EXISTS workflow_executions (
    id SERIAL PRIMARY KEY,
    workflow_id INTEGER NOT NULL REFERENCES custom_workflows(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255) NOT NULL,
    input_query TEXT NOT NULL,
    output JSONB,
    success BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    execution_time_ms INTEGER,
    tokens_used INTEGER,
    quality_score INTEGER,
    execution_steps JSONB DEFAULT '[]',
    mcp_calls JSONB DEFAULT '[]',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_mcp_servers_type ON mcp_servers(server_type);
CREATE INDEX IF NOT EXISTS idx_mcp_servers_active ON mcp_servers(is_active);

CREATE INDEX IF NOT EXISTS idx_custom_workflows_status ON custom_workflows(status);
CREATE INDEX IF NOT EXISTS idx_custom_workflows_created_by ON custom_workflows(created_by);
CREATE INDEX IF NOT EXISTS idx_custom_workflows_name ON custom_workflows(name);

CREATE INDEX IF NOT EXISTS idx_workflow_mcp_servers_workflow ON workflow_mcp_servers(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_mcp_servers_mcp ON workflow_mcp_servers(mcp_server_id);

CREATE INDEX IF NOT EXISTS idx_workflow_executions_workflow ON workflow_executions(workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_user ON workflow_executions(user_id);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_session ON workflow_executions(session_id);
CREATE INDEX IF NOT EXISTS idx_workflow_executions_started ON workflow_executions(started_at);

-- 트리거: updated_at 자동 업데이트
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_mcp_servers_updated_at ON mcp_servers;
CREATE TRIGGER update_mcp_servers_updated_at
    BEFORE UPDATE ON mcp_servers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_custom_workflows_updated_at ON custom_workflows;
CREATE TRIGGER update_custom_workflows_updated_at
    BEFORE UPDATE ON custom_workflows
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 샘플 데이터 (선택사항)
-- INSERT INTO mcp_servers (name, url, server_type, description, capabilities) VALUES
--     ('web_search_mcp', 'local', 'web_search', 'Tavily 웹 검색 MCP 서버', '["real_time_search", "multi_source_search"]'),
--     ('file_processing_mcp', 'local', 'file_processing', '파일 처리 MCP 서버', '["file_read", "file_write", "file_analysis"]'),
--     ('database_mcp', 'local', 'data_analysis', '데이터베이스 작업 MCP 서버', '["query_execution", "schema_inspection"]')
-- ON CONFLICT (name) DO NOTHING;

COMMENT ON TABLE mcp_servers IS 'MCP 서버 정보 저장';
COMMENT ON TABLE custom_workflows IS '커스텀 워크플로우 정의 저장';
COMMENT ON TABLE workflow_mcp_servers IS '워크플로우와 MCP 서버 간의 연결 정보';
COMMENT ON TABLE workflow_executions IS '워크플로우 실행 기록';

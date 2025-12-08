-- Analytics Backoffice Database Migration
-- Run this script to create the necessary tables for the analytics backoffice

-- Enable pgvector extension if not already enabled
CREATE EXTENSION IF NOT EXISTS vector;

-- Analysis Runs table
CREATE TABLE IF NOT EXISTS analysis_runs (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(36) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'pending',
    config JSONB DEFAULT '{}',
    facet_types TEXT[] DEFAULT '{}',
    start_date TIMESTAMP,
    end_date TIMESTAMP,
    total_conversations INTEGER DEFAULT 0,
    processed_conversations INTEGER DEFAULT 0,
    total_clusters INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    progress_percentage FLOAT DEFAULT 0.0,
    current_stage VARCHAR(100),
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_run_id ON analysis_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_status ON analysis_runs(status);

-- Facets table
CREATE TABLE IF NOT EXISTS facets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    facet_type VARCHAR(50) NOT NULL,
    description TEXT,
    extraction_prompt TEXT,
    value_type VARCHAR(50) DEFAULT 'string',
    is_active BOOLEAN DEFAULT TRUE,
    config JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_facets_name ON facets(name);

-- Facet Values table
CREATE TABLE IF NOT EXISTS facet_values (
    id SERIAL PRIMARY KEY,
    facet_id INTEGER REFERENCES facets(id) ON DELETE CASCADE,
    value VARCHAR(500) NOT NULL,
    normalized_value VARCHAR(500) NOT NULL,
    count INTEGER DEFAULT 0,
    embedding vector(384),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(facet_id, normalized_value)
);

CREATE INDEX IF NOT EXISTS idx_facet_values_facet_id ON facet_values(facet_id);
CREATE INDEX IF NOT EXISTS idx_facet_values_normalized ON facet_values(normalized_value);

-- Clusters table
CREATE TABLE IF NOT EXISTS clusters (
    id SERIAL PRIMARY KEY,
    cluster_id VARCHAR(36) UNIQUE NOT NULL,
    analysis_run_id INTEGER REFERENCES analysis_runs(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    summary TEXT,
    level INTEGER DEFAULT 0,
    parent_id INTEGER REFERENCES clusters(id) ON DELETE CASCADE,
    path VARCHAR(500) DEFAULT '/',
    conversation_count INTEGER DEFAULT 0,
    unique_user_count INTEGER DEFAULT 0,
    centroid_x FLOAT,
    centroid_y FLOAT,
    centroid_embedding vector(384),
    top_facets JSONB,
    keywords TEXT[],
    is_visible BOOLEAN DEFAULT TRUE,
    privacy_validated BOOLEAN DEFAULT FALSE,
    privacy_reason VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_clusters_cluster_id ON clusters(cluster_id);
CREATE INDEX IF NOT EXISTS idx_clusters_analysis_run_id ON clusters(analysis_run_id);
CREATE INDEX IF NOT EXISTS idx_clusters_parent_id ON clusters(parent_id);

-- Conversation Facets table
CREATE TABLE IF NOT EXISTS conversation_facets (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL,
    analysis_run_id INTEGER REFERENCES analysis_runs(id) ON DELETE CASCADE,
    facets JSONB DEFAULT '{}',
    summary_embedding vector(384),
    umap_x FLOAT,
    umap_y FLOAT,
    cluster_id INTEGER REFERENCES clusters(id) ON DELETE SET NULL,
    is_private BOOLEAN DEFAULT FALSE,
    privacy_reason VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(conversation_id, analysis_run_id)
);

CREATE INDEX IF NOT EXISTS idx_conversation_facets_conversation_id ON conversation_facets(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversation_facets_analysis_run_id ON conversation_facets(analysis_run_id);
CREATE INDEX IF NOT EXISTS idx_conversation_facets_cluster_id ON conversation_facets(cluster_id);

-- Cluster Hierarchy materialized view table
CREATE TABLE IF NOT EXISTS cluster_hierarchy (
    id SERIAL PRIMARY KEY,
    analysis_run_id INTEGER NOT NULL,
    cluster_id INTEGER NOT NULL,
    ancestor_id INTEGER NOT NULL,
    depth INTEGER NOT NULL,
    UNIQUE(cluster_id, ancestor_id)
);

CREATE INDEX IF NOT EXISTS idx_cluster_hierarchy_analysis_run_id ON cluster_hierarchy(analysis_run_id);
CREATE INDEX IF NOT EXISTS idx_cluster_hierarchy_cluster_id ON cluster_hierarchy(cluster_id);
CREATE INDEX IF NOT EXISTS idx_cluster_hierarchy_ancestor_id ON cluster_hierarchy(ancestor_id);

-- Insert default facets
INSERT INTO facets (name, facet_type, description, value_type) VALUES
    ('topic', 'topic', 'Main topic or subject of the conversation', 'string'),
    ('language', 'language', 'Primary language used in the conversation', 'string'),
    ('task_type', 'task_type', 'Type of task being performed', 'string'),
    ('intent', 'intent', 'User''s primary intent', 'string'),
    ('domain', 'domain', 'Domain area of the conversation', 'string'),
    ('complexity', 'complexity', 'Complexity level from 1 to 5', 'number'),
    ('sentiment', 'sentiment', 'Overall sentiment of the conversation', 'string'),
    ('safety_score', 'safety_score', 'Safety score from 1 to 5', 'number')
ON CONFLICT (name) DO NOTHING;

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
DROP TRIGGER IF EXISTS update_analysis_runs_updated_at ON analysis_runs;
CREATE TRIGGER update_analysis_runs_updated_at
    BEFORE UPDATE ON analysis_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_facets_updated_at ON facets;
CREATE TRIGGER update_facets_updated_at
    BEFORE UPDATE ON facets
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_clusters_updated_at ON clusters;
CREATE TRIGGER update_clusters_updated_at
    BEFORE UPDATE ON clusters
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Phase 3.1: Knowledge Graph Tables for Graph-Augmented Retrieval
-- ============================================================================

-- 엔티티 테이블
CREATE TABLE IF NOT EXISTS kg_entities (
    entity_id VARCHAR(255) PRIMARY KEY,
    entity_type VARCHAR(100) NOT NULL,
    entity_name VARCHAR(500) NOT NULL,
    entity_description TEXT,
    properties JSONB DEFAULT '{}',
    confidence_score FLOAT DEFAULT 0.0,
    embedding vector(1536),
    source_document_id VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kg_entities_type ON kg_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_kg_entities_name ON kg_entities(entity_name);
CREATE INDEX IF NOT EXISTS idx_kg_entities_embedding ON kg_entities
    USING hnsw(embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_kg_entities_source ON kg_entities(source_document_id);

-- 관계 테이블
CREATE TABLE IF NOT EXISTS kg_relations (
    relation_id SERIAL PRIMARY KEY,
    source_entity_id VARCHAR(255) NOT NULL REFERENCES kg_entities(entity_id) ON DELETE CASCADE,
    target_entity_id VARCHAR(255) NOT NULL REFERENCES kg_entities(entity_id) ON DELETE CASCADE,
    relation_type VARCHAR(100) NOT NULL,
    confidence_score FLOAT DEFAULT 0.0,
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_entity_id, target_entity_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_kg_relations_source ON kg_relations(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_kg_relations_target ON kg_relations(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_kg_relations_type ON kg_relations(relation_type);

-- 엔티티 출현 위치 (엔티티가 어떤 문서에서 등장했는지 추적)
CREATE TABLE IF NOT EXISTS kg_entity_occurrences (
    occurrence_id SERIAL PRIMARY KEY,
    entity_id VARCHAR(255) NOT NULL REFERENCES kg_entities(entity_id) ON DELETE CASCADE,
    document_id VARCHAR(255) NOT NULL,
    chunk_id VARCHAR(255),
    context_snippet TEXT,
    position_start INT,
    position_end INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kg_occurrences_entity ON kg_entity_occurrences(entity_id);
CREATE INDEX IF NOT EXISTS idx_kg_occurrences_document ON kg_entity_occurrences(document_id);

-- 그래프 탐색 헬퍼 함수: 시작 엔티티에서 N-hop 이웃 탐색
CREATE OR REPLACE FUNCTION kg_traverse_neighbors(
    start_entity_id VARCHAR,
    max_depth INT DEFAULT 2,
    relation_types VARCHAR[] DEFAULT NULL
) RETURNS TABLE(
    entity_id VARCHAR,
    entity_name VARCHAR,
    entity_type VARCHAR,
    depth INT,
    path VARCHAR[]
) AS $$
WITH RECURSIVE entity_graph AS (
    -- Base case: 시작 엔티티
    SELECT
        e.entity_id,
        e.entity_name,
        e.entity_type,
        0 AS depth,
        ARRAY[e.entity_id]::VARCHAR[] AS path
    FROM kg_entities e
    WHERE e.entity_id = start_entity_id

    UNION

    -- Recursive: 관계를 따라 탐색
    SELECT
        e.entity_id,
        e.entity_name,
        e.entity_type,
        eg.depth + 1,
        eg.path || e.entity_id
    FROM entity_graph eg
    JOIN kg_relations r ON r.source_entity_id = eg.entity_id
    JOIN kg_entities e ON e.entity_id = r.target_entity_id
    WHERE
        eg.depth < max_depth
        AND NOT (e.entity_id = ANY(eg.path))  -- 순환 방지
        AND (relation_types IS NULL OR r.relation_type = ANY(relation_types))
)
SELECT * FROM entity_graph;
$$ LANGUAGE sql STABLE;

-- HyperDeepResearch Schema
-- 고도화된 딥리서치 시스템을 위한 데이터베이스 스키마

-- 보고서 테이블
CREATE TABLE IF NOT EXISTS hyper_research_reports (
    id SERIAL PRIMARY KEY,
    report_id VARCHAR(255) UNIQUE NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    session_id VARCHAR(255) NOT NULL,

    -- 연구 주제 및 메타데이터
    research_topic TEXT NOT NULL,
    research_plan JSONB,
    research_status VARCHAR(50) DEFAULT 'pending', -- pending, in_progress, completed, failed

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 연구 통계
    total_sections INTEGER DEFAULT 0,
    total_sources INTEGER DEFAULT 0,
    total_queries INTEGER DEFAULT 0,
    processing_time_ms INTEGER,

    -- 품질 메트릭
    quality_score FLOAT,
    completeness_score FLOAT,

    -- 추가 메타데이터
    metadata JSONB DEFAULT '{}',

    -- deleted_at 컬럼 추가 (soft delete 용)
    deleted_at TIMESTAMP

    -- Note: Foreign key to users table is optional - uncomment if users table exists
    -- FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 보고서 섹션 테이블
CREATE TABLE IF NOT EXISTS hyper_research_sections (
    id SERIAL PRIMARY KEY,
    section_id VARCHAR(255) UNIQUE NOT NULL,
    report_id VARCHAR(255) NOT NULL,

    -- 섹션 구조 정보
    section_order INTEGER NOT NULL, -- 섹션 순서
    section_level INTEGER DEFAULT 1, -- 섹션 레벨 (1: 메인, 2: 서브섹션 등)
    parent_section_id VARCHAR(255), -- 부모 섹션 (계층 구조)
    section_type VARCHAR(100) NOT NULL, -- 섹션 타입: planning, data_collection, analysis, report_generation 등

    -- 섹션 내용
    section_title TEXT NOT NULL,
    section_content TEXT,
    section_summary TEXT,

    -- 섹션 상태
    section_status VARCHAR(50) DEFAULT 'pending', -- pending, in_progress, completed, failed

    -- 섹션 데이터 소스
    sources_count INTEGER DEFAULT 0,
    sources JSONB DEFAULT '[]', -- 이 섹션에서 사용된 소스들
    queries JSONB DEFAULT '[]', -- 이 섹션을 위해 실행된 쿼리들

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    processing_time_ms INTEGER,

    -- 추가 메타데이터
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (report_id) REFERENCES hyper_research_reports(report_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_section_id) REFERENCES hyper_research_sections(section_id) ON DELETE SET NULL
);

-- 데이터 수집 기록 테이블
CREATE TABLE IF NOT EXISTS hyper_research_data_collection (
    id SERIAL PRIMARY KEY,
    collection_id VARCHAR(255) UNIQUE NOT NULL,
    report_id VARCHAR(255) NOT NULL,
    section_id VARCHAR(255),

    -- 검색 정보
    query_text TEXT NOT NULL,
    query_type VARCHAR(50), -- initial, gap_fill, verification, targeted
    search_phase INTEGER, -- 1, 2, 3, 4 (어느 단계에서 수집되었는지)

    -- 결과 정보
    results_count INTEGER DEFAULT 0,
    results JSONB DEFAULT '[]',

    -- 타임스탬프
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    execution_time_ms INTEGER,

    -- 메타데이터
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (report_id) REFERENCES hyper_research_reports(report_id) ON DELETE CASCADE,
    FOREIGN KEY (section_id) REFERENCES hyper_research_sections(section_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS hyper_research_criticism_feedback (
    id SERIAL PRIMARY KEY,
    feedback_id VARCHAR(255) UNIQUE NOT NULL,
    report_id VARCHAR(255) NOT NULL,
    section_type VARCHAR(100) NOT NULL,
    section_title TEXT NOT NULL,
    severity VARCHAR(50) DEFAULT 'none',
    has_issues BOOLEAN DEFAULT FALSE,
    feedback_text TEXT,
    suggested_queries JSONB DEFAULT '[]',
    missing_perspectives JSONB DEFAULT '[]',
    redirect_suggestion TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);


-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_hyper_reports_user_id ON hyper_research_reports(user_id);
CREATE INDEX IF NOT EXISTS idx_hyper_reports_session_id ON hyper_research_reports(session_id);
CREATE INDEX IF NOT EXISTS idx_hyper_reports_status ON hyper_research_reports(research_status);
CREATE INDEX IF NOT EXISTS idx_hyper_reports_created_at ON hyper_research_reports(created_at);

CREATE INDEX IF NOT EXISTS idx_hyper_sections_report_id ON hyper_research_sections(report_id);
CREATE INDEX IF NOT EXISTS idx_hyper_sections_order ON hyper_research_sections(report_id, section_order);
CREATE INDEX IF NOT EXISTS idx_hyper_sections_type ON hyper_research_sections(section_type);
CREATE INDEX IF NOT EXISTS idx_hyper_sections_status ON hyper_research_sections(section_status);
CREATE INDEX IF NOT EXISTS idx_hyper_sections_parent ON hyper_research_sections(parent_section_id);

CREATE INDEX IF NOT EXISTS idx_hyper_data_collection_report_id ON hyper_research_data_collection(report_id);
CREATE INDEX IF NOT EXISTS idx_hyper_data_collection_section_id ON hyper_research_data_collection(section_id);
CREATE INDEX IF NOT EXISTS idx_hyper_data_collection_phase ON hyper_research_data_collection(search_phase);

-- add index for deleted_at and research_status for efficient soft delete queries
CREATE INDEX IF NOT EXISTS idx_hyper_reports_deleted_at ON hyper_research_reports(deleted_at);
CREATE INDEX IF NOT EXISTS idx_hyper_reports_research_status ON hyper_research_reports(research_status);


-- 트리거: 보고서 업데이트 시간 자동 갱신
CREATE OR REPLACE FUNCTION update_hyper_report_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_hyper_report_updated_at ON hyper_research_reports;
CREATE TRIGGER trigger_update_hyper_report_updated_at
    BEFORE UPDATE ON hyper_research_reports
    FOR EACH ROW
    EXECUTE FUNCTION update_hyper_report_updated_at();

-- 트리거: 섹션 추가 시 보고서 통계 업데이트
CREATE OR REPLACE FUNCTION update_hyper_report_section_count()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE hyper_research_reports
        SET total_sections = total_sections + 1
        WHERE report_id = NEW.report_id;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE hyper_research_reports
        SET total_sections = total_sections - 1
        WHERE report_id = OLD.report_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_hyper_report_section_count ON hyper_research_sections;
CREATE TRIGGER trigger_update_hyper_report_section_count
    AFTER INSERT OR DELETE ON hyper_research_sections
    FOR EACH ROW
    EXECUTE FUNCTION update_hyper_report_section_count();

-- 뷰: 전체 보고서 개요
CREATE OR REPLACE VIEW hyper_research_overview AS
SELECT
    r.report_id,
    r.user_id,
    r.research_topic,
    r.research_status,
    r.created_at,
    r.completed_at,
    r.total_sections,
    r.total_sources,
    r.quality_score,
    COUNT(DISTINCT s.section_id) as completed_sections,
    COUNT(DISTINCT CASE WHEN s.section_status = 'completed' THEN s.section_id END) as successful_sections
FROM hyper_research_reports r
LEFT JOIN hyper_research_sections s ON r.report_id = s.report_id
GROUP BY r.report_id, r.user_id, r.research_topic, r.research_status,
         r.created_at, r.completed_at, r.total_sections, r.total_sources, r.quality_score;

-- 뷰: 섹션별 상세 정보 (계층 구조 포함)
CREATE OR REPLACE VIEW hyper_research_section_hierarchy AS
WITH RECURSIVE section_tree AS (
    -- 루트 섹션 (parent_section_id가 NULL인 것)
    SELECT
        section_id,
        report_id,
        section_title,
        section_order,
        section_level,
        parent_section_id,
        section_type,
        section_status,
        ARRAY[section_order] as path,
        section_title as full_path
    FROM hyper_research_sections
    WHERE parent_section_id IS NULL

    UNION ALL

    -- 자식 섹션
    SELECT
        s.section_id,
        s.report_id,
        s.section_title,
        s.section_order,
        s.section_level,
        s.parent_section_id,
        s.section_type,
        s.section_status,
        st.path || s.section_order,
        st.full_path || ' > ' || s.section_title
    FROM hyper_research_sections s
    INNER JOIN section_tree st ON s.parent_section_id = st.section_id
)
SELECT * FROM section_tree
ORDER BY path;

-- 샘플 데이터 삽입 함수
CREATE OR REPLACE FUNCTION create_sample_hyper_research_report(
    p_user_id VARCHAR(255),
    p_session_id VARCHAR(255),
    p_topic TEXT
) RETURNS VARCHAR(255) AS $$
DECLARE
    v_report_id VARCHAR(255);
BEGIN
    v_report_id := 'hyper_report_' || gen_random_uuid()::text;

    INSERT INTO hyper_research_reports (
        report_id, user_id, session_id, research_topic,
        research_status, research_plan
    ) VALUES (
        v_report_id, p_user_id, p_session_id, p_topic,
        'pending',
        '{"phases": ["topic_confirmation", "planning", "data_collection", "analysis", "report_generation"]}'::jsonb
    );

    RETURN v_report_id;
END;
$$ LANGUAGE plpgsql;

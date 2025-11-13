-- Migration: Add conversation tracking to deep research reports
-- Purpose: Connect chat conversations with deep research reports for web integration

-- Add conversation_id and initial_message_id to hyper_research_reports
ALTER TABLE hyper_research_reports
ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(255),
ADD COLUMN IF NOT EXISTS initial_message_id VARCHAR(255);

-- Add foreign keys (with ON DELETE CASCADE to maintain referential integrity)
DO $$
BEGIN
    -- Add foreign key for conversation_id if not exists
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_hyper_research_reports_conversation_id'
    ) THEN
        ALTER TABLE hyper_research_reports
        ADD CONSTRAINT fk_hyper_research_reports_conversation_id
        FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE;
    END IF;

    -- Add foreign key for initial_message_id if not exists
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_hyper_research_reports_initial_message_id'
    ) THEN
        ALTER TABLE hyper_research_reports
        ADD CONSTRAINT fk_hyper_research_reports_initial_message_id
        FOREIGN KEY (initial_message_id) REFERENCES messages(message_id) ON DELETE SET NULL;
    END IF;
END $$;

-- Add indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_hyper_reports_conversation_id
ON hyper_research_reports(conversation_id);

CREATE INDEX IF NOT EXISTS idx_hyper_reports_initial_message_id
ON hyper_research_reports(initial_message_id);

-- Add comment
COMMENT ON COLUMN hyper_research_reports.conversation_id IS
'References the conversation where this deep research was initiated';

COMMENT ON COLUMN hyper_research_reports.initial_message_id IS
'References the user message that triggered this deep research';

-- Update the create_sample_hyper_research_report function to include conversation_id
CREATE OR REPLACE FUNCTION create_hyper_research_report(
    p_user_id VARCHAR(255),
    p_session_id VARCHAR(255),
    p_topic TEXT,
    p_conversation_id VARCHAR(255) DEFAULT NULL,
    p_initial_message_id VARCHAR(255) DEFAULT NULL
) RETURNS VARCHAR(255) AS $$
DECLARE
    v_report_id VARCHAR(255);
BEGIN
    v_report_id := 'hyper_report_' || gen_random_uuid()::text;

    INSERT INTO hyper_research_reports (
        report_id, user_id, session_id, research_topic,
        conversation_id, initial_message_id,
        research_status, research_plan
    ) VALUES (
        v_report_id, p_user_id, p_session_id, p_topic,
        p_conversation_id, p_initial_message_id,
        'pending',
        '{"phases": ["topic_confirmation", "planning", "data_collection", "analysis", "report_generation"]}'::jsonb
    );

    RETURN v_report_id;
END;
$$ LANGUAGE plpgsql;

-- Create function to get deep research reports for a conversation
CREATE OR REPLACE FUNCTION get_conversation_deep_research_reports(
    p_conversation_id VARCHAR(255)
)
RETURNS TABLE (
    report_id VARCHAR(255),
    research_topic TEXT,
    research_status VARCHAR(50),
    created_at TIMESTAMP,
    completed_at TIMESTAMP,
    total_sections INTEGER,
    total_sources INTEGER,
    quality_score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        r.report_id,
        r.research_topic,
        r.research_status,
        r.created_at,
        r.completed_at,
        r.total_sections,
        r.total_sources,
        r.quality_score
    FROM hyper_research_reports r
    WHERE r.conversation_id = p_conversation_id
      AND r.deleted_at IS NULL
    ORDER BY r.created_at DESC;
END;
$$ LANGUAGE plpgsql;

-- Create view for conversation with deep research info
CREATE OR REPLACE VIEW conversation_with_deep_research AS
SELECT
    c.conversation_id,
    c.user_id,
    c.title,
    c.model_name,
    c.status,
    c.message_count,
    c.created_at,
    c.last_message_at,
    COUNT(DISTINCT r.report_id) as deep_research_count,
    COUNT(DISTINCT r.report_id) FILTER (WHERE r.research_status = 'in_progress') as active_research_count,
    MAX(r.completed_at) as last_research_completed_at
FROM conversations c
LEFT JOIN hyper_research_reports r ON c.conversation_id = r.conversation_id AND r.deleted_at IS NULL
WHERE c.deleted_at IS NULL
GROUP BY c.conversation_id, c.user_id, c.title, c.model_name, c.status, c.message_count, c.created_at, c.last_message_at;

-- Add comment to view
COMMENT ON VIEW conversation_with_deep_research IS
'Conversations enriched with deep research statistics';

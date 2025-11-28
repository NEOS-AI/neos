-- Migration: Add deep research events table
-- Purpose: Real-time event streaming for deep research progress
-- Author: Claude
-- Date: 2025-11-27

-- Create events table for real-time progress tracking
CREATE TABLE IF NOT EXISTS hyper_research_events (
    -- Primary identification
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id VARCHAR(255) NOT NULL,

    -- Event metadata
    event_type VARCHAR(50) NOT NULL,
    event_category VARCHAR(30) NOT NULL,
    sequence_number INTEGER NOT NULL,

    -- Event data (flexible JSON structure)
    event_data JSONB NOT NULL DEFAULT '{}',

    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Foreign key to reports table
    FOREIGN KEY (report_id) REFERENCES hyper_research_reports(report_id) ON DELETE CASCADE
);

-- Indexes for fast polling and querying
CREATE INDEX IF NOT EXISTS idx_events_report_created
    ON hyper_research_events(report_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_events_type
    ON hyper_research_events(report_id, event_type);

-- Unique index on report_id + sequence_number for fast polling and duplicate prevention
-- Note: UNIQUE INDEX serves both as constraint and index, so no separate index needed
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_report_seq_unique
    ON hyper_research_events(report_id, sequence_number);

-- Comment on table
COMMENT ON TABLE hyper_research_events IS
    'Real-time event log for deep research progress tracking. Supports SSE streaming to clients.';

COMMENT ON COLUMN hyper_research_events.event_type IS
    'Event type: phase_started, query_executing, llm_call_started, sources_collected, progress_update, etc.';

COMMENT ON COLUMN hyper_research_events.event_category IS
    'Event category: phase, data_collection, llm, analysis, progress';

COMMENT ON COLUMN hyper_research_events.sequence_number IS
    'Sequential number for ordering events within a report. Used for efficient polling.';

COMMENT ON COLUMN hyper_research_events.event_data IS
    'Flexible JSONB field containing event-specific data. Structure varies by event_type.';

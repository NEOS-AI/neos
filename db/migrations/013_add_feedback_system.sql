-- Migration 013: Extend vote system with feedback (Phase 2.11)
--
-- Adds text feedback and category to existing votes table.
-- Enables feedback-based quality improvement:
-- - Source quality adjustment (which sources get downvoted)
-- - Prompt issue identification (categorized feedback text)
-- - Query classifier improvement (feedback correlation)

ALTER TABLE "Vote_v2" ADD COLUMN IF NOT EXISTS feedback_text TEXT;
ALTER TABLE "Vote_v2" ADD COLUMN IF NOT EXISTS feedback_category VARCHAR(50);
-- Categories: source_quality, incorrect_info, prompt_issue, missing_info, other

-- Migration 022: Add tool approval allowlist table
-- (OpenClaw Execution Approval System)
-- 사용자가 특정 스킬을 allowlist에 등록하면 이후 요청은 자동 승인된다.

CREATE TABLE IF NOT EXISTS tool_approval_allowlist (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    skill_name VARCHAR(100) NOT NULL,
    auto_approved BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, skill_name)
);

COMMENT ON TABLE tool_approval_allowlist IS '사용자별 스킬 자동 승인 allowlist (Phase 2 Execution Approval)';
COMMENT ON COLUMN tool_approval_allowlist.skill_name IS '자동 승인할 스킬 이름 (예: api_call, file_processing)';
COMMENT ON COLUMN tool_approval_allowlist.auto_approved IS 'true=자동 승인, false=항상 사용자 확인 필요';

CREATE INDEX IF NOT EXISTS idx_allowlist_user_skill ON tool_approval_allowlist(user_id, skill_name);

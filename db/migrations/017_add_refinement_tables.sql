-- ============================================================================
-- Phase 3.8: Interactive Research Refinement
-- ============================================================================

-- 사용자 소스 선호도 (블랙리스트, 신뢰도 조정)
CREATE TABLE IF NOT EXISTS user_source_preferences (
    preference_id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    source_url TEXT NOT NULL,
    action VARCHAR(50) NOT NULL,  -- 'blacklist', 'trust_adjust'
    trust_adjustment FLOAT DEFAULT 0.0,  -- -1.0 ~ +1.0
    reason TEXT,
    session_id VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, source_url, action)
);

CREATE INDEX IF NOT EXISTS idx_user_source_prefs_user ON user_source_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_user_source_prefs_action ON user_source_preferences(action);

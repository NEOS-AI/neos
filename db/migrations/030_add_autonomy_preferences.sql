-- Agent autonomy preference support.
-- Uses existing users.preferences JSONB column; no table shape change required.

CREATE INDEX IF NOT EXISTS idx_users_preferences_autonomy
    ON users USING gin ((preferences -> 'autonomy_level'));

UPDATE users
SET preferences = jsonb_set(
    COALESCE(preferences, '{}'::jsonb),
    '{autonomy_level}',
    '1',
    TRUE
)
WHERE preferences IS NULL OR preferences -> 'autonomy_level' IS NULL;

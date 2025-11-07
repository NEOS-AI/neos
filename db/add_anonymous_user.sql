-- Add anonymous user for web chat interface
-- This user is used when users access the web interface without authentication

INSERT INTO users (user_id, preferences)
VALUES (
    'anonymous',
    '{"interface": "web", "role": "anonymous"}'
)
ON CONFLICT (user_id) DO NOTHING;

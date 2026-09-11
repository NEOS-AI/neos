ALTER TABLE learned_lessons
    ADD COLUMN IF NOT EXISTS last_injected_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS inject_count INTEGER;

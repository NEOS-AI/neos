-- User x model preferences (effort). 2026-09-24.
-- Design: docs/MODEL_EFFORT_PREFERENCES_DESIGN.md §4.4
-- model_pin is the canonical catalog pin (normalized before insert).
-- effort has no DB constraint: the resolver's gate refuses a level a model
-- no longer takes; the API validates on write.

CREATE TABLE IF NOT EXISTS user_model_preferences (
    user_id    VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    model_pin  VARCHAR(100) NOT NULL,
    effort     VARCHAR(20)  NOT NULL,
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, model_pin)
);

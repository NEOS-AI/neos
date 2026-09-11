CREATE TABLE IF NOT EXISTS channel_inbound_idempotency (
    session_id VARCHAR(255) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    outcome TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (session_id, idempotency_key)
);

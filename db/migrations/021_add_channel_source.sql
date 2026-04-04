-- Migration 021: Add channel source columns to query_history
-- (OpenClaw Multi-Channel Adapter Layer)
-- 외부 채널(Telegram, Discord, Slack)에서 트리거된 쿼리를 추적한다.

ALTER TABLE query_history
    ADD COLUMN IF NOT EXISTS channel_source VARCHAR(50) DEFAULT 'api',
    ADD COLUMN IF NOT EXISTS external_channel_id VARCHAR(500);

COMMENT ON COLUMN query_history.channel_source IS '요청 채널 유형: api | telegram | discord | slack';
COMMENT ON COLUMN query_history.external_channel_id IS '외부 채널 식별자 (Telegram chat_id, Discord channel_id 등)';

CREATE INDEX IF NOT EXISTS idx_qh_channel_source ON query_history(channel_source);

-- 상시 에이전트 트리거의 채널 원천 (로드맵 트랙 Q4b, 2026-10-01).
-- 설계: docs/Q2_Q4B_RULES_CHANNEL_TRIGGERS_DESIGN_261001.md §3
--
-- 지정한 채널(slack/discord/telegram)의 메시지가 에이전트의 background 태스크가 된다.
-- - 발동시키는 발신자: 소유자에게 매핑된 사람(channels.principals) + 트리거의 allowed_senders.
--   봇·자기 자신은 언제나 아니다(코드).
-- - 074 의 source CHECK 를 넓히고(그것을 읽는 코드가 이 단계에 온다), 원천별 모양을 CHECK 로 묶는다.
-- 제약 이름을 고정해 다시 건다 -- 074 의 열 CHECK 는 기본 이름을 쓴다(069 와 같은 방식).
ALTER TABLE standing_agent_triggers ADD COLUMN IF NOT EXISTS channel_type VARCHAR(16) NULL;
ALTER TABLE standing_agent_triggers ADD COLUMN IF NOT EXISTS channel_id VARCHAR(255) NULL;
ALTER TABLE standing_agent_triggers
    ADD COLUMN IF NOT EXISTS allowed_senders JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE standing_agent_triggers DROP CONSTRAINT IF EXISTS standing_agent_triggers_source_check;
ALTER TABLE standing_agent_triggers
    ADD CONSTRAINT standing_agent_triggers_source_check
        CHECK (source IN ('webhook', 'channel'));

ALTER TABLE standing_agent_triggers DROP CONSTRAINT IF EXISTS standing_agent_triggers_source_shape;
ALTER TABLE standing_agent_triggers
    ADD CONSTRAINT standing_agent_triggers_source_shape
        CHECK (
            jsonb_typeof(allowed_senders) = 'array'
            AND (
                (source = 'webhook' AND channel_type IS NULL AND channel_id IS NULL
                 AND allowed_senders = '[]'::jsonb)
                OR (source = 'channel'
                    -- IS NOT NULL 을 따로 쓴다: `NULL IN (...)` 은 NULL 이고, CHECK 는 NULL 을
                    -- **통과**시킨다. 이 줄이 없으면 channel_type 이 빈 채널 행이 들어간다(실 DB 로 확인).
                    AND channel_type IS NOT NULL
                    AND channel_type IN ('slack', 'discord', 'telegram')
                    AND channel_id IS NOT NULL AND btrim(channel_id) <> '')
            )
        );

-- 인바운드 메시지 하나마다 이 인덱스로 찾는다.
CREATE INDEX IF NOT EXISTS ix_standing_agent_triggers_channel
    ON standing_agent_triggers(channel_type, channel_id)
    WHERE source = 'channel' AND deleted_at IS NULL;

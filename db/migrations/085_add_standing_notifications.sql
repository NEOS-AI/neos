-- 상시 에이전트 소유자 알림 (로드맵 트랙 Q10b, 2026-10-02).
-- 설계: docs/Q10B_Q3_PAUSE_STANDING_QUESTIONS_DESIGN_261002.md §4
--
-- 둘이다.
--
-- 1. standing_agent_notify_targets -- 에이전트의 알림이 갈 채널 하나. `standing_agents` 에
--    열을 더하지 않고 따로 둔다: 에이전트 응답 모양과 기존 PATCH 가 그대로이고, 에이전트에
--    딸린 것은 `agent_id` 로 키를 잡는다는 Q13 규칙(설계 §4.3)과도 같다.
-- 2. standing_notifications -- 워커가 적고 API 프로세스가 꺼내 보내는 durable 큐.
--    채널 어댑터는 API 프로세스에만 있다(`main.py` lifespan). `(agent_id, dedupe_key)`
--    유일이 "한 번"을 보장한다 -- 봉투 경고는 달마다(`budget_warning:YYYY-MM`), 멈춤은
--    멈춤 이벤트마다, 상시 질문(Q3)은 DA 런마다.
--
-- 둘 다 `ON DELETE CASCADE` -- 에이전트(그리고 사용자) 삭제를 막지 않는다(074 와 같은 이유).
-- 두 번 적용해도 같다.

CREATE TABLE IF NOT EXISTS standing_agent_notify_targets (
    agent_id     VARCHAR(64)  PRIMARY KEY
                 REFERENCES standing_agents(agent_id) ON DELETE CASCADE,
    channel_type VARCHAR(16)  NOT NULL
                 CHECK (channel_type IN ('slack', 'discord', 'telegram')),
    channel_id   VARCHAR(255) NOT NULL CHECK (btrim(channel_id) <> ''),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS standing_notifications (
    notification_id VARCHAR(64)  PRIMARY KEY,
    agent_id        VARCHAR(64)  NOT NULL
                    REFERENCES standing_agents(agent_id) ON DELETE CASCADE,
    kind            VARCHAR(32)  NOT NULL
                    CHECK (kind IN ('budget_warning', 'task_paused', 'question_changed')),
    dedupe_key      VARCHAR(255) NOT NULL,
    -- 목적지는 적을 때의 것이다. 대상을 바꿔도 이미 적힌 알림은 원래 곳으로 간다.
    channel_type    VARCHAR(16)  NOT NULL,
    channel_id      VARCHAR(255) NOT NULL,
    body            TEXT         NOT NULL,
    status          VARCHAR(16)  NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sent', 'failed')),
    attempts        INTEGER      NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_error      TEXT         NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    sent_at         TIMESTAMPTZ  NULL,
    CONSTRAINT uq_standing_notifications_dedupe UNIQUE (agent_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS idx_standing_notifications_due
    ON standing_notifications(next_attempt_at)
    WHERE status = 'pending';

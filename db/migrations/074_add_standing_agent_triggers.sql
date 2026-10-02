-- 상시 에이전트의 이벤트 트리거 (로드맵 트랙 Q4a, 2026-10-01).
-- 설계: docs/Q4_Q10_TRIGGER_BUDGET_DESIGN_261001.md §2
--
-- 서명된 webhook 배달 하나가 에이전트의 background 태스크 하나가 된다.
--
-- - 키는 agent_id 다(Q13 결정 6 · 설계 §4.3). owner_id 열은 없다 -- 소유 검사는
--   standing_agents 를 거쳐 조인한다.
-- - ON DELETE CASCADE: 사용자 삭제는 users -> standing_agents 로 CASCADE 된다. coding_tasks 는
--   owner_id 로도 함께 지워지지만 이 테이블엔 owner_id 가 없어 NO ACTION 이면 사용자 삭제가
--   막힌다. 트리거는 에이전트 없이 의미가 없다.
-- - source 는 지금 'webhook' 하나다. 채널 원천(Q4b)은 그것을 읽는 코드와 함께 CHECK 를 넓힌다.
-- - 서명 비밀은 저장하지 않는다. HMAC(NEOS_TRIGGER_SIGNING_KEY, trigger_id) 로 파생한다.
-- - filters 는 [{"path": "a.b", "equals": <JSON 값>}, ...] -- 전부 맞아야 발동한다. 빈 배열은 언제나.
-- - 배달 멱등성은 새 테이블이 아니라 channel_inbound_idempotency 를
--   session_id = 'trigger:{trigger_id}' 로 쓴다.
CREATE TABLE IF NOT EXISTS standing_agent_triggers (
    trigger_id      VARCHAR(64)  PRIMARY KEY,                     -- 'st_' + hex
    agent_id        VARCHAR(64)  NOT NULL REFERENCES standing_agents(agent_id) ON DELETE CASCADE,
    source          VARCHAR(16)  NOT NULL DEFAULT 'webhook'
                    CHECK (source IN ('webhook')),
    prompt_template TEXT         NOT NULL CHECK (btrim(prompt_template) <> ''),
    filters         JSONB        NOT NULL DEFAULT '[]'::jsonb
                    CHECK (jsonb_typeof(filters) = 'array'),
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ  NULL
);

CREATE INDEX IF NOT EXISTS ix_standing_agent_triggers_agent
    ON standing_agent_triggers(agent_id) WHERE deleted_at IS NULL;

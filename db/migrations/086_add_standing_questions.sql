-- 상시 질문 (로드맵 트랙 Q3, 2026-10-02).
-- 설계: docs/Q10B_Q3_PAUSE_STANDING_QUESTIONS_DESIGN_261002.md §5
--
-- 에이전트가 같은 질문을 주기적으로 심층분석(DA)에 다시 묻고, 직전 런과 verified 클레임
-- 집합이 달라졌을 때만 소유자에게 알린다. `scheduled_tasks` 를 넓히지 않는다(SQ1) --
-- 그 표는 `user_id` 키에 워크플로우 의미이고, 에이전트에 딸린 것은 `agent_id` 로 키를
-- 잡는다(Q13 §4.3).
--
-- 1. standing_questions -- 질문 하나와 그 주기. `next_run_at` 은 UTC cron 의 다음 회차.
--    `last_skip_reason` 은 막힌 회차의 사유(에이전트 멈춤·봉투) -- 다음 회차에 지워진다.
-- 2. standing_question_runs -- 질문이 연 DA 런 하나하나와 그 정산. 질문마다 진행 중
--    (`dispatched`)은 **하나**다(부분 unique 인덱스, SQ3) -- 겹친 런이 서로의 기준선이 되지 않게.
--    `diff` 는 정산한 차이(분류별 수와 해시), 기준선 회차면 `{"baseline": true}`.
--
-- 둘 다 `ON DELETE CASCADE` -- 에이전트·사용자·DA 런 삭제를 막지 않는다. 두 번 적용해도 같다.

CREATE TABLE IF NOT EXISTS standing_questions (
    question_id       VARCHAR(64)  PRIMARY KEY,
    agent_id          VARCHAR(64)  NOT NULL
                      REFERENCES standing_agents(agent_id) ON DELETE CASCADE,
    question          TEXT         NOT NULL CHECK (btrim(question) <> ''),
    cron_expression   VARCHAR(100) NOT NULL,
    enabled           BOOLEAN      NOT NULL DEFAULT TRUE,
    next_run_at       TIMESTAMPTZ  NOT NULL,
    last_skip_reason  VARCHAR(64)  NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at        TIMESTAMPTZ  NULL
);

CREATE INDEX IF NOT EXISTS idx_standing_questions_due
    ON standing_questions(next_run_at)
    WHERE enabled AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_standing_questions_agent
    ON standing_questions(agent_id)
    WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS standing_question_runs (
    question_id  VARCHAR(64)  NOT NULL
                 REFERENCES standing_questions(question_id) ON DELETE CASCADE,
    da_run_id    VARCHAR(8)   NOT NULL
                 REFERENCES deep_analysis_runs(id) ON DELETE CASCADE,
    status       VARCHAR(16)  NOT NULL DEFAULT 'dispatched'
                 CHECK (status IN ('dispatched', 'settled', 'failed')),
    diff         JSONB        NULL,
    notified     BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    settled_at   TIMESTAMPTZ  NULL,
    PRIMARY KEY (question_id, da_run_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_question_runs_one_in_flight
    ON standing_question_runs(question_id)
    WHERE status = 'dispatched';

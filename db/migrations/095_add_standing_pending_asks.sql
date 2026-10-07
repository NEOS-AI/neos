-- 상시 에이전트의 대기 질문 (로드맵 트랙 Q9a, 2026-10-05).
-- 설계: docs/Q9_ASK_AND_WAIT_DESIGN_261005.md §4
--
-- 에이전트의 autonomous 태스크가 `ask_user.v1` 을 부르면 질문 행 하나가 생기고 태스크는
-- `waiting_user` 로 선다. 답이 오면 `answered`, 시간이 지나면 `expired`, 태스크가 취소되면
-- `cancelled` 다.
--
-- - "에이전트당 대기 하나"는 부분 unique 인덱스 하나에만 산다(결정 6 과 같은 모양). 둘째
--   질문은 그 인덱스에 걸려 `ask_pending` 으로 거절된다.
-- - (task_id, run_id, tool_call_id) 유일 -- 재개한 루프가 자기 질문을 찾는 열쇠다(승인과 같다).
-- - `owner_id` 열이 없다. 소유 검사는 standing_agents · coding_tasks 를 조인한다(Q8 §4).
-- - 전부 ON DELETE CASCADE -- 사용자 삭제 한 문장이 에이전트·태스크와 함께 지운다.
--
-- 그리고 085 의 알림 kind CHECK 를 넓힌다: 질문 알림 `question_asked`(Q9b), 만료 알림
-- `ask_expired`(Q9d, 결정 Q-D). 085 의 CHECK 는 이름 없는 인라인 CHECK 이고, Postgres 가 붙인
-- 이름은 `standing_notifications_kind_check` 다 -- 테스트 DB 에서 확인했고
-- `tests/standing/test_pending_asks_contract.py` 가 그 이름 하나만 남는지 본다.
--
-- 두 번 적용해도 같다.

CREATE TABLE IF NOT EXISTS standing_pending_asks (
    ask_id           VARCHAR(64)  PRIMARY KEY,
    agent_id         VARCHAR(64)  NOT NULL
                     REFERENCES standing_agents(agent_id) ON DELETE CASCADE,
    task_id          VARCHAR(64)  NOT NULL
                     REFERENCES coding_tasks(task_id) ON DELETE CASCADE,
    run_id           VARCHAR(64)  NOT NULL
                     REFERENCES coding_runs(run_id) ON DELETE CASCADE,
    tool_call_id     VARCHAR(128) NOT NULL,
    questions        JSONB        NOT NULL,
    reply_session_id TEXT         NULL,
    status           VARCHAR(16)  NOT NULL DEFAULT 'waiting'
                     CHECK (status IN ('waiting', 'answered', 'expired', 'cancelled')),
    asked_at         TIMESTAMPTZ  NOT NULL,
    expires_at       TIMESTAMPTZ  NOT NULL,
    answered_at      TIMESTAMPTZ  NULL,
    answers          JSONB        NULL,
    CONSTRAINT ck_standing_pending_asks_expiry CHECK (expires_at > asked_at),
    CONSTRAINT ck_standing_pending_asks_answered
        CHECK ((status = 'answered') = (answered_at IS NOT NULL AND answers IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_pending_asks_one_waiting_per_agent
    ON standing_pending_asks(agent_id) WHERE status = 'waiting';

CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_pending_asks_call
    ON standing_pending_asks(task_id, run_id, tool_call_id);

CREATE INDEX IF NOT EXISTS ix_standing_pending_asks_due
    ON standing_pending_asks(expires_at) WHERE status = 'waiting';

ALTER TABLE standing_notifications DROP CONSTRAINT IF EXISTS standing_notifications_kind_check;
ALTER TABLE standing_notifications ADD CONSTRAINT standing_notifications_kind_check
    CHECK (kind IN (
        'budget_warning', 'task_paused', 'question_changed', 'question_asked', 'ask_expired'
    ));

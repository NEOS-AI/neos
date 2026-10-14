-- 작업 생명주기 (spec 2026-10-13 §4.4, W1 Plan 2). 전달 아웃박스는 Plan 2b 가 따로 만든다(아래).
--
-- 작업(work) = 입구에서 실행 한 번: 웹 메시지 · 채널 메시지 · 예약 실행 · 트리거로 열린 코딩 태스크.
-- 세션(096)은 "무엇을 기억하나", 작업은 "누가 언제 무엇을 했고 결과를 어디로 보내나" 다.
-- - 승인 대기의 정본은 `status = 'waiting_approval'` + `pending` 이다 -- 그래프 상태가 아니다
-- - `version` 은 낙관적 잠금 -- 같은 승인에 두 결정이 오면 하나만 재개된다
-- - 전달 아웃박스(`workflow_deliveries`)는 여기서 만들지 않는다 -- Plan 2b(단계 4)가 Q10b(085)의
--   모양으로 따로 만든다. `IF NOT EXISTS` 테이블을 덜 된 모양으로 먼저 깔면 이미 적용된 DB 에서는
--   나중 수정이 조용히 no-op 이 된다
--
-- 두 번 적용해도 같다.

CREATE TABLE IF NOT EXISTS workflow_runs (
    work_id         TEXT         PRIMARY KEY,
    entry           TEXT         NOT NULL CHECK (entry IN ('web', 'channel', 'schedule', 'trigger', 'api')),
    kind            TEXT         NOT NULL CHECK (kind IN ('workflow', 'deep_analysis', 'coding')),
    ref_id          TEXT         NULL,
    parent_work_id  TEXT         NULL REFERENCES workflow_runs(work_id) ON DELETE SET NULL,
    session_id      TEXT         NULL,
    user_id         TEXT         NOT NULL,
    status          TEXT         NOT NULL
                    CHECK (status IN ('running', 'waiting_approval', 'completed', 'failed', 'expired')),
    pending         JSONB        NULL,
    result          JSONB        NULL,
    delivery        JSONB        NOT NULL,
    version         INTEGER      NOT NULL CHECK (version >= 1),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_workflow_runs_pending
        CHECK ((status = 'waiting_approval') = (pending IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_waiting_session
    ON workflow_runs (session_id, updated_at DESC) WHERE status = 'waiting_approval';
CREATE INDEX IF NOT EXISTS idx_workflow_runs_ref
    ON workflow_runs (kind, ref_id) WHERE ref_id IS NOT NULL;

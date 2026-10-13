-- 채팅 워크플로의 세션 상태 (spec 2026-10-13 §4.3, W1 Plan 2).
--
-- 세션(웹은 conversation_id, 채널은 세션 키)마다 최신 스냅샷 한 행. LangGraph 체크포인터
-- (`langgraph_checkpoints`)를 대신한다 -- 그쪽은 Plan 3 에서 지운다.
-- - `state` 는 `neos/workflow/runtime/state_codec.py` 의 출력(타입 태그 JSON)
-- - `version` 은 낙관적 잠금 -- 겹친 턴은 나중 저장이 진다
-- - `user_id` 에 FK 를 걸지 않는다: 채널 사용자는 users 행이 없을 수 있다
-- - 보존 정리는 `updated_at` 으로(30일)
--
-- 두 번 적용해도 같다.

CREATE TABLE IF NOT EXISTS workflow_sessions (
    session_id  TEXT         PRIMARY KEY,
    user_id     TEXT         NOT NULL,
    state       JSONB        NOT NULL,
    version     INTEGER      NOT NULL CHECK (version >= 1),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workflow_sessions_updated_at
    ON workflow_sessions (updated_at);

-- 상시 에이전트 채널 횡단 스레드 (로드맵 트랙 Q8a, 2026-10-05).
-- 설계: docs/Q8_CROSS_CHANNEL_THREAD_DESIGN_261005.md §4
--
-- 셋이다.
--
-- 1. standing_agent_threads -- 에이전트의 맥락 단위. "활성 스레드는 에이전트당 하나"는 부분
--    unique 인덱스 하나에만 산다(결정 6 과 같은 모양). "새로 시작"은 활성 스레드를 보관하고
--    새로 여는 것이라(결정 Q8-2) 보관된 스레드는 몇 개든 남는다.
-- 2. standing_agent_thread_sessions -- 채널 세션(또는 'web:{conversation_id}') -> 스레드.
--    회전은 행을 지우지 않고 새 스레드로 옮긴다.
-- 3. standing_agent_thread_turns -- 턴 전사, append-only. 피드 커서용 `xact_id`(072 와 같다).
--
-- 전부 `ON DELETE CASCADE`. 스레드 행에는 `owner_id` 가 없어서(키는 agent_id 뿐, Q13 §9)
-- 사용자 삭제 -> 에이전트 CASCADE 가 여기까지 내려오지 않으면 NO ACTION 이 사용자 삭제를
-- 막는다. 에이전트의 soft delete 는 cascade 를 부르지 않으므로 저장소가 같은 트랜잭션에서
-- 스레드를 지운다(결정 Q8-4, `PostgresStandingAgentStore.delete`).
-- 두 번 적용해도 같다.

CREATE TABLE IF NOT EXISTS standing_agent_threads (
    agent_thread_id VARCHAR(64) PRIMARY KEY,
    agent_id        VARCHAR(64) NOT NULL
                    REFERENCES standing_agents(agent_id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at     TIMESTAMPTZ NULL
);

-- "하나"는 이 인덱스 하나에만 산다. F5(여러 프로젝트)로 늘릴 때 지우는 것이 이것이다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_agent_threads_one_active_per_agent
    ON standing_agent_threads(agent_id) WHERE archived_at IS NULL;

CREATE TABLE IF NOT EXISTS standing_agent_thread_sessions (
    session_id      TEXT        PRIMARY KEY CHECK (btrim(session_id) <> ''),
    agent_thread_id VARCHAR(64) NOT NULL
                    REFERENCES standing_agent_threads(agent_thread_id) ON DELETE CASCADE,
    channel_type    VARCHAR(16) NOT NULL
                    CHECK (channel_type IN ('slack', 'discord', 'telegram', 'web')),
    attached_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 회전이 붙은 세션을 스레드 단위로 옮긴다.
CREATE INDEX IF NOT EXISTS idx_standing_agent_thread_sessions_thread
    ON standing_agent_thread_sessions(agent_thread_id);

CREATE TABLE IF NOT EXISTS standing_agent_thread_turns (
    turn_id         BIGSERIAL   PRIMARY KEY,
    agent_thread_id VARCHAR(64) NOT NULL
                    REFERENCES standing_agent_threads(agent_thread_id) ON DELETE CASCADE,
    session_id      TEXT        NOT NULL,
    channel_type    VARCHAR(16) NOT NULL
                    CHECK (channel_type IN ('slack', 'discord', 'telegram', 'web')),
    role            VARCHAR(16) NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT        NOT NULL CHECK (btrim(content) <> ''),
    idem_key        TEXT        NULL,
    xact_id         xid8        NOT NULL DEFAULT pg_current_xact_id(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 재시도가 같은 턴을 두 번 쓰지 못한다(인바운드 멱등 키 · 웹은 저장된 메시지 id).
CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_agent_thread_turns_idem
    ON standing_agent_thread_turns(agent_thread_id, session_id, role, idem_key)
    WHERE idem_key IS NOT NULL;

-- 창 조립: 최근 N 개.
CREATE INDEX IF NOT EXISTS idx_standing_agent_thread_turns_window
    ON standing_agent_thread_turns(agent_thread_id, turn_id DESC);

-- `xact_id` 는 첫 쓰기부터 있어야 한다(지난 행에 트랜잭션 id 를 나중에 채울 수 없다). 그 열로
-- 읽는 피드 커서 인덱스 `(agent_thread_id, xact_id, turn_id)` 는 그것을 읽는 Q8c 가 더한다 --
-- 읽는 코드 없이 인덱스를 먼저 두지 않는다(Q13d 와 같은 규칙).

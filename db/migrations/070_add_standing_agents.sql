-- 상시 에이전트 개체 (로드맵 트랙 Q13a, 2026-09-30).
-- 설계: docs/Q13_STANDING_AGENT_DESIGN_260930.md §4.1
--
-- 태스크보다 오래 사는 1급 객체다. 사용자당 하나로 시작하고(결정 6), 그 "하나"는
-- 아래 첫 인덱스 **하나에만** 산다 -- 여럿으로 늘릴 때 지우는 것이 그것 하나다.
-- 에이전트에 딸리는 테이블은 전부 `agent_id` 로 키를 잡는다(설계 §4.3).
CREATE TABLE IF NOT EXISTS standing_agents (
    agent_id    VARCHAR(64)  PRIMARY KEY,
    owner_id    VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    -- 길이 제한 없음(Q13 결정 3). 빈 이름만 거절한다.
    name        TEXT         NOT NULL CHECK (btrim(name) <> ''),
    status      VARCHAR(16)  NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'paused', 'retired')),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ  NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_agents_one_per_owner
    ON standing_agents(owner_id) WHERE deleted_at IS NULL;

-- 같은 소유자 안에서 이름 중복 금지, 대소문자·앞뒤 공백 무시(Q13 결정 3).
-- 이름이 아니라 **해시**로 건다: 길이 제한 없는 TEXT 를 btree 에 그대로 넣으면
-- 약 2.7KB 를 넘는 이름이 INSERT 에서 실패한다. 여럿으로 늘릴 때도 남는 인덱스다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_agents_name_per_owner
    ON standing_agents(owner_id, md5(lower(btrim(name)))) WHERE deleted_at IS NULL;

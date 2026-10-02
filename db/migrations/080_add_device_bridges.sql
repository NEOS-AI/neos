-- 사용자 기기 브리지 페어링 자격증명 (로드맵 트랙 Q16a, 2026-10-01).
-- 설계: docs/Q16_DEVICE_BRIDGE_DESIGN_261001.md · 위협 모델: docs/Q16_DEVICE_BRIDGE_THREAT_MODEL.md
--
-- 토큰은 만들 때 한 번만 보이고 여기에는 SHA-256 해시만 남는다(B1). 폐기는 행 삭제다.
-- 키는 user_id 다 -- 기기는 사람의 것이지 에이전트의 것이 아니다(B1, Q6 S4 와 같은 이유).
-- 동시에 붙는 연결은 사용자당 하나이고(B5) 그것은 DB 가 아니라 연결 표시(Redis)가 정한다.
CREATE TABLE IF NOT EXISTS device_bridges (
    bridge_id         VARCHAR(64)  PRIMARY KEY CHECK (bridge_id ~ '^dbr_[0-9a-f]{24}$'),
    user_id           VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name              VARCHAR(64)  NOT NULL CHECK (name ~ '^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$'),
    token_hash        CHAR(64)     NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    -- 아무도 보지 않는 런(autonomous·background)이 이 기기를 읽어도 되는가(B7). 기본은 아니다.
    allow_unattended  BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_connected_at TIMESTAMPTZ,
    UNIQUE (user_id, name)
);

-- 사용자 비밀 금고 (로드맵 트랙 Q6, 2026-10-01).
-- 설계: docs/Q6_CREDENTIAL_BROKER_DESIGN_261001.md
--
-- 도구 인자에는 `secret://<name>` 참조만 실리고 실행기가 실행 직전에 푼다.
-- 값은 AES-GCM 봉인(S5) -- 키는 NEOS_SECRET_BROKER_KEY 에서 파생하고 DB 에는 없다.
-- AAD 가 user_id:name 이라 행을 다른 사용자·이름으로 옮기면 풀리지 않는다.
-- env_name 은 이 비밀을 실을 수 있는 유일한 환경변수다(S3).
CREATE TABLE IF NOT EXISTS user_secrets (
    user_id     VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name        VARCHAR(64)  NOT NULL CHECK (name ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    env_name    VARCHAR(64)  NOT NULL CHECK (env_name ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    ciphertext  BYTEA        NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, name)
);

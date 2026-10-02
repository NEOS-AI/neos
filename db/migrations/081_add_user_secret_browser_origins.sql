-- 비밀별 브라우저 출처 묶임 (로드맵 트랙 Q14b, 2026-10-02).
-- 설계: docs/Q14_AGENT_BROWSER_DESIGN_261001.md §7 (X1~X3)
--
-- browser_fill_secret.v1 은 이 배열에 있는 https 출처에만 비밀을 입력한다. 기본은 빈 배열 --
-- 077 의 기존 행은 execute.v1·커넥터(env_name, S3)에는 그대로 쓰이고 브라우저에는
-- 어디에도 입력되지 않는다(fail closed). 소유자가 PUT 으로 출처를 적어야 열린다.
-- 출처는 AAD 에도 실린다(neos/coding/secrets.py `_cipher`) -- 키 없이 이 칸만 고치면 풀리지 않는다.
-- 상한 8 은 `MAX_BROWSER_ORIGINS` 와 같다. 두 번 적용해도 같다(IF NOT EXISTS 가 CHECK 까지 건너뛴다).
ALTER TABLE user_secrets
    ADD COLUMN IF NOT EXISTS browser_origins TEXT[] NOT NULL DEFAULT '{}'
        CHECK (cardinality(browser_origins) <= 8);

BEGIN;

-- provider 서킷 상태와 운영자 드레인을 **프로세스 밖으로** 옮긴다.
--
-- 045 까지 `ProviderHealthCircuit` 은 순수 인메모리였다. 그 결과 두 가지가
-- 깨져 있었다(로드맵 CA8·CA11):
--   * beat 의 헬스 프로브가 호출마다 새 서킷을 만들어 롤링 윈도가 이어지지
--     않았다 -- 비율 판정이 아예 성립하지 않았다.
--   * API 프로세스에서 켠 드레인을 Celery 워커가 몰랐다.
--
-- 설계 결정 둘.
--   1. `failure_window` 는 판정 **결과**가 아니라 판정의 **재료**다. 비율
--      계산을 SQL 로 옮기지 않고 창만 실어 나른다 -- 판정 로직은
--      `neos.coding.managed.health.ProviderHealthCircuit` 한 곳에 남는다.
--   2. `drained` 는 서킷이 쓰는 컬럼이 **아니다.** 같은 컬럼에 합치면 정상
--      프로브 한 번이 운영자의 드레인을 지운다. 읽는 쪽에서 합친다:
--      "드레인됐거나 서킷이 UNAVAILABLE 이면 신규 admission 을 막는다".
CREATE TABLE coding_sandbox_provider_health (
    provider VARCHAR(64) NOT NULL,
    region VARCHAR(64) NOT NULL,
    circuit_state VARCHAR(16) NOT NULL DEFAULT 'healthy'
        CHECK (circuit_state IN ('healthy', 'degraded', 'unavailable')),
    -- 관측 창. `true` 가 실패다. 길이는 애플리케이션의
    -- `sandbox.managed.health_window_size` 가 정하고 100 을 넘지 않는다.
    failure_window BOOLEAN[] NOT NULL DEFAULT ARRAY[]::BOOLEAN[]
        CHECK (array_length(failure_window, 1) IS NULL
               OR array_length(failure_window, 1) <= 100),
    drained BOOLEAN NOT NULL DEFAULT FALSE,
    drained_at TIMESTAMPTZ,
    -- 운영자 식별자. 감사용이며 메트릭 라벨로 쓰지 않는다.
    drained_by VARCHAR(255),
    version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (provider, region),
    CHECK (
        (drained AND drained_at IS NOT NULL)
        OR (NOT drained AND drained_at IS NULL AND drained_by IS NULL)
    )
);

COMMIT;

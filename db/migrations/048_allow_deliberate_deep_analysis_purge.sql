-- Migration 048: 의도적인 purge 만 append-only 트리거를 통과한다 (SCHEMA2)
--
-- 036 이 두 가지를 동시에 걸어 놓았다:
--   - `deep_analysis_events.run_id` 가 `deep_analysis_runs(id)` 를
--     `ON DELETE CASCADE` 로 참조한다
--   - 같은 테이블에 `BEFORE UPDATE OR DELETE` 트리거가 있고 무조건
--     `RAISE EXCEPTION 'deep_analysis_events is append-only'` 한다
--
-- 겹치면 **이벤트가 하나라도 있는 run 은 삭제할 수 없다.** run 을 지우려 하면
-- CASCADE 가 events 의 DELETE 를 시도하고 트리거가 그것을 거부한다. 테스트만의
-- 문제가 아니라 프로덕션도 그렇다 -- 대화 삭제나 보존기한 요구가 생기면 여기서
-- 걸린다(로드맵 §7 SCHEMA2, D66 이 관측).
--
-- 무엇을 바꾸고 무엇을 바꾸지 않는가
-- ---------------------------------------------------------------------
-- append-only(설계 §1 P2 · D8)를 없애서 풀지 않는다. 그것은 §2.3 이 타협 불가로
-- 못박은 넷 중 하나이고, `deep_analysis_events` 는 §10.1 이 "지우면 재현 불가" 로
-- 적은 증거 테이블이다 -- 로드맵 §5.2 의 수치가 그 테이블 하나에 걸려 있다.
--
-- 대신 **기본은 그대로 거부하고, 의도를 표명한 트랜잭션만** 통과시킨다. 트리거
-- 함수가 세션 변수를 확인하며, 그 변수는 `SET LOCAL` 로만 세워지므로 트랜잭션이
-- 끝나면 사라진다. 이것이 이 설계의 안전장치 전부다 -- 플래그가 세션에 남으면
-- 그 커넥션이 풀로 돌아간 뒤 다음 요청이 append-only 없이 돈다.
--
-- 트리거 자체는 건드리지 않는다(`CREATE OR REPLACE FUNCTION` 만). 트리거를
-- DROP/CREATE 하면 그 사이 짧은 창에서 보호가 없다.
--
-- ⚠️ **이 마이그레이션은 purge 를 일으키지 않는다.** 경로를 열 뿐이고 호출자는
-- 없다. 보존기한 정책이나 대화 삭제 UI 는 별개 결정이다 -- 지금 바뀌는 것은
-- "구조적으로 불가능" 이 "정책이 정하면 가능" 이 되는 것뿐이다.

CREATE OR REPLACE FUNCTION deep_analysis_events_reject_mutation()
RETURNS TRIGGER AS $$
BEGIN
    -- `current_setting(..., true)` 의 둘째 인자는 "설정이 없으면 에러 대신
    -- NULL" 이다. 없는 것이 정상 경로이므로 NULL 이 거부로 이어져야 한다 --
    -- `IS DISTINCT FROM` 을 쓰는 이유가 그것이다(`<>` 는 NULL 에서 NULL 이라
    -- IF 가 거짓이 되고 **조용히 통과**한다).
    IF current_setting('deep_analysis.allow_purge', true)
       IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'deep_analysis_events is append-only';
    END IF;

    -- 통과 경로. DELETE 트리거는 OLD 를, UPDATE 트리거는 NEW 를 돌려줘야
    -- 하므로 둘을 함께 다룬다.
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION deep_analysis_events_reject_mutation() IS
    'append-only 가드. deep_analysis.allow_purge = ''on'' 인 트랜잭션에서만 '
    '변경을 허용한다 (SCHEMA2, 마이그레이션 048).';

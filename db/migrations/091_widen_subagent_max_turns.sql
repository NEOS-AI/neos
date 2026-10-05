-- 서브에이전트 티켓의 턴 상한 8 → 12 (DECISIONS D114, 2026-10-05).
--
-- 055 가 `CHECK (max_turns BETWEEN 1 AND 8)` 를 이름 없이 걸었다 -- Postgres 가 붙인 이름이
-- `subagent_runs_max_turns_check` 다. 코드의 상한(`neos.subagent.types.MAX_TICKET_TURNS`)을 12 로
-- 올리자 compose 자식의 행이 이 제약에서 거절됐다(D114 라이브 dry run). 메모리 스토어는 제약이
-- 없어 단위 테스트가 못 봤다. 상한은 코드와 같아야 한다 -- `tests/subagent/test_postgres_cas.py` 가 맞춘다.
-- 두 번 적용해도 같다(지우고 다시 건다).
ALTER TABLE subagent_runs DROP CONSTRAINT IF EXISTS subagent_runs_max_turns_check;
ALTER TABLE subagent_runs
    ADD CONSTRAINT subagent_runs_max_turns_check CHECK (max_turns BETWEEN 1 AND 12);

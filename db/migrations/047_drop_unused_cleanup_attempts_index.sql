-- Migration 047: cleanup_attempts 부분 인덱스를 실제로 쓰이는 형태로 고친다 (CA9)
--
-- 045 는 이 인덱스를 이렇게 만들었다:
--
--     CREATE INDEX idx_coding_sandbox_cleanup_attempts_pending
--         ON coding_sandbox_cleanup_attempts(allocation_id, next_retry_at)
--         WHERE finished_at IS NULL;
--
-- 그런데 시도 행은 **완료 시점에 한 번만** 쓰인다 -- `commit_cleanup_outcome()`
-- 의 INSERT 가 `finished_at = now` 를 함께 싣는다(`repository.py`). 즉
-- `finished_at IS NULL` 인 행은 만들어지지 않고, 이 부분 인덱스는 **항상 비어
-- 있다.** Task 6 이 minor 로 유예했고 로드맵이 CA9 로 추적하던 항목이다.
--
-- 판정 -- 지우기만 하지 않는다 (2026-08-25).
-- ---------------------------------------------------------------------
-- CA9 의 원문은 "쓰이지 않으니 삭제"였다. 그러나 이 테이블을 읽는 질의 셋이
-- **전부 같은 두 컬럼을 쓴다**:
--
--   - `mark_cleanup_ready()`      WHERE allocation_id = ? AND next_retry_at > ?
--   - `count_cleanup_attempts()`  WHERE allocation_id = ?
--   - `reconcile()` 의 NOT EXISTS  WHERE allocation_id = ? AND next_retry_at > ?
--
-- 즉 **컬럼 선택은 옳았고 부분 조건만 틀렸다.** 그냥 지우면 조정 사이클이
-- 매번 seq scan 으로 떨어진다 -- 쓰이지 않는 인덱스를 없애려다 쓰이던 접근
-- 경로를 없애는 셈이다. 그래서 조건만 떼고 살린다.
--
-- 이름을 바꾸는 이유: `_pending` 은 "아직 안 끝난 시도"라는 뜻인데 그런 행은
-- 존재하지 않는다. 이름이 거짓이면 다음 사람이 부분 조건을 되살린다.

DROP INDEX IF EXISTS idx_coding_sandbox_cleanup_attempts_pending;

CREATE INDEX IF NOT EXISTS idx_coding_sandbox_cleanup_attempts_retry
    ON coding_sandbox_cleanup_attempts(allocation_id, next_retry_at);

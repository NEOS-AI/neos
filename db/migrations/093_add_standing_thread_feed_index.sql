-- 상시 에이전트 스레드 턴 피드 커서 인덱스 (로드맵 트랙 Q8c, 2026-10-05).
-- 설계: docs/Q8_CROSS_CHANNEL_THREAD_DESIGN_261005.md §4 · §9
--
-- 피드 커서는 `(xact_id, turn_id)` 이고 독자는 `pg_snapshot_xmin` 미만만 읽는다(072 · Q13d 와
-- 같은 이유: `turn_id` 순서는 커밋 순서가 아니라서, 늦게 커밋된 턴이 이미 지나간 커서 뒤로
-- 떨어져 영영 건너뛰어진다). `xact_id` 열은 092 가 첫 쓰기부터 채웠다. 이 인덱스는 그 열을
-- 읽는 Q8c 와 함께 온다 -- 읽는 코드 없이 인덱스를 먼저 두지 않았다.
-- 두 번 적용해도 같다.

CREATE INDEX IF NOT EXISTS idx_standing_agent_thread_turns_feed
    ON standing_agent_thread_turns(agent_thread_id, xact_id, turn_id);

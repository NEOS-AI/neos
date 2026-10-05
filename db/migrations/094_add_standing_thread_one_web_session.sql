-- 상시 에이전트 스레드의 웹 세션은 하나 (로드맵 트랙 Q8d, 2026-10-05).
-- 설계: docs/Q8_CROSS_CHANNEL_THREAD_DESIGN_261005.md §5 · §9 (결정 Q8-3)
--
-- 웹 "에이전트 대화"는 에이전트당 하나다. 붙는 곳은 늘 활성 스레드이고 회전은 세션 행을 옮기므로
-- "스레드당 웹 세션 하나"가 곧 "에이전트당 하나"다. 동시에 두 번 만들면 둘째의 붙이기가 이
-- 인덱스에 걸린다 -- 엔드포인트는 만든 대화를 지우고 이긴 쪽을 돌려준다.
-- 두 번 적용해도 같다.

CREATE UNIQUE INDEX IF NOT EXISTS uq_standing_agent_thread_sessions_one_web
    ON standing_agent_thread_sessions(agent_thread_id) WHERE channel_type = 'web';

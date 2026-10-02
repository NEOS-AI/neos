-- 코딩 태스크 모드에 background 를 더한다 (로드맵 트랙 Q1, 2026-09-30).
--
-- background = 아무도 시키지 않은 일(선제적 조사). 보는 사람이 없으므로
--              autonomous 처럼 승인 요구가 거절로 접히고, 천장이 READ_ONLY 다 --
--              쓰기·명령·질문·자식 생성은 `policy_mode_ceiling` 으로 거절된다.
--
-- 068 의 CHECK 는 이름 없이 인라인으로 만들어져 Postgres 가 붙인 이름
-- (`coding_tasks_mode_check`)을 쓴다. 이름을 고정해 다시 건다.
ALTER TABLE coding_tasks DROP CONSTRAINT IF EXISTS coding_tasks_mode_check;
ALTER TABLE coding_tasks
    ADD CONSTRAINT coding_tasks_mode_check
        CHECK (mode IN ('interactive', 'autonomous', 'background'));

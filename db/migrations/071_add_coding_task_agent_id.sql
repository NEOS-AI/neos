-- 코딩 태스크를 연 상시 에이전트 (로드맵 트랙 Q13c, 2026-09-30).
-- 설계: docs/Q13_STANDING_AGENT_DESIGN_260930.md §4.2 · §5
--
-- NULL = 사람이 직접 연 태스크(지금까지의 전부). 에이전트가 연 태스크도
-- `owner_id` 는 에이전트의 소유자다 -- 소유 검사는 지금처럼 `owner_id` 하나로 하고,
-- 이 열은 권한에 쓰지 않는다(에이전트를 끼웠다고 소유 검사 경로가 둘이 되면 안 된다).
--
-- ON DELETE 는 걸지 않는다(기본 NO ACTION). 에이전트 삭제는 `deleted_at` 이고,
-- 사용자 삭제는 standing_agents 와 coding_tasks 를 같은 문장 안에서 함께 지운다
-- (둘 다 users 에 CASCADE) -- NO ACTION 은 문장 끝에 검사하므로 막히지 않는다.
--
-- `(agent_id, last_activity_at)` 인덱스는 여기서 만들지 않는다. 그것을 읽는
-- 활동 피드(Q13d)가 함께 만든다 -- 읽는 코드 없이 먼저 두지 않는다(설계 §9).
ALTER TABLE coding_tasks
    ADD COLUMN IF NOT EXISTS agent_id VARCHAR(64) NULL
        REFERENCES standing_agents(agent_id);

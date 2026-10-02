-- 상시 에이전트 활동 피드의 커서 (로드맵 트랙 Q13d, 2026-09-30).
-- 설계: docs/Q13_STANDING_AGENT_DESIGN_260930.md §7.1
--
-- 활동 피드는 에이전트가 연 태스크 **여럿**의 원장을 하나로 합친다. 태스크마다 `seq`
-- 가 따로라 `seq` 는 합친 커서가 못 되고, `created_at` 도 못 된다: 호출자가 넘긴
-- 시계이고 태스크마다 다른 트랜잭션이 따로 커밋하므로, 이른 `created_at` 이 늦게
-- 커밋되면 이미 지나간 커서 뒤로 떨어져 **영영 건너뛰어진다**.
--
-- 그래서 쓴 트랜잭션의 id 를 적는다. 독자는 `pg_snapshot_xmin`(아직 안 끝난
-- 트랜잭션 중 가장 작은 id) **미만만** 읽는다 -- 그 아래는 전부 끝났고, 앞으로
-- 커밋될 것은 전부 그 이상이라 커서 뒤로 떨어지지 않는다. 대가: 오래 열린
-- 트랜잭션이 있으면 피드가 그만큼 **늦는다**(건너뛰지는 않는다).
--
-- 열을 NULL 로 더한 뒤 기본값을 거는 두 단계다 -- 휘발성 기본값을 ADD COLUMN 에
-- 바로 걸면 테이블 전체를 다시 쓴다. 기존 행은 NULL 로 남고 피드에 나오지 않는다.
-- 에이전트 태스크는 071 이후에만 생기고 071·072 는 같이 배포되므로 잃는 것이 없다.
ALTER TABLE coding_events ADD COLUMN IF NOT EXISTS xact_id xid8 NULL;
ALTER TABLE coding_events ALTER COLUMN xact_id SET DEFAULT pg_current_xact_id();

CREATE INDEX IF NOT EXISTS idx_coding_events_task_xact
    ON coding_events(task_id, xact_id, seq);

-- 피드는 에이전트의 태스크부터 고른다. 설계 §4.2 의 `(agent_id, last_activity_at)`
-- 는 최근순 태스크 목록용이었는데 그것을 읽는 코드가 없다 -- 읽는 쪽에 맞췄다.
CREATE INDEX IF NOT EXISTS idx_coding_tasks_agent
    ON coding_tasks(agent_id) WHERE agent_id IS NOT NULL;

-- 상시 에이전트의 자기소개(온보딩) (로드맵 트랙 Q13f, 2026-10-01).
-- 설계: docs/Q13_STANDING_AGENT_DESIGN_260930.md §8
--
-- 만들어질 때 background 태스크 하나를 연다. 그 태스크가 **성공으로** 끝나면 최종
-- 답이 자기소개 메모(STAGED)가 된다.
--
-- onboarding_task_id: 어느 태스크가 자기소개인가. 완료 훅이 읽는다. FK 는 걸지 않는다 --
--   coding_tasks.agent_id 가 이미 이 테이블을 가리켜 둘이 서로를 가리키게 된다.
--   값이 있으면 덮어쓰지 않는다(한 번만 연다).
-- onboarded_at: 메모를 남겼다. 완료 훅이 두 번 불려도 메모는 하나다 -- 이 열을
--   조건부로 먼저 채운 쪽만 쓴다.
ALTER TABLE standing_agents ADD COLUMN IF NOT EXISTS onboarding_task_id VARCHAR(64) NULL;
ALTER TABLE standing_agents ADD COLUMN IF NOT EXISTS onboarded_at TIMESTAMPTZ NULL;

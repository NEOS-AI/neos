-- 트랙 J (2026-09-20): `/evidence` 한도를 질문 단위로 센다.
--
-- 계약 §9 결정 4 가 한도를 "질문별 blob 합계" 로 정했는데, 기존 스키마에는
-- 그것을 셀 자리가 없었다. `deep_analysis_blobs` 의 PK 는
-- (run_id, content_hash) 라 질문을 모르고, `deep_analysis_evidence` 는
-- 클레임이 생긴 **뒤에야** blob 을 가리킨다 -- 한도는 fetch 시점에 걸어야
-- 하므로 그 표에서 합을 낼 수 없다.
--
-- 메모리가 아니라 열인 이유: run 은 재개된다(`job_resumed`). 메모리에 세면
-- 재개된 run 이 자기가 쓴 양을 잊고 한도를 넘는다.
--
-- `spent_tokens` 와 같은 모양이다 -- 한도가 있는 자원을 질문 단위로 세고,
-- 남은 양을 빼서 본다.
ALTER TABLE deep_analysis_questions
    ADD COLUMN IF NOT EXISTS evidence_bytes INTEGER NOT NULL DEFAULT 0;

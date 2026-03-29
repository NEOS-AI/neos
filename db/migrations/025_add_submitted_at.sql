-- Phase 8 A2UI: 중복 폼 제출 방어용 submitted_at 컬럼
-- UIFrameSession에 submitted_at을 추가하여 동일 frame_id 중복 제출을 원자적으로 방지한다.
-- NULL = 미제출, NOT NULL = 이미 제출됨 → HTTP 409 Conflict 반환

ALTER TABLE ui_frame_sessions
    ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMP NULL;

COMMENT ON COLUMN ui_frame_sessions.submitted_at
    IS 'NULL=미제출, NOT NULL=이미 제출됨 (중복 제출 방어)';

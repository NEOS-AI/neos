-- UI 폼 세션 저장 테이블
-- UIFrameGenerator가 생성한 frame_id → (original_query, conversation_id) 매핑
-- POST /api/v1/ui/submit 수신 시 원본 쿼리 복원에 사용

CREATE TABLE IF NOT EXISTS ui_frame_sessions (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    frame_id         UUID         UNIQUE NOT NULL,
    session_id       VARCHAR(255) NOT NULL,
    user_id          VARCHAR(255) REFERENCES users(user_id) ON DELETE SET NULL,
    conversation_id  UUID         NULL,
    original_query   TEXT         NOT NULL,
    frame_data       JSONB        DEFAULT '{}',   -- UIFrame 전체 JSON (디버깅용)
    expires_at       TIMESTAMP    NOT NULL,
    created_at       TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ui_frame_sessions_frame_id
    ON ui_frame_sessions(frame_id);

CREATE INDEX IF NOT EXISTS idx_ui_frame_sessions_expires_at
    ON ui_frame_sessions(expires_at);

-- 만료된 레코드 자동 정리 (선택적 — pg_cron 또는 별도 Celery Beat 태스크로 실행)
-- DELETE FROM ui_frame_sessions WHERE expires_at < NOW();

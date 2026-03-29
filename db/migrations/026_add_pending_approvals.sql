-- Migration 026: Execution Approval 타임아웃 추적 테이블
-- APPROVAL_TIMEOUT_SECONDS를 실제로 강제하기 위한 경량 추적 테이블.
-- Celery Beat 태스크(expire_pending_approvals)가 5분마다 만료 항목을 자동 거부한다.

CREATE TABLE IF NOT EXISTS pending_approvals (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   VARCHAR(255) NOT NULL,
    request_id   VARCHAR(255) NOT NULL,
    user_id      VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    skill_name   VARCHAR(100) NOT NULL,
    requested_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMP    NOT NULL,
    resolved     BOOLEAN      NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_pending_request_id UNIQUE (request_id)
);

CREATE INDEX IF NOT EXISTS idx_pending_approvals_expires_unresolved
    ON pending_approvals(expires_at)
    WHERE resolved = FALSE;

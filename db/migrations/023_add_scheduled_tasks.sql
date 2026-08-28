-- Migration 023: Add scheduled_tasks table
-- (OpenClaw Cron 스케줄 스킬): 사용자 반복 태스크 등록 테이블
-- Celery Beat 폴러가 매 1분마다 next_run_at을 확인해 만기 태스크를 워크플로우에 제출한다.

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,

    -- 태스크 정보
    title           VARCHAR(500) NOT NULL,        -- 사용자가 입력한 원본 요청
    query           TEXT        NOT NULL,          -- 워크플로우에 전달할 쿼리
    cron_expression VARCHAR(100) NOT NULL,         -- 예: "0 9 * * *" (매일 오전 9시)
    timezone        VARCHAR(100) NOT NULL DEFAULT 'UTC',

    -- 채널 라우팅
    channel_type    VARCHAR(50)  NOT NULL DEFAULT 'api',   -- api | telegram | discord
    channel_id      VARCHAR(500),                          -- 외부 채널 ID (텔레그램 chat_id 등)

    -- 상태 관리
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    last_run_at     TIMESTAMP,
    next_run_at     TIMESTAMP   NOT NULL,          -- 다음 실행 예정 시각 (UTC)
    run_count       INTEGER     NOT NULL DEFAULT 0,
    last_error      TEXT,                          -- 마지막 실패 오류 메시지

    -- 타임스탬프
    created_at      TIMESTAMP   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP   NOT NULL DEFAULT NOW()
);

-- 폴러 쿼리 최적화: is_active=TRUE인 태스크 중 next_run_at <= NOW() 조회
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run
    ON scheduled_tasks (next_run_at)
    WHERE is_active = TRUE;

-- 사용자별 태스크 목록 조회 최적화
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_user_id
    ON scheduled_tasks (user_id);

-- updated_at 자동 갱신 트리거
-- SQLAlchemy onupdate는 Python 레이어에서만 동작하므로,
-- raw SQL / Alembic / 다른 DB 클라이언트 업데이트에도 updated_at이 갱신되도록 보장한다.
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE 'plpgsql';

DROP TRIGGER IF EXISTS update_scheduled_tasks_updated_at ON scheduled_tasks;
CREATE TRIGGER update_scheduled_tasks_updated_at
    BEFORE UPDATE ON scheduled_tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

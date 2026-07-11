-- Migration 037: Deep Analysis Harness — L5 improvement-report table
-- L5 개선 루프(Sub-project B): 주기 Celery 태스크가 계산한 개선 신호 롤링 리포트를 저장.
-- events는 read-only(§11.3, D8); 리포트는 이 별도 테이블에만 쓴다.

CREATE TABLE IF NOT EXISTS deep_analysis_reports (
    id           BIGSERIAL   PRIMARY KEY,
    period_start TIMESTAMP   NOT NULL,        -- 롤링 윈도우 시작 (UTC)
    period_end   TIMESTAMP   NOT NULL,        -- 롤링 윈도우 끝 (UTC)
    signals      JSONB       NOT NULL,        -- DeepAnalysisAnalyticsService.signals() 결과
    created_at   TIMESTAMP   NOT NULL DEFAULT NOW()
);

-- 최신 리포트 조회 최적화
CREATE INDEX IF NOT EXISTS idx_da_reports_created
    ON deep_analysis_reports (created_at DESC);

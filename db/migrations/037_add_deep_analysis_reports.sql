-- Migration 037: Deep Analysis Harness — L5 improvement-report table
-- L5 개선 루프(Sub-project B): 주기 Celery 태스크가 계산한 개선 신호 롤링 리포트를 저장.
-- events는 read-only(§11.3, D8); 리포트는 이 별도 테이블에만 쓴다.

CREATE TABLE IF NOT EXISTS deep_analysis_reports (
    id           BIGSERIAL   PRIMARY KEY,
    period_start TIMESTAMP   NOT NULL,        -- 롤링 윈도우 시작 (naive UTC)
    period_end   TIMESTAMP   NOT NULL,        -- 롤링 윈도우 끝 (naive UTC)
    signals      JSONB       NOT NULL,        -- DeepAnalysisAnalyticsService.signals() 결과
    -- ORM 기본값(utc_now_naive)과 일치하도록 세션 TZ가 아닌 UTC naive로 강제
    created_at   TIMESTAMP   NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
);

-- 최신 리포트 조회 최적화
CREATE INDEX IF NOT EXISTS idx_da_reports_created
    ON deep_analysis_reports (created_at DESC);

-- L5 analytics의 시간 윈도우 필터(ts >= since)용 인덱스.
-- (036은 (run_id, qid, kind)만 인덱싱해 ts 필터가 풀스캔이었음.)
CREATE INDEX IF NOT EXISTS idx_da_events_ts
    ON deep_analysis_events (ts);

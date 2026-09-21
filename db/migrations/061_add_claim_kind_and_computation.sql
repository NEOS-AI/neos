-- 트랙 J (2026-09-21): 계산 클레임을 저장할 자리.
--
-- 지금까지 `deep_analysis_claims` 에는 클레임의 **종류**가 없었다. 저장되는
-- 것이 전부 quote 라 필요가 없었기 때문이다. 계산 클레임(계약 §4)이 들어오면
-- 그 전제가 되는 `ComputedEvidence` -- 스크립트·입력·전제·런타임·digest --
-- 를 둘 곳도 없다. `deep_analysis_evidence` 는 quote 전용이다: `source_url`
-- 과 `excerpt` 가 NOT NULL 이고 `raw_ref` 가 blob 에 FK 로 걸려 있어, 계산
-- 증거를 거기 욱여넣으려면 빈 문자열과 가짜 참조를 만들어야 한다.
--
-- ## 기본값이 'quote' 인 이유는 그것이 참이기 때문이다
--
-- 기존 행은 전부 quote 다. 계산 클레임을 만드는 analyze 명세는
-- `code_research.specs_enabled` 에 없고, 그래서 지금까지 어떤 run 도 계산
-- 클레임을 제출할 수 없었다. 기본값은 "모르니까 이걸로 두자" 가 아니라
-- 측정된 사실이다.
--
-- ## 채점기의 전제 검사가 이 컬럼에 기댄다
--
-- 계약 §5 는 `premises` 가 "verified **quote** 클레임" 이어야 한다고 적는다.
-- 컬럼이 없던 동안 `graders/computed.py` 는 `status` 만 봤고, 저장된 것이
-- 전부 quote 였으므로 그 검사는 **그 사이에는 정확했다.** 이 마이그레이션이
-- 그 전제를 깨므로 같은 커밋에서 검사도 조인다 -- 컬럼만 넣고 검사를 두면
-- 계산 위에 계산을 쌓는 사슬이 열린다. 그 사슬의 어느 고리도 fetch 된
-- 원문에 닿지 않는다.
--
-- `computation` 은 TEXT + JSON 문자열이다. `deep_analysis_events.payload` 와
-- 같은 모양을 따른다 -- 이 스키마에 JSONB 를 쓰는 표가 아직 없고, 여기에
-- 처음 들이면 같은 저장소에 직렬화 규약이 둘이 된다.
ALTER TABLE deep_analysis_claims
    ADD COLUMN IF NOT EXISTS kind VARCHAR(12) NOT NULL DEFAULT 'quote';

ALTER TABLE deep_analysis_claims
    ADD COLUMN IF NOT EXISTS computation TEXT;

-- CHECK 은 멱등하게 건다. `ADD CONSTRAINT ... IF NOT EXISTS` 가 없으므로
-- 존재를 먼저 묻는다 -- 두 번 적용해도 같은 스키마여야 한다(`db-verify` 가
-- 재적용까지 본다).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_deep_analysis_claims_kind'
    ) THEN
        ALTER TABLE deep_analysis_claims
            ADD CONSTRAINT ck_deep_analysis_claims_kind
            CHECK (kind IN ('quote', 'computed'));
    END IF;
END $$;

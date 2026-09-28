-- 코딩 태스크의 실행 모드 (로드맵 K9, 2026-09-28 사용자 결정: 태스크 요청 필드).
--
-- interactive = 사람이 Code UI 로 보고 승인한다(지금까지의 유일한 모드).
-- autonomous  = 아무도 보지 않는다. 승인 요구는 기다리지 않고 거절로 접히고
--               (D-L1 의 unattended 접기), 자율 오버레이 자리가 켜진다.
--
-- 태스크 행에 두는 이유: 재개·워커 이관·safe point 에서도 같은 모드여야 한다.
-- 기본값이 interactive 라 기존 행과 모드를 모르는 호출자는 전과 같다.
ALTER TABLE coding_tasks
    ADD COLUMN IF NOT EXISTS mode VARCHAR(16) NOT NULL DEFAULT 'interactive'
        CHECK (mode IN ('interactive', 'autonomous'));

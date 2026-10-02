-- 기기 브리지 쓰기 허락 (로드맵 트랙 Q16b, 2026-10-02).
-- 설계: docs/Q16_DEVICE_BRIDGE_DESIGN_261001.md §6 · 위협 모델: docs/Q16_DEVICE_BRIDGE_THREAT_MODEL.md §4
--
-- 브리지가 쓰기 도구(write_file, WORKSPACE_WRITE)를 선언해도 되는가(BW2). 기본은 아니다 --
-- 클라이언트의 --allow-writes 와 이 열이 둘 다 참이어야 선언이 받아진다. allow_unattended 와
-- 따로다: 무인 런의 쓰기는 이 열과 상관없이 늘 거절된다(BW4).
-- 080 이 만든 표에 열 하나를 더한다(번호순이 080 뒤를 보장한다). 두 번 적용해도 같다.
ALTER TABLE device_bridges
    ADD COLUMN IF NOT EXISTS allow_writes BOOLEAN NOT NULL DEFAULT FALSE;

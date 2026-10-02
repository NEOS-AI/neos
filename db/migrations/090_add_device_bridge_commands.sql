-- 기기 브리지 명령 허락 (로드맵 트랙 Q16c, 2026-10-02).
-- 설계: docs/Q16_DEVICE_BRIDGE_DESIGN_261001.md §7 · 위협 모델: docs/Q16_DEVICE_BRIDGE_THREAT_MODEL.md §5
--
-- 브리지가 명령 도구(run_command, COMMAND)를 선언해도 되는가(BC2). 기본은 아니다 --
-- 클라이언트의 --allow-commands 와 이 열이 둘 다 참이어야 하고, 선언한 실행 파일은 서버 상한
-- (device_bridge.command_allowlist) 안이어야 한다. allow_unattended · allow_writes 와 따로다:
-- 무인 런의 명령은 이 열과 상관없이 늘 거절된다(BC6).
-- 080 이 만든 표에 열 하나를 더한다(번호순이 080 뒤를 보장한다). 두 번 적용해도 같다.
ALTER TABLE device_bridges
    ADD COLUMN IF NOT EXISTS allow_commands BOOLEAN NOT NULL DEFAULT FALSE;

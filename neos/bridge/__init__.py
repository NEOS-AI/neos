"""NEOS 기기 브리지 참조 클라이언트 -- 트랙 Q16a (docs/Q16_DEVICE_BRIDGE_DESIGN_261001.md).

사용자가 **자기 기기에서** 돌린다. 명시한 루트 폴더 하나 안에서 READ_ONLY 도구
(`list_dir` · `stat` · `read_file`)만 답한다. 아무것도 실행하지 않는다.

    NEOS_BRIDGE_TOKEN=ndb_... python -m neos.bridge --url wss://host/api/v1/coding/device-bridge/ws --root ~/notes

서버 쪽 짝은 `neos.coding.bridge` 다.
"""

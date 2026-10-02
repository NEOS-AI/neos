"""실제 MCP(Model Context Protocol) 클라이언트 -- 트랙 Q11a.

docs/Q11_MCP_CLIENT_DESIGN_261001.md. 이름에 "MCP" 가 들어간 옛 모듈
(`neos/tools/mcp_integration.py` · `neos/tools/mcp_server_manager.py` ·
`neos/tools/manager/mcp_manager.py` · `neos/fsi/mcp_attach.py`)은 프로토콜을
말하지 않는다(M1). JSON-RPC 로 MCP 서버와 말하는 것은 이 패키지뿐이다.

- `protocol` -- JSON-RPC 2.0 세션과 두 전송(stdio · streamable HTTP)
- `catalog`  -- 운영자 설정 + `tools/list` -> 위험을 **선언한** 도구만 (M4)
- `runner`   -- `tools/call` 한 번: 금고에서 풀고 -> 부르고 -> 가리고 -> 감싼다
"""

from __future__ import annotations

#: 노출 이름의 접두. 내장 도구 이름은 이것으로 시작하지 않는다(M5).
CONNECTOR_TOOL_PREFIX = "mcp__"


def is_connector_tool_name(name: object) -> bool:
    return isinstance(name, str) and name.startswith(CONNECTOR_TOOL_PREFIX)


__all__ = ["CONNECTOR_TOOL_PREFIX", "is_connector_tool_name"]

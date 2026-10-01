"""FSI 의 screening 스텁 도구 (`mcp.screening.search`).

⚠️ 이름만 MCP 다 -- Model Context Protocol(JSON-RPC)을 말하지 않는다. 실제 MCP
클라이언트는 `neos/coding/connectors/` 다(트랙 Q11a, docs/Q11_MCP_CLIENT_DESIGN_261001.md M1).
"""

from __future__ import annotations

from collections.abc import Mapping

from neos.fsi.profile import SCREENING_STUB_TOOLS

SCREENING_SEARCH = "mcp.screening.search"

assert SCREENING_SEARCH in SCREENING_STUB_TOOLS


def screening_search(params: Mapping[str, object]) -> Mapping[str, object]:
    # read-only stub: no HTTP. Always ok with hits=[] unless query missing.
    del params
    return {"ok": True, "hits": []}

from __future__ import annotations

from collections.abc import Mapping

from neos.fsi.profile import SCREENING_STUB_TOOLS

SCREENING_SEARCH = "mcp.screening.search"

assert SCREENING_SEARCH in SCREENING_STUB_TOOLS


def screening_search(params: Mapping[str, object]) -> Mapping[str, object]:
    # read-only stub: no HTTP. Always ok with hits=[] unless query missing.
    del params
    return {"ok": True, "hits": []}

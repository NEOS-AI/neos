from __future__ import annotations

import ast
from pathlib import Path

import pytest

from neos.fsi.mcp_attach import SCREENING_SEARCH, screening_search
from neos.fsi.ports import FsiParentWorkspacePort, FsiSessionPort
from neos.fsi.profile import SCREENING_STUB_TOOLS

pytestmark = pytest.mark.no_db


def test_screening_search_is_read_only_stub() -> None:
    assert SCREENING_SEARCH == "mcp.screening.search"
    assert SCREENING_SEARCH in SCREENING_STUB_TOOLS
    assert screening_search({"query": "Ada Lovelace"}) == {"ok": True, "hits": []}
    assert screening_search({}) == {"ok": True, "hits": []}


def test_mcp_attach_has_no_http_ports_or_partner() -> None:
    path = Path(__file__).resolve().parents[2] / "neos" / "fsi" / "mcp_attach.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            imported.add(node.module)
    assert "httpx" not in imported
    assert "requests" not in imported
    assert "urllib" not in imported
    assert "aiohttp" not in imported
    assert "neos.fsi.ports" not in imported
    assert "neos.tools" not in imported
    assert "mcp_integration" not in source
    assert "whitelist_party" not in source
    assert "mark_cleared" not in source
    assert "lseg" not in source
    assert "sp-global" not in source
    assert "sp_global" not in source


@pytest.mark.asyncio
async def test_session_with_screening_exposes_stub(tmp_path: Path) -> None:
    port = FsiSessionPort(
        tmp_path, write=False, mcp_allowlist=frozenset({"screening"})
    )
    assert SCREENING_SEARCH in port.definitions()
    result = await port.execute(SCREENING_SEARCH, {"query": "Ada Lovelace"})
    assert result == {"ok": True, "hits": []}


@pytest.mark.asyncio
async def test_session_without_screening_denies_stub(tmp_path: Path) -> None:
    port = FsiSessionPort(tmp_path, write=False)
    assert SCREENING_SEARCH not in port.definitions()
    result = await port.execute(SCREENING_SEARCH, {"query": "Ada Lovelace"})
    assert result == {"ok": False, "error": "tool_not_allowed"}


@pytest.mark.asyncio
async def test_other_mcp_allowlist_does_not_attach_screening(
    tmp_path: Path,
) -> None:
    port = FsiSessionPort(
        tmp_path, write=False, mcp_allowlist=frozenset({"capiq", "lseg"})
    )
    assert SCREENING_SEARCH not in port.definitions()
    result = await port.execute(SCREENING_SEARCH, {"query": "Ada Lovelace"})
    assert result == {"ok": False, "error": "tool_not_allowed"}


@pytest.mark.asyncio
async def test_parent_workspace_port_does_not_grow_screening(
    tmp_path: Path,
) -> None:
    reader = FsiParentWorkspacePort(tmp_path, write=False)
    writer = FsiParentWorkspacePort(tmp_path, write=True)
    assert SCREENING_SEARCH not in reader.definitions()
    assert SCREENING_SEARCH not in writer.definitions()
    denied = await reader.execute(SCREENING_SEARCH, {"query": "Ada Lovelace"})
    assert denied == {"ok": False, "error": "tool_not_allowed"}


@pytest.mark.asyncio
async def test_session_skill_allowlist_still_works(tmp_path: Path) -> None:
    port = FsiSessionPort(
        tmp_path,
        write=False,
        skill_allowlist=frozenset({"kyc-doc-parse"}),
        mcp_allowlist=frozenset({"screening"}),
    )
    assert "load_skill.v1" in port.definitions()
    assert SCREENING_SEARCH in port.definitions()
    skill = await port.execute("load_skill.v1", {"name": "kyc-doc-parse"})
    assert skill["ok"] is True
    assert skill["name"] == "kyc-doc-parse"

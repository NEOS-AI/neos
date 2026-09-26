from __future__ import annotations

from pathlib import Path

import pytest

from neos.fsi.ports import FsiSessionPort

pytestmark = pytest.mark.no_db


def _session(
    workspace: Path,
    *,
    write: bool,
    skill_allowlist: frozenset[str] = frozenset(),
) -> FsiSessionPort:
    return FsiSessionPort(
        workspace, write=write, skill_allowlist=skill_allowlist
    )


@pytest.mark.asyncio
async def test_session_load_skill_permitted_kyc_doc_parse(tmp_path: Path) -> None:
    port = _session(
        tmp_path, write=False, skill_allowlist=frozenset({"kyc-doc-parse"})
    )
    assert "load_skill.v1" in port.definitions()
    result = await port.execute("load_skill.v1", {"name": "kyc-doc-parse"})
    assert result["ok"] is True
    assert result["name"] == "kyc-doc-parse"
    assert "Parse the onboarding packet" in result["markdown"]


@pytest.mark.asyncio
async def test_session_load_skill_unknown_outside_allowlist(tmp_path: Path) -> None:
    port = _session(
        tmp_path, write=False, skill_allowlist=frozenset({"kyc-doc-parse"})
    )
    result = await port.execute("load_skill.v1", {"name": "xlsx-author"})
    assert result == {"ok": False, "error": "unknown_skill"}


@pytest.mark.asyncio
async def test_session_load_skill_unknown_name_is_unknown_skill(tmp_path: Path) -> None:
    port = _session(
        tmp_path, write=False, skill_allowlist=frozenset({"kyc-doc-parse"})
    )
    result = await port.execute("load_skill.v1", {"name": "not-a-skill"})
    assert result == {"ok": False, "error": "unknown_skill"}


@pytest.mark.asyncio
async def test_default_session_load_skill_is_tool_not_allowed(tmp_path: Path) -> None:
    port = _session(tmp_path, write=False)
    assert "load_skill.v1" not in port.definitions()
    result = await port.execute("load_skill.v1", {"name": "kyc-doc-parse"})
    assert result == {"ok": False, "error": "tool_not_allowed"}


@pytest.mark.asyncio
async def test_session_approve_onboarding_is_policy_binding_denied(
    tmp_path: Path,
) -> None:
    port = _session(
        tmp_path, write=False, skill_allowlist=frozenset({"kyc-doc-parse"})
    )
    result = await port.execute("approve_onboarding", {})
    assert result["ok"] is False
    assert result["error"] == "policy_binding_denied"
    assert result["action"] == "approve_onboarding"


@pytest.mark.asyncio
async def test_session_writer_jails_to_out_spec_json(tmp_path: Path) -> None:
    port = _session(
        tmp_path, write=True, skill_allowlist=frozenset({"kyc-doc-parse"})
    )
    assert port.definitions() == (
        "read_file.v1",
        "write_file.v1",
        "load_skill.v1",
    )
    payload = '{"packet_id": "PKT-1"}'
    allowed = await port.execute(
        "write_file.v1",
        {"path": "out/_spec/packet.json", "content": payload},
    )
    assert allowed["ok"] is True
    written = tmp_path / "out" / "_spec" / "packet.json"
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == payload
    denied = await port.execute(
        "write_file.v1",
        {"path": "out/packet.json", "content": '{"n": 1}'},
    )
    assert denied == {"ok": False, "error": "path_denied"}
    assert not (tmp_path / "out" / "packet.json").exists()
    xlsx = await port.execute(
        "write_file.v1",
        {"path": "out/_spec/packet.xlsx", "content": "not-a-workbook"},
    )
    assert xlsx == {"ok": False, "error": "xlsx_forbidden"}
    assert not (tmp_path / "out" / "_spec" / "packet.xlsx").exists()

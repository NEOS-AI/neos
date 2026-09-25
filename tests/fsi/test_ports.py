from __future__ import annotations

from pathlib import Path

import pytest

from neos.fsi.ports import FsiParentWorkspacePort

pytestmark = pytest.mark.no_db


def _reader(workspace: Path) -> FsiParentWorkspacePort:
    return FsiParentWorkspacePort(workspace, write=False)


def _writer(workspace: Path) -> FsiParentWorkspacePort:
    return FsiParentWorkspacePort(workspace, write=True)


@pytest.mark.asyncio
async def test_reader_cannot_write(tmp_path: Path) -> None:
    port = _reader(tmp_path)
    assert port.definitions() == ("read_file.v1", "search_text.v1")
    target = tmp_path / "out" / "_spec" / "packet.json"
    result = await port.execute(
        "write_file.v1",
        {"path": "out/_spec/packet.json", "content": '{"ok": true}'},
    )
    assert result == {"ok": False, "error": "tool_not_allowed"}
    assert not target.exists()


@pytest.mark.asyncio
async def test_writer_json_under_out_spec(tmp_path: Path) -> None:
    port = _writer(tmp_path)
    assert port.definitions() == ("read_file.v1", "write_file.v1")
    payload = '{"packet_id": "PKT-1"}'
    result = await port.execute(
        "write_file.v1",
        {"path": "out/_spec/packet.json", "content": payload},
    )
    assert result["ok"] is True
    written = tmp_path / "out" / "_spec" / "packet.json"
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == payload
    read_back = await port.execute("read_file.v1", {"path": "out/_spec/packet.json"})
    assert read_back["ok"] is True
    assert read_back["content"] == payload


@pytest.mark.asyncio
async def test_writer_xlsx_is_denied(tmp_path: Path) -> None:
    port = _writer(tmp_path)
    for path in (
        "out/escalation-PKT.xlsx",
        "out/_spec/packet.xlsx",
        "./out/model.xlsx",
    ):
        result = await port.execute(
            "write_file.v1",
            {"path": path, "content": "not-a-workbook"},
        )
        assert result == {"ok": False, "error": "xlsx_forbidden"}
    assert not (tmp_path / "out" / "escalation-PKT.xlsx").exists()
    assert not (tmp_path / "out" / "_spec" / "packet.xlsx").exists()
    assert not (tmp_path / "out" / "model.xlsx").exists()


@pytest.mark.asyncio
async def test_path_escape_is_denied(tmp_path: Path) -> None:
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("classified", encoding="utf-8")
    (tmp_path / "inside.txt").write_text("ok", encoding="utf-8")
    writer = _writer(tmp_path)
    reader = _reader(tmp_path)
    escaped_read = await reader.execute("read_file.v1", {"path": "../secret.txt"})
    assert escaped_read == {"ok": False, "error": "path_denied"}
    escaped_write = await writer.execute(
        "write_file.v1",
        {"path": "../secret.txt", "content": "pwned"},
    )
    assert escaped_write == {"ok": False, "error": "path_denied"}
    assert outside.read_text(encoding="utf-8") == "classified"
    missing = await reader.execute("read_file.v1", {"path": "no-such-file.txt"})
    assert missing == {"ok": False, "error": "not_found"}


@pytest.mark.asyncio
async def test_writer_json_outside_out_spec_is_denied(tmp_path: Path) -> None:
    port = _writer(tmp_path)
    for path in (
        "out/packet.json",
        "notes.json",
        "out/_spec/../leak.json",
        "./workspace.json",
    ):
        result = await port.execute(
            "write_file.v1",
            {"path": path, "content": '{"n": 1}'},
        )
        assert result == {"ok": False, "error": "path_denied"}
    assert not (tmp_path / "out" / "packet.json").exists()
    assert not (tmp_path / "notes.json").exists()
    assert not (tmp_path / "leak.json").exists()
    assert not (tmp_path / "workspace.json").exists()

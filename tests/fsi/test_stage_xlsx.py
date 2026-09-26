from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from neos.fsi.ports import FsiParentWorkspacePort, FsiSessionPort
from neos.fsi.safety import SUCCESS_ARTIFACT_STATUS
from neos.fsi.stage_xlsx import stage_xlsx

pytestmark = pytest.mark.no_db

_ROWS = (("packet_id", "PKT-1"), ("disposition", "escalate"))
_OK_PATH = "out/escalation-PKT.xlsx"


def _reader(workspace: Path) -> FsiParentWorkspacePort:
    return FsiParentWorkspacePort(workspace, write=False)


def _writer(workspace: Path) -> FsiParentWorkspacePort:
    return FsiParentWorkspacePort(workspace, write=True)


def test_stage_xlsx_writes_out_xlsx(tmp_path: Path) -> None:
    result = stage_xlsx(tmp_path, path=_OK_PATH, rows=_ROWS)
    written = tmp_path / "out" / "escalation-PKT.xlsx"
    assert result == {
        "ok": True,
        "path": _OK_PATH,
        "status": SUCCESS_ARTIFACT_STATUS,
    }
    assert result["status"] == "staged_for_signoff"
    assert written.is_file()
    sheet = openpyxl.load_workbook(written).active
    assert [cell.value for cell in next(sheet.iter_rows())] == ["packet_id", "PKT-1"]


@pytest.mark.parametrize(
    "path",
    (
        "../secret.xlsx",
        "out/_spec/packet.xlsx",
        "draft/book.xlsx",
        "out/foo/bar.xlsx",
    ),
)
def test_stage_xlsx_denies_escaped_and_nested_paths(
    tmp_path: Path, path: str
) -> None:
    result = stage_xlsx(tmp_path, path=path, rows=_ROWS)
    assert result == {"ok": False, "error": "path_denied"}
    assert not (tmp_path / "out" / "escalation-PKT.xlsx").exists()
    assert list(tmp_path.rglob("*.xlsx")) == []


@pytest.mark.asyncio
async def test_reader_definitions_include_glob_and_stage_xlsx(
    tmp_path: Path,
) -> None:
    port = _reader(tmp_path)
    assert port.definitions() == (
        "read_file.v1",
        "search_text.v1",
        "glob_files.v1",
        "stage_xlsx.v1",
    )
    result = await port.execute(
        "stage_xlsx.v1",
        {"path": _OK_PATH, "rows": [list(row) for row in _ROWS]},
    )
    assert result == {
        "ok": True,
        "path": _OK_PATH,
        "status": "staged_for_signoff",
    }
    assert (tmp_path / "out" / "escalation-PKT.xlsx").is_file()


@pytest.mark.asyncio
async def test_writer_stage_xlsx_is_tool_not_allowed(tmp_path: Path) -> None:
    port = _writer(tmp_path)
    assert "stage_xlsx.v1" not in port.definitions()
    assert "glob_files.v1" not in port.definitions()
    result = await port.execute(
        "stage_xlsx.v1",
        {"path": _OK_PATH, "rows": [list(row) for row in _ROWS]},
    )
    assert result == {"ok": False, "error": "tool_not_allowed"}
    assert not (tmp_path / "out" / "escalation-PKT.xlsx").exists()


@pytest.mark.asyncio
async def test_writer_glob_is_tool_not_allowed(tmp_path: Path) -> None:
    port = _writer(tmp_path)
    result = await port.execute("glob_files.v1", {"pattern": "**/*"})
    assert result == {"ok": False, "error": "tool_not_allowed"}


@pytest.mark.asyncio
async def test_reader_glob_star_is_one_path_segment(tmp_path: Path) -> None:
    out = tmp_path / "out"
    nested = out / "nested"
    nested.mkdir(parents=True)
    (out / "escalation-PKT.xlsx").write_bytes(b"xlsx")
    (nested / "foo.xlsx").write_bytes(b"xlsx")
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "book.xlsx").write_bytes(b"xlsx")
    port = _reader(tmp_path)
    result = await port.execute("glob_files.v1", {"pattern": "out/*.xlsx"})
    assert result["ok"] is True
    assert {"path": "out/escalation-PKT.xlsx"} in result["matches"]
    assert {"path": "out/nested/foo.xlsx"} not in result["matches"]
    assert {"path": "draft/book.xlsx"} not in result["matches"]


@pytest.mark.asyncio
async def test_session_write_false_inherits_glob_and_stage(
    tmp_path: Path,
) -> None:
    port = FsiSessionPort(tmp_path, write=False)
    assert port.definitions() == (
        "read_file.v1",
        "search_text.v1",
        "glob_files.v1",
        "stage_xlsx.v1",
    )
    result = await port.execute(
        "stage_xlsx.v1",
        {"path": _OK_PATH, "rows": [list(row) for row in _ROWS]},
    )
    assert result["ok"] is True
    assert result["path"] == _OK_PATH
    assert result["status"] == SUCCESS_ARTIFACT_STATUS


@pytest.mark.asyncio
async def test_session_writer_omits_stage_xlsx(tmp_path: Path) -> None:
    port = FsiSessionPort(tmp_path, write=True)
    assert "stage_xlsx.v1" not in port.definitions()
    result = await port.execute(
        "stage_xlsx.v1",
        {"path": _OK_PATH, "rows": [list(row) for row in _ROWS]},
    )
    assert result == {"ok": False, "error": "tool_not_allowed"}

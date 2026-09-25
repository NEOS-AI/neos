from __future__ import annotations

import json
from pathlib import Path

import pytest

from neos.univer.ports import UniverToolPort
from neos.univer.sidecar import InMemorySidecar, SidecarClient

pytestmark = pytest.mark.no_db

_SIDECAR_TOOLS = (
    "univer.inspect.v1",
    "univer.range_get.v1",
    "univer.range_set.v1",
    "univer.execute_command.v1",
    "univer.formula_wait.v1",
    "univer.save.v1",
)


def _names(port: UniverToolPort) -> tuple[str, ...]:
    names: list[str] = []
    for item in port.definitions():
        names.append(item if isinstance(item, str) else item.name)
    return tuple(names)


def _port(tmp_path: Path, **kwargs: object) -> UniverToolPort:
    sidecar = InMemorySidecar(session_dir=tmp_path, **kwargs)
    return UniverToolPort(sidecar)


@pytest.mark.asyncio
async def test_definitions_stay_six_names(tmp_path: Path) -> None:
    port = _port(tmp_path)
    assert _names(port) == _SIDECAR_TOOLS


@pytest.mark.asyncio
async def test_empty_sheet_outline_is_1000_by_20(tmp_path: Path) -> None:
    port = _port(tmp_path)
    result = await port.execute("univer.inspect.v1", {})
    assert result["ok"] is True
    sheets = result["outline"]["sheets"]
    assert len(sheets) == 1
    sheet = sheets[0]
    assert sheet["row_count"] == 1000
    assert sheet["column_count"] == 20
    assert sheet["row_height"] == 24
    assert sheet["column_width"] == 88


@pytest.mark.asyncio
async def test_formula_dirty_before_wait(tmp_path: Path) -> None:
    port = _port(tmp_path)
    set_a1 = await port.execute(
        "univer.range_set.v1",
        {"a1": "A1", "value": 1},
    )
    assert set_a1["ok"] is True
    set_b1 = await port.execute(
        "univer.range_set.v1",
        {"a1": "B1", "formula": "=A1+1"},
    )
    assert set_b1["ok"] is True
    inspect = await port.execute(
        "univer.inspect.v1",
        {"include_values": True},
    )
    assert inspect == {"ok": False, "error": "formula_dirty"}
    save = await port.execute("univer.save.v1", {})
    assert save == {"ok": False, "error": "formula_dirty"}


@pytest.mark.asyncio
async def test_wait_then_save_computed_v(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute("univer.range_set.v1", {"a1": "A1", "value": 1})
    await port.execute("univer.range_set.v1", {"a1": "B1", "formula": "=A1+1"})
    waited = await port.execute("univer.formula_wait.v1", {})
    assert waited == {"ok": True, "formula_dirty": False}
    saved = await port.execute("univer.save.v1", {})
    assert saved["ok"] is True
    assert saved["path"] == "draft/workbook.json"
    assert saved["bytes"] > 0
    path = tmp_path / "draft" / "workbook.json"
    assert path.is_file()
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    b1 = snapshot["sheets"]["sheet-01"]["cellData"]["0"]["1"]
    assert b1["v"] == 2
    assert b1["t"] == 2
    assert b1["f"] == "=A1+1"
    got = await port.execute("univer.range_get.v1", {"a1": "B1"})
    assert got["ok"] is True
    assert got["cells"][0]["v"] == 2


@pytest.mark.asyncio
async def test_set_range_values_command_updates_cells(tmp_path: Path) -> None:
    port = _port(tmp_path)
    result = await port.execute(
        "univer.execute_command.v1",
        {
            "id": "sheet.command.set-range-values",
            "params": {
                "range": {
                    "startRow": 0,
                    "startColumn": 0,
                    "endRow": 0,
                    "endColumn": 0,
                },
                "value": {"v": 9, "t": 2},
            },
        },
    )
    assert result["ok"] is True
    got = await port.execute("univer.range_get.v1", {"a1": "A1"})
    assert got["ok"] is True
    assert got["cells"][0]["v"] == 9


@pytest.mark.asyncio
async def test_command_not_allowlisted(tmp_path: Path) -> None:
    port = _port(tmp_path)
    result = await port.execute(
        "univer.execute_command.v1",
        {"id": "sheet.command.remove-sheet"},
    )
    assert result == {"ok": False, "error": "command_not_allowlisted"}


@pytest.mark.asyncio
async def test_mutation_forbidden(tmp_path: Path) -> None:
    port = _port(tmp_path)
    result = await port.execute(
        "univer.execute_command.v1",
        {"id": "sheet.mutation.set-range-values"},
    )
    assert result == {"ok": False, "error": "mutation_forbidden"}
    assert "MUTATION" not in json.dumps(result)


@pytest.mark.asyncio
async def test_insert_row_shifts_cells(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute("univer.range_set.v1", {"a1": "A1", "value": 1})
    result = await port.execute(
        "univer.execute_command.v1",
        {"id": "sheet.command.insert-row", "params": {"startRow": 0, "count": 1}},
    )
    assert result["ok"] is True
    a1 = await port.execute("univer.range_get.v1", {"a1": "A1"})
    a2 = await port.execute("univer.range_get.v1", {"a1": "A2"})
    assert a1.get("cells") == [] or a1["cells"][0].get("v") in (None, [])
    assert a2["cells"][0]["v"] == 1
    outline = await port.execute("univer.inspect.v1", {})
    assert outline["outline"]["sheets"][0]["row_count"] == 1001


@pytest.mark.asyncio
async def test_remove_row_shifts_cells_up(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute("univer.range_set.v1", {"a1": "A1", "value": 1})
    await port.execute("univer.range_set.v1", {"a1": "A2", "value": 2})
    result = await port.execute(
        "univer.execute_command.v1",
        {"id": "sheet.command.remove-row", "params": {"startRow": 0, "count": 1}},
    )
    assert result["ok"] is True
    a1 = await port.execute("univer.range_get.v1", {"a1": "A1"})
    a2 = await port.execute("univer.range_get.v1", {"a1": "A2"})
    assert a1["cells"][0]["v"] == 2
    assert a2.get("cells") == [] or a2["cells"][0].get("v") in (None, [])
    outline = await port.execute("univer.inspect.v1", {})
    assert outline["outline"]["sheets"][0]["row_count"] == 999


@pytest.mark.asyncio
async def test_insert_col_shifts_cells(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute("univer.range_set.v1", {"a1": "A1", "value": 1})
    result = await port.execute(
        "univer.execute_command.v1",
        {
            "id": "sheet.command.insert-col",
            "params": {"startColumn": 0, "count": 1},
        },
    )
    assert result["ok"] is True
    a1 = await port.execute("univer.range_get.v1", {"a1": "A1"})
    b1 = await port.execute("univer.range_get.v1", {"a1": "B1"})
    assert a1.get("cells") == [] or a1["cells"][0].get("v") in (None, [])
    assert b1["cells"][0]["v"] == 1
    outline = await port.execute("univer.inspect.v1", {})
    assert outline["outline"]["sheets"][0]["column_count"] == 21


@pytest.mark.asyncio
async def test_remove_col_floor_is_one(tmp_path: Path) -> None:
    port = _port(tmp_path)
    result = await port.execute(
        "univer.execute_command.v1",
        {
            "id": "sheet.command.remove-col",
            "params": {"startColumn": 0, "count": 100},
        },
    )
    assert result["ok"] is True
    outline = await port.execute("univer.inspect.v1", {})
    assert outline["outline"]["sheets"][0]["column_count"] == 1


@pytest.mark.asyncio
async def test_add_merge_lands_in_snapshot(tmp_path: Path) -> None:
    port = _port(tmp_path)
    result = await port.execute(
        "univer.execute_command.v1",
        {
            "id": "sheet.command.add-worksheet-merge",
            "params": {
                "startRow": 0,
                "startColumn": 0,
                "endRow": 1,
                "endColumn": 1,
            },
        },
    )
    assert result["ok"] is True
    await port.execute("univer.save.v1", {})
    snapshot = json.loads((tmp_path / "draft" / "workbook.json").read_text(encoding="utf-8"))
    merge = snapshot["sheets"]["sheet-01"]["mergeData"]
    assert {
        "startRow": 0,
        "startColumn": 0,
        "endRow": 1,
        "endColumn": 1,
    } in merge


@pytest.mark.asyncio
async def test_sort_range_numeric_then_string(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute("univer.range_set.v1", {"a1": "A1", "value": "b"})
    await port.execute("univer.range_set.v1", {"a1": "B1", "value": 9})
    await port.execute("univer.range_set.v1", {"a1": "A2", "value": 10})
    await port.execute("univer.range_set.v1", {"a1": "B2", "value": 8})
    await port.execute("univer.range_set.v1", {"a1": "A3", "value": 2})
    await port.execute("univer.range_set.v1", {"a1": "B3", "value": 7})
    result = await port.execute(
        "univer.execute_command.v1",
        {"id": "sheet.command.sort-range", "params": {"range": "A1:B3"}},
    )
    assert result["ok"] is True
    a1 = await port.execute("univer.range_get.v1", {"a1": "A1"})
    a2 = await port.execute("univer.range_get.v1", {"a1": "A2"})
    a3 = await port.execute("univer.range_get.v1", {"a1": "A3"})
    b1 = await port.execute("univer.range_get.v1", {"a1": "B1"})
    assert a1["cells"][0]["v"] == 2
    assert a2["cells"][0]["v"] == 10
    assert a3["cells"][0]["v"] == "b"
    assert b1["cells"][0]["v"] == 7


@pytest.mark.asyncio
async def test_add_validation_lands_in_resources(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute(
        "univer.execute_command.v1",
        {"id": "sheet.command.addDataValidation", "params": {"ranges": ["A1"]}},
    )
    await port.execute("univer.save.v1", {})
    snapshot = json.loads((tmp_path / "draft" / "workbook.json").read_text(encoding="utf-8"))
    names = [item["name"] for item in snapshot["resources"]]
    assert "SHEET_DATA_VALIDATION_PLUGIN" in names
    item = next(
        entry
        for entry in snapshot["resources"]
        if entry["name"] == "SHEET_DATA_VALIDATION_PLUGIN"
    )
    assert item["data"] == json.dumps({"ranges": ["A1"]})


@pytest.mark.asyncio
async def test_conditional_and_table_plugin_names(tmp_path: Path) -> None:
    port = _port(tmp_path)
    cf = await port.execute(
        "univer.execute_command.v1",
        {
            "id": "sheet.command.add-conditional-rule",
            "params": {"range": "A1", "type": "colorScale"},
        },
    )
    table = await port.execute(
        "univer.execute_command.v1",
        {
            "id": "sheet.command.add-table",
            "params": {"name": "T1", "range": "A1:B2"},
        },
    )
    assert cf["ok"] is True
    assert table["ok"] is True
    await port.execute("univer.save.v1", {})
    snapshot = json.loads((tmp_path / "draft" / "workbook.json").read_text(encoding="utf-8"))
    by_name = {item["name"]: item["data"] for item in snapshot["resources"]}
    assert "SHEET_CONDITIONAL_FORMATTING_PLUGIN" in by_name
    assert "SHEET_TABLE_PLUGIN" in by_name
    assert by_name["SHEET_CONDITIONAL_FORMATTING_PLUGIN"] == json.dumps(
        {"range": "A1", "type": "colorScale"}
    )
    assert by_name["SHEET_TABLE_PLUGIN"] == json.dumps(
        {"name": "T1", "range": "A1:B2"}
    )


@pytest.mark.asyncio
async def test_save_outside_draft_is_path_denied(tmp_path: Path) -> None:
    port = _port(tmp_path)
    trunk = await port.execute("univer.save.v1", {"path": "trunk/workbook.json"})
    assert trunk == {"ok": False, "error": "path_denied"}
    nested = await port.execute(
        "univer.save.v1",
        {"path": "draft/nested/workbook.json"},
    )
    assert nested == {"ok": False, "error": "path_denied"}
    abs_path = await port.execute(
        "univer.save.v1",
        {"path": "/tmp/workbook.json"},
    )
    assert abs_path == {"ok": False, "error": "path_denied"}
    assert not (tmp_path / "trunk" / "workbook.json").exists()


@pytest.mark.asyncio
async def test_save_does_not_follow_symlink_into_trunk(tmp_path: Path) -> None:
    draft = tmp_path / "draft"
    trunk = tmp_path / "trunk"
    draft.mkdir()
    trunk.mkdir()
    planted = trunk / "workbook.json"
    planted.write_text("keep", encoding="utf-8")
    (draft / "workbook.json").symlink_to(planted)
    port = _port(tmp_path)
    result = await port.execute("univer.save.v1", {})
    assert result == {"ok": False, "error": "path_denied"}
    assert planted.read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_save_does_not_follow_symlink_outside_session(tmp_path: Path) -> None:
    draft = tmp_path / "draft"
    draft.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside-workbook.json"
    outside.write_text("keep-out", encoding="utf-8")
    (draft / "workbook.json").symlink_to(outside)
    try:
        port = _port(tmp_path)
        result = await port.execute("univer.save.v1", {})
        assert result == {"ok": False, "error": "path_denied"}
        assert outside.read_text(encoding="utf-8") == "keep-out"
    finally:
        outside.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_save_does_not_follow_doc_symlink_into_trunk(tmp_path: Path) -> None:
    draft = tmp_path / "draft"
    trunk = tmp_path / "trunk"
    draft.mkdir()
    trunk.mkdir()
    planted = trunk / "document.json"
    planted.write_text("keep", encoding="utf-8")
    (draft / "document.json").symlink_to(planted)
    port = _port(tmp_path, kind="doc")
    result = await port.execute("univer.save.v1", {})
    assert result == {"ok": False, "error": "path_denied"}
    assert planted.read_text(encoding="utf-8") == "keep"


@pytest.mark.asyncio
async def test_formula_timeout(tmp_path: Path) -> None:
    port = _port(tmp_path, formula_timeout=True)
    await port.execute("univer.range_set.v1", {"a1": "A1", "formula": "=1+1"})
    result = await port.execute(
        "univer.formula_wait.v1",
        {"timeout_ms": 1},
    )
    assert result == {"ok": False, "error": "formula_timeout"}


@pytest.mark.asyncio
async def test_inspect_too_large_has_no_partial(tmp_path: Path) -> None:
    port = _port(tmp_path)
    result = await port.execute(
        "univer.inspect.v1",
        {"include_values": True, "range": "A1:T21"},
    )
    assert result == {"ok": False, "error": "inspect_too_large"}
    assert "outline" not in result
    assert "cells" not in result


@pytest.mark.asyncio
async def test_stub_sidecar_still_node_missing() -> None:
    port = UniverToolPort(SidecarClient(node=None))
    result = await port.execute("univer.inspect.v1", {})
    assert result == {"ok": False, "error": "node_missing"}


@pytest.mark.asyncio
async def test_execute_never_raises(tmp_path: Path) -> None:
    port = _port(tmp_path)
    result = await port.execute("univer.save.v1", {"path": object()})  # type: ignore[dict-item]
    assert result["ok"] is False
    assert "error" in result


def test_health_reports_steady_empty_sheet(tmp_path: Path) -> None:
    sidecar = InMemorySidecar(session_dir=tmp_path)
    result = sidecar.call("health", {})
    assert result["ok"] is True
    assert result["pid"] == 0
    assert result["kind"] == "sheet"
    assert result["lifecycle"] == "Steady"
    assert result["unit_id"] == "workbook-01"
    assert result["formula_dirty"] is False
    assert result["in_flight"] is False
    assert result["app_version"] == "1.0.2"


def test_load_invalid_json_is_snapshot_invalid(tmp_path: Path) -> None:
    (tmp_path / "draft").mkdir()
    (tmp_path / "draft" / "workbook.json").write_text("{", encoding="utf-8")
    sidecar = InMemorySidecar(session_dir=tmp_path)
    result = sidecar.call("load", {"path": "draft/workbook.json"})
    assert result == {"ok": False, "error": "snapshot_invalid"}


def test_create_second_unit_is_one_unit_limit(tmp_path: Path) -> None:
    sidecar = InMemorySidecar(session_dir=tmp_path)
    first = sidecar.call("create", {})
    # Ruling: implicit boot counts as the one unit.
    assert first == {"ok": False, "error": "one_unit_limit"}


def test_in_flight_call_is_unit_busy(tmp_path: Path) -> None:
    sidecar = InMemorySidecar(session_dir=tmp_path)
    sidecar._in_flight = True
    result = sidecar.call("inspect", {})
    assert result == {"ok": False, "error": "unit_busy"}


def test_dispose_then_create_allows_one_unit(tmp_path: Path) -> None:
    sidecar = InMemorySidecar(session_dir=tmp_path)
    sidecar.call("range_set", {"a1": "A1", "value": 9})
    disposed = sidecar.call("dispose", {})
    assert disposed["ok"] is True
    empty = sidecar.call("range_get", {"a1": "A1"})
    assert empty["ok"] is True
    assert empty["cells"] == []
    created = sidecar.call("create", {})
    assert created["ok"] is True
    second = sidecar.call("create", {})
    assert second == {"ok": False, "error": "one_unit_limit"}


def test_load_missing_file_keeps_empty_unit(tmp_path: Path) -> None:
    sidecar = InMemorySidecar(session_dir=tmp_path)
    sidecar.call("range_set", {"a1": "A1", "value": 9})
    result = sidecar.call("load", {"path": "draft/workbook.json"})
    assert result["ok"] is True
    got = sidecar.call("range_get", {"a1": "A1"})
    assert got["ok"] is True
    assert got["cells"] == []
    outline = sidecar.call("inspect", {})
    assert outline["outline"]["sheets"][0]["row_count"] == 1000
    assert outline["outline"]["sheets"][0]["column_count"] == 20


def test_load_outside_session_is_path_denied(tmp_path: Path) -> None:
    sidecar = InMemorySidecar(session_dir=tmp_path)
    parent = sidecar.call("load", {"path": "../workbook.json"})
    assert parent == {"ok": False, "error": "path_denied"}
    absolute = sidecar.call("load", {"path": "/tmp/workbook.json"})
    assert absolute == {"ok": False, "error": "path_denied"}


def test_load_replaces_existing_unit(tmp_path: Path) -> None:
    sidecar = InMemorySidecar(session_dir=tmp_path)
    sidecar.call("range_set", {"a1": "A1", "value": 1})
    sidecar.call("range_set", {"a1": "B1", "formula": "=A1+1"})
    sidecar.call("formula_wait", {})
    saved = sidecar.call("save", {})
    assert saved["ok"] is True
    sidecar.call("range_set", {"a1": "A1", "value": 99})
    loaded = sidecar.call("load", {"path": "draft/workbook.json"})
    assert loaded["ok"] is True
    got = sidecar.call("range_get", {"a1": "B1"})
    assert got["ok"] is True
    assert got["cells"][0]["v"] == 2
    a1 = sidecar.call("range_get", {"a1": "A1"})
    assert a1["cells"][0]["v"] == 1


@pytest.mark.asyncio
async def test_inspect_formula_errors_after_wait(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute("univer.range_set.v1", {"a1": "A1", "value": 0})
    await port.execute("univer.range_set.v1", {"a1": "B1", "formula": "=1/A1"})
    await port.execute("univer.formula_wait.v1", {})
    inspect = await port.execute("univer.inspect.v1", {"include_values": True})
    assert inspect["ok"] is True
    codes = {item["code"] for item in inspect["formula_errors"]}
    assert "#DIV/0!" in codes
    assert any(item["a1"] == "B1" for item in inspect["formula_errors"])


@pytest.mark.asyncio
async def test_inspect_unknown_formula_is_name_error(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute("univer.range_set.v1", {"a1": "A1", "formula": "=FOO()"})
    await port.execute("univer.formula_wait.v1", {})
    inspect = await port.execute("univer.inspect.v1", {"include_values": True})
    assert inspect["ok"] is True
    assert any(
        item["code"] == "#NAME?" and item["a1"] == "A1"
        for item in inspect["formula_errors"]
    )
    got = await port.execute("univer.range_get.v1", {"a1": "A1"})
    assert got["ok"] is True
    assert got["cells"][0]["v"] == "#NAME?"


@pytest.mark.asyncio
async def test_sum_range_and_if_after_wait(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute("univer.range_set.v1", {"a1": "A1", "value": 1})
    await port.execute("univer.range_set.v1", {"a1": "A2", "value": 2})
    await port.execute("univer.range_set.v1", {"a1": "B1", "formula": "=SUM(A1:A2)"})
    await port.execute("univer.range_set.v1", {"a1": "C1", "formula": "=IF(A1>0,1,0)"})
    await port.execute("univer.formula_wait.v1", {})
    b1 = await port.execute("univer.range_get.v1", {"a1": "B1"})
    c1 = await port.execute("univer.range_get.v1", {"a1": "C1"})
    assert b1["cells"][0]["v"] == 3
    assert c1["cells"][0]["v"] == 1
    await port.execute("univer.range_set.v1", {"a1": "D1", "formula": "=FOO()"})
    await port.execute("univer.formula_wait.v1", {})
    inspect = await port.execute("univer.inspect.v1", {"include_values": True})
    assert any(item["code"] == "#NAME?" and item["a1"] == "D1" for item in inspect["formula_errors"])


@pytest.mark.asyncio
async def test_sum_empty_range_is_zero(tmp_path: Path) -> None:
    port = _port(tmp_path)
    await port.execute("univer.range_set.v1", {"a1": "B1", "formula": "=SUM(Z1:Z2)"})
    await port.execute("univer.formula_wait.v1", {})
    got = await port.execute("univer.range_get.v1", {"a1": "B1"})
    assert got["ok"] is True
    assert got["cells"][0]["v"] == 0


@pytest.mark.asyncio
async def test_doc_empty_inspect_is_crlf_paragraph(tmp_path: Path) -> None:
    port = UniverToolPort(InMemorySidecar(session_dir=tmp_path, kind="doc"))
    inspect = await port.execute("univer.inspect.v1", {})
    assert inspect["ok"] is True
    assert inspect["outline"]["data_stream_length"] == 2
    assert inspect["outline"]["paragraph_count"] == 1
    assert inspect["paragraphs"][0]["text"] == ""
    assert inspect["paragraphs"][0]["length"] == 0


@pytest.mark.asyncio
async def test_doc_insert_text_round_trip(tmp_path: Path) -> None:
    port = UniverToolPort(InMemorySidecar(session_dir=tmp_path, kind="doc"))
    inserted = await port.execute(
        "univer.execute_command.v1",
        {"id": "doc.command.insert-text", "params": {"text": "Hello"}},
    )
    assert inserted["ok"] is True
    inspect = await port.execute("univer.inspect.v1", {})
    assert inspect["ok"] is True
    assert inspect["paragraphs"][0]["text"] == "Hello"
    saved = await port.execute("univer.save.v1", {})
    assert saved["ok"] is True
    snapshot = json.loads((tmp_path / "draft" / "document.json").read_text(encoding="utf-8"))
    assert "Hello" in snapshot["body"]["dataStream"]


@pytest.mark.asyncio
async def test_doc_update_text_replaces_paragraph(tmp_path: Path) -> None:
    port = UniverToolPort(InMemorySidecar(session_dir=tmp_path, kind="doc"))
    await port.execute(
        "univer.execute_command.v1",
        {"id": "doc.command.insert-text", "params": {"text": "Hello"}},
    )
    updated = await port.execute(
        "univer.execute_command.v1",
        {"id": "doc.command.update-text", "params": {"text": "Hi"}},
    )
    assert updated["ok"] is True
    inspect = await port.execute("univer.inspect.v1", {})
    assert inspect["ok"] is True
    assert inspect["paragraphs"][0]["text"] == "Hi"
    assert inspect["outline"]["data_stream_length"] == 4
    saved = await port.execute("univer.save.v1", {})
    assert saved["ok"] is True
    snapshot = json.loads((tmp_path / "draft" / "document.json").read_text(encoding="utf-8"))
    assert snapshot["body"]["dataStream"] == "Hi\r\n"
    assert "Hello" not in snapshot["body"]["dataStream"]

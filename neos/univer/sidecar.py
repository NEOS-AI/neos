from __future__ import annotations

import ast
import json
import operator
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from neos.univer.allowlist import COMMAND_ALLOWLIST, mutation_id

_CELL_REF = re.compile(r"\$?([A-Za-z]+)\$?([0-9]+)")
_A1_RANGE = re.compile(
    r"^\$?([A-Za-z]+)\$?([0-9]+)(?::\$?([A-Za-z]+)\$?([0-9]+))?$"
)
_INSPECT_CELL_LIMIT = 400
_SAVE_SHEET = "draft/workbook.json"
_SAVE_DOC = "draft/document.json"
_EMPTY_ROW_COUNT = 1000
_EMPTY_COLUMN_COUNT = 20
_EMPTY_ROW_HEIGHT = 24
_EMPTY_COLUMN_WIDTH = 88
_APP_VERSION = "1.0.2"
_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_ERROR_TYPES = frozenset(
    {
        "#DIV/0!",
        "#NAME?",
        "#VALUE!",
        "#NUM!",
        "#N/A",
        "#CYCLE!",
        "#REF!",
        "#SPILL!",
        "#CALC!",
        "#ERROR!",
        "#GETTING_DATA",
        "#NULL!",
    }
)


def node_binary() -> Path | None:
    found = shutil.which("node")
    return Path(found) if found else None


class SidecarClient:
    def __init__(self, *, node: Path | None = None) -> None:
        self._node = node

    @property
    def node(self) -> Path | None:
        return self._node

    def unavailable_error(self) -> str:
        if self._node is None:
            return "node_missing"
        return "sidecar_unavailable"


class InMemorySidecar:
    def __init__(
        self,
        *,
        session_dir: Path,
        kind: str = "sheet",
        formula_timeout: bool = False,
    ) -> None:
        if kind not in {"sheet", "doc"}:
            raise ValueError("kind must be sheet or doc")
        self._session_dir = session_dir
        self._kind = kind
        self._formula_timeout = formula_timeout
        self._dirty = False
        self._cells: dict[tuple[int, int], dict[str, Any]] = {}
        self._sheet_id = "sheet-01"
        self._sheet_name = "Sheet1"
        self._unit_id = "workbook-01" if kind == "sheet" else "document-01"
        self._unit_name = "Workbook" if kind == "sheet" else "Document1"
        self._row_count = _EMPTY_ROW_COUNT
        self._column_count = _EMPTY_COLUMN_COUNT
        self._in_flight = False
        self._created = True

    def unavailable_error(self) -> str:
        return "sidecar_unavailable"

    def call(self, method: str, params: Mapping[str, object]) -> Mapping[str, Any]:
        if self._in_flight:
            return {"ok": False, "error": "unit_busy"}
        handler = getattr(self, method, None)
        if not callable(handler) or method.startswith("_"):
            return {"ok": False, "error": "tool_not_allowed"}
        self._in_flight = True
        try:
            return handler(params)
        finally:
            self._in_flight = False

    def health(self, params: Mapping[str, object]) -> Mapping[str, Any]:
        return {
            "ok": True,
            "pid": 0,
            "kind": self._kind,
            "lifecycle": "Steady",
            "unit_id": self._unit_id,
            "formula_dirty": self._dirty,
            "in_flight": False,
            "app_version": _APP_VERSION,
        }

    def create(self, params: Mapping[str, object]) -> Mapping[str, Any]:
        if self._created:
            return {"ok": False, "error": "one_unit_limit"}
        self._reset_empty_unit()
        self._created = True
        return {"ok": True, "unit_id": self._unit_id}

    def dispose(self, params: Mapping[str, object]) -> Mapping[str, Any]:
        self._reset_empty_unit()
        self._created = False
        return {"ok": True}

    def load(self, params: Mapping[str, object]) -> Mapping[str, Any]:
        raw = params.get("path")
        resolved = _confine(self._session_dir, raw)
        if resolved is None:
            return {"ok": False, "error": "path_denied"}
        if not resolved.is_file():
            self._reset_empty_unit()
            self._created = True
            return {"ok": True, "unit_id": self._unit_id}
        try:
            text = resolved.read_text(encoding="utf-8")
            snapshot = json.loads(text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return {"ok": False, "error": "snapshot_invalid"}
        if not isinstance(snapshot, dict):
            return {"ok": False, "error": "snapshot_invalid"}
        applied = self._apply_snapshot(snapshot)
        if applied is not None:
            return applied
        self._created = True
        return {"ok": True, "unit_id": self._unit_id}

    def inspect(self, params: Mapping[str, object]) -> Mapping[str, Any]:
        if self._kind == "doc":
            return self._inspect_doc(params)
        sheet = params.get("sheet")
        if sheet is not None and sheet not in {self._sheet_id, self._sheet_name}:
            return {"ok": False, "error": "not_found"}
        include_values = bool(params.get("include_values", False))
        if include_values and self._dirty:
            return {"ok": False, "error": "formula_dirty"}
        outline = self._sheet_outline()
        payload: dict[str, Any] = {
            "ok": True,
            "unit": self._unit_payload(),
            "outline": outline,
        }
        if params.get("include_formula_errors", True):
            payload["formula_errors"] = self._formula_errors()
        if not include_values:
            return payload
        parsed = _parse_range(params.get("range"))
        if parsed is None and params.get("range") is not None:
            return {"ok": False, "error": "not_found"}
        if parsed is None:
            cells = [self._cell_payload(r, c) for (r, c) in sorted(self._cells)]
            if len(cells) > _INSPECT_CELL_LIMIT:
                return {"ok": False, "error": "inspect_too_large"}
            if cells:
                payload["range"] = self._range_payload(cells)
            return payload
        start_row, start_col, end_row, end_col = parsed
        area = (end_row - start_row + 1) * (end_col - start_col + 1)
        if area > _INSPECT_CELL_LIMIT:
            return {"ok": False, "error": "inspect_too_large"}
        cells = [
            self._cell_payload(r, c)
            for (r, c) in sorted(self._cells)
            if start_row <= r <= end_row and start_col <= c <= end_col
        ]
        payload["range"] = {
            "sheet": self._sheet_id,
            "a1": _to_a1(start_row, start_col, end_row, end_col),
            "startRow": start_row,
            "startColumn": start_col,
            "endRow": end_row,
            "endColumn": end_col,
            "cells": cells,
        }
        return payload

    def range_get(self, params: Mapping[str, object]) -> Mapping[str, Any]:
        if self._kind != "sheet":
            return {"ok": False, "error": "unit_kind_mismatch"}
        parsed = _parse_range(params.get("a1") or params.get("range"))
        if parsed is None:
            return {"ok": False, "error": "not_found"}
        start_row, start_col, end_row, end_col = parsed
        cells = [
            self._cell_payload(r, c)
            for r in range(start_row, end_row + 1)
            for c in range(start_col, end_col + 1)
            if (r, c) in self._cells
        ]
        return {
            "ok": True,
            "a1": _to_a1(start_row, start_col, end_row, end_col),
            "cells": cells,
        }

    def range_set(self, params: Mapping[str, object]) -> Mapping[str, Any]:
        if self._kind != "sheet":
            return {"ok": False, "error": "unit_kind_mismatch"}
        parsed = _parse_range(params.get("a1") or params.get("range"))
        if parsed is None:
            return {"ok": False, "error": "not_found"}
        start_row, start_col, _end_row, _end_col = parsed
        formula = params.get("formula")
        if formula is None:
            formula = params.get("setFormula")
        value = params.get("value")
        if isinstance(formula, str) and formula:
            self._put_cell(start_row, start_col, {"f": formula})
            self._dirty = True
            return {"ok": True}
        if isinstance(value, str) and value.startswith("="):
            self._put_cell(start_row, start_col, {"f": value})
            self._dirty = True
            return {"ok": True}
        self._put_cell(start_row, start_col, _cell_from_value(value))
        return {"ok": True}

    def execute_command(self, params: Mapping[str, object]) -> Mapping[str, Any]:
        command_id = params.get("id")
        if not isinstance(command_id, str) or not command_id:
            return {"ok": False, "error": "command_not_allowlisted"}
        if mutation_id(command_id):
            return {"ok": False, "error": "mutation_forbidden"}
        if command_id not in COMMAND_ALLOWLIST:
            return {"ok": False, "error": "command_not_allowlisted"}
        if command_id.startswith("doc.command.") and self._kind != "doc":
            return {"ok": False, "error": "unit_kind_mismatch"}
        if command_id.startswith("sheet.command.") and self._kind != "sheet":
            return {"ok": False, "error": "unit_kind_mismatch"}
        body = params.get("params", {})
        if not isinstance(body, Mapping):
            return {"ok": False, "error": "command_failed"}
        if command_id == "sheet.command.set-range-values":
            return self._set_range_values(body)
        if command_id in {
            "sheet.command.insert-row",
            "sheet.command.insert-col",
            "sheet.command.remove-row",
            "sheet.command.remove-col",
        }:
            self._dirty = True
        return {"ok": True}

    def formula_wait(self, params: Mapping[str, object]) -> Mapping[str, Any]:
        if self._formula_timeout:
            return {"ok": False, "error": "formula_timeout"}
        if not self._dirty:
            return {"ok": True, "formula_dirty": False}
        self._apply_formulas()
        self._dirty = False
        return {"ok": True, "formula_dirty": False}

    def save(self, params: Mapping[str, object]) -> Mapping[str, Any]:
        raw = params.get("path")
        if raw is None:
            path = _SAVE_SHEET if self._kind == "sheet" else _SAVE_DOC
        elif not isinstance(raw, str):
            return {"ok": False, "error": "path_denied"}
        else:
            path = raw
        allowed = _SAVE_SHEET if self._kind == "sheet" else _SAVE_DOC
        if path != allowed:
            return {"ok": False, "error": "path_denied"}
        if self._dirty and self._has_formulas():
            return {"ok": False, "error": "formula_dirty"}
        snapshot = self._snapshot()
        text = json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"
        encoded = text.encode("utf-8")
        target = self._session_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
        return {"ok": True, "path": path, "bytes": len(encoded)}

    def _inspect_doc(self, params: Mapping[str, object]) -> Mapping[str, Any]:
        return {
            "ok": True,
            "unit": self._unit_payload(),
            "outline": {
                "title": self._unit_name,
                "data_stream_length": 2,
                "paragraph_count": 1,
                "sections": [{"startIndex": 1}],
            },
            "paragraphs": [{"startIndex": 0, "text": "", "length": 0}],
        }

    def _set_range_values(self, body: Mapping[str, object]) -> Mapping[str, Any]:
        parsed = _parse_range(body.get("range") or body.get("a1"))
        if parsed is None:
            return {"ok": False, "error": "command_failed"}
        start_row, start_col, end_row, end_col = parsed
        value = body.get("value")
        cells = _expand_command_values(value, start_row, start_col, end_row, end_col)
        if cells is None:
            return {"ok": False, "error": "command_failed"}
        dirty = False
        for (row, col), cell in cells.items():
            self._put_cell(row, col, cell)
            if cell.get("f"):
                dirty = True
        if dirty:
            self._dirty = True
        return {"ok": True}

    def _put_cell(self, row: int, col: int, cell: Mapping[str, Any]) -> None:
        stored = dict(self._cells.get((row, col), {}))
        for key, item in cell.items():
            if item is None:
                stored.pop(key, None)
            else:
                stored[key] = item
        if "f" in stored and stored["f"] and "v" not in cell:
            stored.pop("v", None)
            stored.pop("t", None)
        if not stored:
            self._cells.pop((row, col), None)
            return
        self._cells[(row, col)] = stored

    def _cell_payload(self, row: int, col: int) -> dict[str, Any]:
        cell = self._cells[(row, col)]
        payload: dict[str, Any] = {"r": row, "c": col}
        payload["v"] = cell.get("v")
        payload["t"] = cell.get("t")
        payload["f"] = cell.get("f")
        return payload

    def _range_payload(self, cells: list[dict[str, Any]]) -> dict[str, Any]:
        rows = [item["r"] for item in cells]
        cols = [item["c"] for item in cells]
        start_row, end_row = min(rows), max(rows)
        start_col, end_col = min(cols), max(cols)
        return {
            "sheet": self._sheet_id,
            "a1": _to_a1(start_row, start_col, end_row, end_col),
            "startRow": start_row,
            "startColumn": start_col,
            "endRow": end_row,
            "endColumn": end_col,
            "cells": cells,
        }

    def _unit_payload(self) -> dict[str, Any]:
        return {
            "type": self._kind,
            "unit_id": self._unit_id,
            "name": self._unit_name,
            "lifecycle": "Steady",
            "univer_instance_type": 2 if self._kind == "sheet" else 1,
        }

    def _sheet_outline(self) -> dict[str, Any]:
        return {
            "sheet_order": [self._sheet_id],
            "sheets": [
                {
                    "id": self._sheet_id,
                    "name": self._sheet_name,
                    "row_count": self._row_count,
                    "column_count": self._column_count,
                    "row_height": _EMPTY_ROW_HEIGHT,
                    "column_width": _EMPTY_COLUMN_WIDTH,
                }
            ],
            "active_sheet_id": self._sheet_id,
        }

    def _has_formulas(self) -> bool:
        return any(cell.get("f") for cell in self._cells.values())

    def _formula_errors(self) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        for (row, col), cell in sorted(self._cells.items()):
            value = cell.get("v")
            if value not in _ERROR_TYPES:
                continue
            errors.append(
                {
                    "code": value,
                    "a1": _to_a1(row, col, row, col),
                    "sheet": self._sheet_name,
                }
            )
        return errors

    def _apply_formulas(self) -> None:
        pending = [
            (coord, cell["f"])
            for coord, cell in self._cells.items()
            if cell.get("f")
        ]
        for _ in range(len(pending) + 1):
            progress = False
            remaining: list[tuple[tuple[int, int], str]] = []
            for coord, formula in pending:
                try:
                    value = _eval_formula(formula, self._cells)
                except ZeroDivisionError:
                    value = "#DIV/0!"
                except ValueError as exc:
                    if str(exc) == "missing":
                        remaining.append((coord, formula))
                        continue
                    value = "#NAME?"
                except SyntaxError:
                    value = "#NAME?"
                except Exception:
                    remaining.append((coord, formula))
                    continue
                cell = dict(self._cells[coord])
                cell["v"] = value
                cell["t"] = 2 if isinstance(value, (int, float)) and not isinstance(
                    value, bool
                ) else 1
                self._cells[coord] = cell
                progress = True
            pending = remaining
            if not remaining or not progress:
                break

    def _reset_empty_unit(self) -> None:
        self._cells.clear()
        self._dirty = False
        self._sheet_id = "sheet-01"
        self._sheet_name = "Sheet1"
        self._unit_id = "workbook-01" if self._kind == "sheet" else "document-01"
        self._unit_name = "Workbook" if self._kind == "sheet" else "Document1"
        self._row_count = _EMPTY_ROW_COUNT
        self._column_count = _EMPTY_COLUMN_COUNT

    def _apply_snapshot(self, snapshot: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if self._kind == "sheet" and "body" in snapshot and "sheets" not in snapshot:
            return {"ok": False, "error": "snapshot_invalid"}
        if self._kind == "doc" and "sheets" in snapshot and "body" not in snapshot:
            return {"ok": False, "error": "snapshot_invalid"}
        if self._kind == "sheet" and "sheets" in snapshot and not isinstance(
            snapshot.get("sheets"), Mapping
        ):
            return {"ok": False, "error": "snapshot_invalid"}
        self._reset_empty_unit()
        unit_id = snapshot.get("id")
        if isinstance(unit_id, str) and unit_id:
            self._unit_id = unit_id
        if self._kind == "doc":
            title = snapshot.get("title")
            if isinstance(title, str) and title:
                self._unit_name = title
            return None
        name = snapshot.get("name")
        if isinstance(name, str) and name:
            self._unit_name = name
        order = snapshot.get("sheetOrder")
        sheets = snapshot.get("sheets")
        if isinstance(order, list) and order and isinstance(order[0], str):
            self._sheet_id = order[0]
        if not isinstance(sheets, Mapping):
            return None
        sheet = sheets.get(self._sheet_id)
        if not isinstance(sheet, Mapping) and sheets:
            first = next(iter(sheets.values()), None)
            sheet = first if isinstance(first, Mapping) else None
        if not isinstance(sheet, Mapping):
            return None
        sheet_id = sheet.get("id")
        if isinstance(sheet_id, str) and sheet_id:
            self._sheet_id = sheet_id
        sheet_name = sheet.get("name")
        if isinstance(sheet_name, str) and sheet_name:
            self._sheet_name = sheet_name
        row_count = sheet.get("rowCount")
        if isinstance(row_count, int) and row_count > 0:
            self._row_count = row_count
        column_count = sheet.get("columnCount")
        if isinstance(column_count, int) and column_count > 0:
            self._column_count = column_count
        cell_data = sheet.get("cellData")
        if isinstance(cell_data, Mapping):
            for row_key, row in cell_data.items():
                if not isinstance(row, Mapping):
                    continue
                try:
                    row_i = int(row_key)
                except (TypeError, ValueError):
                    continue
                for col_key, cell in row.items():
                    try:
                        col_i = int(col_key)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(cell, Mapping):
                        self._cells[(row_i, col_i)] = dict(cell)
        return None

    def _snapshot(self) -> dict[str, Any]:
        if self._kind == "doc":
            return {
                "id": self._unit_id,
                "title": self._unit_name,
                "appVersion": _APP_VERSION,
                "body": {
                    "dataStream": "\r\n",
                    "paragraphs": [{"startIndex": 0}],
                    "sectionBreaks": [{"startIndex": 1}],
                },
                "resources": [],
            }
        cell_data: dict[str, dict[str, dict[str, Any]]] = {}
        for (row, col), cell in sorted(self._cells.items()):
            row_key = str(row)
            col_key = str(col)
            cell_data.setdefault(row_key, {})[col_key] = dict(cell)
        return {
            "id": self._unit_id,
            "name": self._unit_name,
            "appVersion": _APP_VERSION,
            "sheetOrder": [self._sheet_id],
            "sheets": {
                self._sheet_id: {
                    "id": self._sheet_id,
                    "name": self._sheet_name,
                    "rowCount": self._row_count,
                    "columnCount": self._column_count,
                    "defaultRowHeight": _EMPTY_ROW_HEIGHT,
                    "defaultColumnWidth": _EMPTY_COLUMN_WIDTH,
                    "cellData": cell_data,
                }
            },
            "resources": [],
        }


def _confine(session_dir: Path, raw: object) -> Path | None:
    if not isinstance(raw, str) or not raw or "\0" in raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        return None
    resolved = (session_dir / candidate).resolve()
    if not resolved.is_relative_to(session_dir.resolve()):
        return None
    return resolved


def _col_index(letters: str) -> int:
    index = 0
    for char in letters.upper():
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _col_letters(index: int) -> str:
    n = index + 1
    chars: list[str] = []
    while n:
        n, rem = divmod(n - 1, 26)
        chars.append(chr(65 + rem))
    return "".join(reversed(chars))


def _to_a1(start_row: int, start_col: int, end_row: int, end_col: int) -> str:
    start = f"{_col_letters(start_col)}{start_row + 1}"
    if start_row == end_row and start_col == end_col:
        return start
    return f"{start}:{_col_letters(end_col)}{end_row + 1}"


def _parse_range(raw: object) -> tuple[int, int, int, int] | None:
    if isinstance(raw, Mapping):
        try:
            start_row = int(raw["startRow"])
            start_col = int(raw["startColumn"])
            end_row = int(raw.get("endRow", start_row))
            end_col = int(raw.get("endColumn", start_col))
        except (KeyError, TypeError, ValueError):
            return None
        if min(start_row, start_col, end_row, end_col) < 0:
            return None
        if end_row < start_row or end_col < start_col:
            return None
        return start_row, start_col, end_row, end_col
    if not isinstance(raw, str) or not raw:
        return None
    match = _A1_RANGE.fullmatch(raw.strip())
    if match is None:
        return None
    start_col = _col_index(match.group(1))
    start_row = int(match.group(2)) - 1
    if match.group(3) is None:
        return start_row, start_col, start_row, start_col
    end_col = _col_index(match.group(3))
    end_row = int(match.group(4)) - 1
    if min(start_row, start_col, end_row, end_col) < 0:
        return None
    if end_row < start_row:
        start_row, end_row = end_row, start_row
    if end_col < start_col:
        start_col, end_col = end_col, start_col
    return start_row, start_col, end_row, end_col


def _cell_from_value(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, bool):
        return {"v": value, "t": 3}
    if isinstance(value, (int, float)):
        return {"v": value, "t": 2}
    if value is None:
        return {}
    return {"v": value, "t": 1}


def _expand_command_values(
    value: object,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
) -> dict[tuple[int, int], dict[str, Any]] | None:
    if isinstance(value, list):
        cells: dict[tuple[int, int], dict[str, Any]] = {}
        for r_off, row in enumerate(value):
            if not isinstance(row, list):
                return None
            for c_off, item in enumerate(row):
                cells[(start_row + r_off, start_col + c_off)] = _cell_from_value(item)
        return cells
    if isinstance(value, Mapping) and any(str(key).isdigit() for key in value):
        cells = {}
        for row_key, row in value.items():
            if not isinstance(row, Mapping):
                return None
            try:
                row_i = int(row_key)
            except (TypeError, ValueError):
                return None
            for col_key, item in row.items():
                try:
                    col_i = int(col_key)
                except (TypeError, ValueError):
                    return None
                cells[(row_i, col_i)] = _cell_from_value(item)
        return cells
    cell = _cell_from_value(value)
    return {
        (row, col): dict(cell)
        for row in range(start_row, end_row + 1)
        for col in range(start_col, end_col + 1)
    }


def _eval_formula(formula: str, cells: Mapping[tuple[int, int], Mapping[str, Any]]) -> Any:
    expr = formula[1:] if formula.startswith("=") else formula

    def replace_ref(match: re.Match[str]) -> str:
        col = _col_index(match.group(1))
        row = int(match.group(2)) - 1
        cell = cells.get((row, col), {})
        if "v" not in cell:
            raise ValueError("missing")
        value = cell["v"]
        return str(value)

    replaced = _CELL_REF.sub(replace_ref, expr)
    tree = ast.parse(replaced, mode="eval")
    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    raise ValueError("unsupported formula")

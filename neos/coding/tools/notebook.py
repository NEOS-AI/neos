"""Structured Jupyter notebook edits. Does not execute cells."""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

EditMode = Literal["replace", "insert", "delete"]
CellType = Literal["code", "markdown"]


class NotebookError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def is_notebook_path(path: str) -> bool:
    return path.rsplit("/", 1)[-1].casefold().endswith(".ipynb")


def _cell_source(value: object) -> str:
    if isinstance(value, list):
        return "".join(str(part) for part in value)
    if value is None:
        return ""
    return str(value)


def _source_lines(text: str) -> list[str]:
    if text == "":
        return []
    if text.endswith("\n"):
        return [f"{line}\n" for line in text.splitlines()]
    lines = text.splitlines()
    if len(lines) == 1:
        return [text]
    return [f"{line}\n" for line in lines[:-1]] + [lines[-1]]


def _new_cell_id() -> str:
    return uuid.uuid4().hex[:12]


def _empty_notebook() -> dict[str, Any]:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            }
        },
        "cells": [],
    }


def parse_notebook(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NotebookError("policy_notebook_invalid") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("cells"), list):
        raise NotebookError("policy_notebook_invalid")
    return payload


def _find_cell(cells: list[Any], cell_id: str | None) -> int:
    if cell_id is None:
        raise NotebookError("policy_notebook_cell_missing")
    for index, cell in enumerate(cells):
        if isinstance(cell, dict) and str(cell.get("id") or "") == cell_id:
            return index
        if str(index) == cell_id:
            return index
    raise NotebookError("policy_notebook_cell_missing")


def _make_cell(cell_type: CellType, source: str, cell_id: str) -> dict[str, Any]:
    cell: dict[str, Any] = {
        "id": cell_id,
        "cell_type": cell_type,
        "metadata": {},
        "source": _source_lines(source),
    }
    if cell_type == "code":
        cell["outputs"] = []
        cell["execution_count"] = None
    return cell


def apply_notebook_edit(
    raw: bytes | None,
    *,
    edit_mode: EditMode,
    new_source: str,
    cell_id: str | None,
    cell_type: CellType | None,
) -> tuple[bytes, dict[str, object]]:
    if raw is None:
        if edit_mode != "insert":
            raise NotebookError("policy_notebook_invalid")
        notebook = _empty_notebook()
    else:
        notebook = parse_notebook(raw)
    cells = notebook["cells"]
    language = str(
        ((notebook.get("metadata") or {}).get("kernelspec") or {}).get(
            "language"
        )
        or "python"
    )

    if edit_mode == "delete":
        index = _find_cell(cells, cell_id)
        removed = cells.pop(index)
        result_id = str(removed.get("id") or cell_id or "")
        result_type = str(removed.get("cell_type") or "code")
        source = ""
    elif edit_mode == "insert":
        kind: CellType = cell_type or "code"
        new_id = _new_cell_id()
        cell = _make_cell(kind, new_source, new_id)
        if cell_id is None or not cells:
            cells.insert(0, cell)
        else:
            cells.insert(_find_cell(cells, cell_id) + 1, cell)
        result_id = new_id
        result_type = kind
        source = new_source
    else:
        index = _find_cell(cells, cell_id)
        cell = cells[index]
        if not isinstance(cell, dict):
            raise NotebookError("policy_notebook_invalid")
        if cell_type is not None:
            cell["cell_type"] = cell_type
        cell["source"] = _source_lines(new_source)
        if cell.get("cell_type") == "code":
            cell.setdefault("outputs", [])
            cell["execution_count"] = None
        if not cell.get("id"):
            cell["id"] = _new_cell_id()
        result_id = str(cell["id"])
        result_type = str(cell.get("cell_type") or "code")
        source = new_source

    payload = json.dumps(notebook, ensure_ascii=False, indent=1).encode("utf-8")
    return payload, {
        "cell_id": result_id,
        "cell_type": result_type,
        "edit_mode": edit_mode,
        "language": language,
        "source": source,
    }

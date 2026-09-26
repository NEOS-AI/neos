from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from openpyxl import Workbook

from neos.fsi.safety import SUCCESS_ARTIFACT_STATUS

_DENIED: dict[str, object] = {"ok": False, "error": "path_denied"}


def stage_xlsx(
    workspace: Path, *, path: str, rows: Sequence[Sequence[object]]
) -> Mapping[str, object]:
    workspace = workspace.resolve()
    out_root = (workspace / "out").resolve()
    if not path or "\0" in path:
        return dict(_DENIED)
    candidate = Path(path)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        return dict(_DENIED)
    resolved = (workspace / candidate).resolve()
    if resolved.parent != out_root:
        return dict(_DENIED)
    if not resolved.is_relative_to(workspace):
        return dict(_DENIED)
    if resolved.suffix.lower() != ".xlsx":
        return dict(_DENIED)
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(list(row))
    out_root.mkdir(parents=True, exist_ok=True)
    workbook.save(resolved)
    return {
        "ok": True,
        "path": resolved.relative_to(workspace).as_posix(),
        "status": SUCCESS_ARTIFACT_STATUS,
    }

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_DENIED = {"ok": False, "error": "path_denied"}
_XLSX = {"ok": False, "error": "xlsx_forbidden"}
_MISSING = {"ok": False, "error": "not_found"}
_DECODE = {"ok": False, "error": "decode_error"}
_INVALID = {"ok": False, "error": "invalid_content"}
_NO_TOOL = {"ok": False, "error": "tool_not_allowed"}

_READ = "read_file.v1"
_WRITE = "write_file.v1"
_SEARCH = "search_text.v1"

_SOURCE_RE = re.compile(r"^[A-Za-z0-9 ._/:#-]+$")
_SOURCE_MAX = 256


class FsiParentWorkspacePort:
    def __init__(self, workspace: Path, *, write: bool) -> None:
        self._workspace = workspace.resolve()
        self._write = write
        self._spec_root = (self._workspace / "out" / "_spec").resolve()

    def definitions(self) -> tuple[str, ...]:
        if self._write:
            return (_READ, _WRITE)
        return (_READ, _SEARCH)

    async def execute(
        self, name: str, input: Mapping[str, object]
    ) -> Mapping[str, Any]:
        if name not in self.definitions():
            return dict(_NO_TOOL)
        payload = dict(input)
        if name == _READ:
            return self._read(payload)
        if name == _WRITE:
            return self._write_file(payload)
        return self._search(payload)

    def _read(self, payload: Mapping[str, object]) -> Mapping[str, Any]:
        resolved = self._confine(payload.get("path"))
        if resolved is None:
            return dict(_DENIED)
        if self._write and not _writer_readable(resolved, self._spec_root):
            return dict(_DENIED)
        if not resolved.is_file():
            return dict(_MISSING)
        try:
            text = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return dict(_DECODE)
        except OSError:
            return dict(_MISSING)
        if self._write:
            return {"ok": True, "content": text}
        source = resolved.relative_to(self._workspace).as_posix()
        return {"ok": True, "content": wrap_untrusted_document(text, source)}

    def _write_file(self, payload: Mapping[str, object]) -> Mapping[str, Any]:
        raw = payload.get("path")
        resolved = self._confine(raw)
        if resolved is None:
            return dict(_DENIED)
        if _is_xlsx(raw, resolved):
            return dict(_XLSX)
        if resolved.suffix != ".json" or resolved.parent != self._spec_root:
            return dict(_DENIED)
        content = payload.get("content", "")
        if not isinstance(content, str):
            return dict(_INVALID)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return {"ok": True, "path": resolved.relative_to(self._workspace).as_posix()}

    def _search(self, payload: Mapping[str, object]) -> Mapping[str, Any]:
        query = str(payload.get("query", ""))
        matches: list[dict[str, object]] = []
        if not query:
            return {"ok": True, "matches": matches}
        for path in self._workspace.rglob("*"):
            try:
                if not path.is_file():
                    continue
                resolved = path.resolve()
                if not resolved.is_relative_to(self._workspace):
                    continue
                text = resolved.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if query not in text:
                continue
            rel = path.relative_to(self._workspace).as_posix()
            matches.append({"path": rel, "snippet": query})
        return {"ok": True, "matches": matches}

    def _confine(self, raw: object) -> Path | None:
        if not isinstance(raw, str) or not raw or "\0" in raw:
            return None
        candidate = Path(raw)
        if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
            return None
        resolved = (self._workspace / candidate).resolve()
        if not resolved.is_relative_to(self._workspace):
            return None
        return resolved


def wrap_untrusted_document(text: str, source: str) -> str:
    if len(source) > _SOURCE_MAX or not _SOURCE_RE.fullmatch(source):
        source = "unknown"
    return (
        f'<untrusted_document source="{source}">\n'
        f"{text}\n"
        "</untrusted_document>"
    )


def _writer_readable(resolved: Path, spec_root: Path) -> bool:
    return resolved.parent == spec_root and resolved.suffix == ".json"


def _is_xlsx(raw: object, resolved: Path) -> bool:
    if resolved.suffix.lower() == ".xlsx":
        return True
    if isinstance(raw, str) and raw.lower().endswith(".xlsx"):
        return True
    return False

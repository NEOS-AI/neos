from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from neos.univer.allowlist import COMMAND_ALLOWLIST, mutation_id
from neos.univer.sidecar import InMemorySidecar, SidecarClient

_DENIED = {"ok": False, "error": "path_denied"}
_XLSX = {"ok": False, "error": "xlsx_forbidden"}
_MISSING = {"ok": False, "error": "not_found"}
_DECODE = {"ok": False, "error": "decode_error"}
_INVALID = {"ok": False, "error": "invalid_content"}
_NO_TOOL = {"ok": False, "error": "tool_not_allowed"}
_NOT_ALLOWLISTED = {"ok": False, "error": "command_not_allowlisted"}
_MUTATION = {"ok": False, "error": "mutation_forbidden"}

_READ = "read_file.v1"
_WRITE = "write_file.v1"
_SEARCH = "search_text.v1"

_SIDECAR_TOOLS = (
    "univer.inspect.v1",
    "univer.range_get.v1",
    "univer.range_set.v1",
    "univer.execute_command.v1",
    "univer.formula_wait.v1",
    "univer.save.v1",
)
_EXECUTE_COMMAND = "univer.execute_command.v1"
_RPC_METHODS = {
    "univer.inspect.v1": "inspect",
    "univer.range_get.v1": "range_get",
    "univer.range_set.v1": "range_set",
    "univer.execute_command.v1": "execute_command",
    "univer.formula_wait.v1": "formula_wait",
    "univer.save.v1": "save",
}
_XLSX_SUFFIXES = {".xlsx", ".xlsm", ".xls"}

_SOURCE_RE = re.compile(r"^[A-Za-z0-9 ._/:#-]+$")
_SOURCE_MAX = 256
_UNTRUSTED_CLOSE = "</untrusted_document>"
_UNTRUSTED_CLOSE_RE = re.compile(re.escape(_UNTRUSTED_CLOSE), re.IGNORECASE)


class UniverParentWorkspacePort:
    def __init__(self, workspace: Path, *, write: bool) -> None:
        self._workspace = workspace.resolve()
        self._write = write
        self._draft_root = (self._workspace / "draft").resolve()

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
        if self._write and not _writer_readable(resolved, self._draft_root):
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
        if resolved.suffix != ".json" or resolved.parent != self._draft_root:
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


class UniverSessionPort:
    def __init__(
        self,
        workspace: Path,
        *,
        write: bool,
        sidecar: SidecarClient | InMemorySidecar,
    ) -> None:
        self._files = UniverParentWorkspacePort(workspace, write=write)
        self._sidecar = UniverToolPort(sidecar)

    def definitions(self) -> tuple[str, ...]:
        return self._files.definitions() + self._sidecar.definitions()

    async def execute(
        self, name: str, input: Mapping[str, object]
    ) -> Mapping[str, Any]:
        try:
            if name.startswith("univer.") or name in self._sidecar.definitions():
                return await self._sidecar.execute(name, input)
            return await self._files.execute(name, input)
        except Exception:
            return dict(_NO_TOOL)


class UniverToolPort:
    def __init__(self, sidecar: SidecarClient | InMemorySidecar) -> None:
        self._sidecar = sidecar

    def definitions(self) -> tuple[str, ...]:
        return _SIDECAR_TOOLS

    async def execute(
        self, name: str, input: Mapping[str, object]
    ) -> Mapping[str, Any]:
        try:
            return self._execute(name, input)
        except Exception:
            return {"ok": False, "error": self._unavailable()}

    def _execute(
        self, name: str, input: Mapping[str, object]
    ) -> Mapping[str, Any]:
        if name not in self.definitions():
            return dict(_NO_TOOL)
        if name == _EXECUTE_COMMAND:
            gated = _gate_execute_command(input)
            if gated is not None:
                return gated
        method = _RPC_METHODS.get(name)
        if method is None:
            return dict(_NO_TOOL)
        return self._dispatch(method, dict(input))

    def _dispatch(
        self, method: str, params: Mapping[str, object]
    ) -> Mapping[str, Any]:
        caller = getattr(self._sidecar, "call", None)
        if callable(caller):
            result = caller(method, params)
            return _as_tool_result(result, self._unavailable())
        dedicated = getattr(self._sidecar, method, None)
        if callable(dedicated):
            result = dedicated(params)
            return _as_tool_result(result, self._unavailable())
        return {"ok": False, "error": self._unavailable()}

    def _unavailable(self) -> str:
        unavailable = getattr(self._sidecar, "unavailable_error", None)
        if callable(unavailable):
            return str(unavailable())
        return "sidecar_unavailable"


def wrap_untrusted_document(text: str, source: str) -> str:
    if len(source) > _SOURCE_MAX or not _SOURCE_RE.fullmatch(source):
        source = "unknown"
    safe = _UNTRUSTED_CLOSE_RE.sub("</untrusted-document>", text)
    return (
        f'<untrusted_document source="{source}">\n'
        f"{safe}\n"
        "</untrusted_document>"
    )


def _gate_execute_command(payload: Mapping[str, object]) -> Mapping[str, Any] | None:
    command_id = payload.get("id")
    if not isinstance(command_id, str) or not command_id:
        return dict(_NOT_ALLOWLISTED)
    if mutation_id(command_id):
        return dict(_MUTATION)
    if command_id not in COMMAND_ALLOWLIST:
        return dict(_NOT_ALLOWLISTED)
    return None


def _writer_readable(resolved: Path, draft_root: Path) -> bool:
    return resolved.parent == draft_root and resolved.suffix == ".json"


def _is_xlsx(raw: object, resolved: Path) -> bool:
    if resolved.suffix.lower() in _XLSX_SUFFIXES:
        return True
    if isinstance(raw, str) and Path(raw).suffix.lower() in _XLSX_SUFFIXES:
        return True
    return False


def _as_tool_result(result: object, fallback: str) -> Mapping[str, Any]:
    if isinstance(result, Mapping) and "ok" in result:
        return dict(result)
    return {"ok": False, "error": fallback}

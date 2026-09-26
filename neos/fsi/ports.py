from __future__ import annotations

import fnmatch
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from neos.fsi.handoff import (
    ALLOWED_TARGETS,
    HANDOFF_TOOL_NAME,
    HandoffCommand,
    validate_handoff,
)
from neos.fsi.mcp_attach import SCREENING_SEARCH, screening_search
from neos.fsi.profile import SCREENING_STUB_TOOLS, skill_permitted
from neos.fsi.safety import binding_error, policy_binding_denied
from neos.fsi.stage_xlsx import stage_xlsx
from neos.skills.markdown_catalog import fsi_catalog

_DENIED = {"ok": False, "error": "path_denied"}
_XLSX = {"ok": False, "error": "xlsx_forbidden"}
_MISSING = {"ok": False, "error": "not_found"}
_DECODE = {"ok": False, "error": "decode_error"}
_INVALID = {"ok": False, "error": "invalid_content"}
_NO_TOOL = {"ok": False, "error": "tool_not_allowed"}
_UNKNOWN_SKILL = {"ok": False, "error": "unknown_skill"}

_READ = "read_file.v1"
_WRITE = "write_file.v1"
_SEARCH = "search_text.v1"
_GLOB = "glob_files.v1"
_STAGE = "stage_xlsx.v1"
_LOAD_SKILL = "load_skill.v1"

_SOURCE_RE = re.compile(r"^[A-Za-z0-9 ._/:#-]+$")
_SOURCE_MAX = 256
_UNTRUSTED_CLOSE = "</untrusted_document>"
_UNTRUSTED_CLOSE_RE = re.compile(re.escape(_UNTRUSTED_CLOSE), re.IGNORECASE)


class FsiParentWorkspacePort:
    def __init__(self, workspace: Path, *, write: bool) -> None:
        self._workspace = workspace.resolve()
        self._write = write
        self._spec_root = (self._workspace / "out" / "_spec").resolve()

    def definitions(self) -> tuple[str, ...]:
        if self._write:
            return (_READ, _WRITE)
        return (_READ, _SEARCH, _GLOB, _STAGE)

    async def execute(
        self, name: str, input: Mapping[str, object]
    ) -> Mapping[str, Any]:
        if policy_binding_denied(name):
            return {**binding_error(name), "ok": False}
        if name not in self.definitions():
            return dict(_NO_TOOL)
        payload = dict(input)
        if name == _READ:
            return self._read(payload)
        if name == _WRITE:
            return self._write_file(payload)
        if name == _GLOB:
            return self._glob(payload)
        if name == _STAGE:
            return self._stage(payload)
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

    def _glob(self, payload: Mapping[str, object]) -> Mapping[str, Any]:
        raw = payload.get("pattern", "**/*")
        pattern = raw if isinstance(raw, str) and raw else "**/*"
        if self._confine(pattern) is None:
            return dict(_DENIED)
        matches: list[dict[str, object]] = []
        for path in self._workspace.rglob("*"):
            try:
                if not path.is_file():
                    continue
                resolved = path.resolve()
                if not resolved.is_relative_to(self._workspace):
                    continue
                rel = path.relative_to(self._workspace).as_posix()
                if self._confine(rel) is None:
                    continue
                if not _glob_match(rel, pattern):
                    continue
            except (OSError, ValueError):
                continue
            matches.append({"path": rel})
        return {"ok": True, "matches": matches}

    def _stage(self, payload: Mapping[str, object]) -> Mapping[str, Any]:
        path = payload.get("path")
        rows = payload.get("rows", ())
        if not isinstance(path, str):
            return dict(_DENIED)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            return dict(_INVALID)
        normalized: list[Sequence[object]] = []
        for row in rows:
            if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
                return dict(_INVALID)
            normalized.append(row)
        return dict(stage_xlsx(self._workspace, path=path, rows=normalized))

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


class FsiSessionPort:
    def __init__(
        self,
        workspace: Path,
        *,
        write: bool,
        skill_allowlist: frozenset[str] = frozenset(),
        mcp_allowlist: frozenset[str] = frozenset(),
        from_slug: str = "",
        handoff_allowlist: frozenset[str] = frozenset(),
    ) -> None:
        self._files = FsiParentWorkspacePort(workspace, write=write)
        self._skill_allowlist = skill_allowlist
        self._mcp_allowlist = mcp_allowlist
        self._from_slug = from_slug
        self._handoff_allowlist = handoff_allowlist

    def definitions(self) -> tuple[str, ...]:
        names = self._files.definitions()
        if self._skill_allowlist:
            names = names + (_LOAD_SKILL,)
        if "screening" in self._mcp_allowlist:
            names = names + tuple(sorted(SCREENING_STUB_TOOLS))
        if self._handoff_allowlist:
            names = names + (HANDOFF_TOOL_NAME,)
        return names

    async def execute(
        self, name: str, input: Mapping[str, object]
    ) -> Mapping[str, Any]:
        if policy_binding_denied(name):
            return {**binding_error(name), "ok": False}
        if name == HANDOFF_TOOL_NAME:
            if HANDOFF_TOOL_NAME not in self.definitions():
                return dict(_NO_TOOL)
            return self._handoff(input)
        if name == _LOAD_SKILL:
            if _LOAD_SKILL not in self.definitions():
                return dict(_NO_TOOL)
            return self._load_skill(input)
        if name == SCREENING_SEARCH:
            if SCREENING_SEARCH not in self.definitions():
                return dict(_NO_TOOL)
            return dict(screening_search(input))
        try:
            return await self._files.execute(name, input)
        except Exception:
            return dict(_NO_TOOL)

    def _handoff(self, payload: Mapping[str, object]) -> Mapping[str, Any]:
        target = payload.get("target")
        if not isinstance(target, str) or target not in self._handoff_allowlist:
            return {"ok": False, "error": "policy_handoff_denied"}
        if target not in ALLOWED_TARGETS:
            return {"ok": False, "error": "policy_handoff_denied"}
        result = validate_handoff(self._from_slug, payload)
        if isinstance(result, HandoffCommand):
            return {
                "ok": True,
                "target": result.target,
                "event": result.event,
                "context_ref": result.context_ref,
            }
        return dict(result)

    def _load_skill(self, payload: Mapping[str, object]) -> Mapping[str, Any]:
        name = payload.get("name")
        if not isinstance(name, str) or not skill_permitted(
            name, self._skill_allowlist
        ):
            return dict(_UNKNOWN_SKILL)
        catalog = fsi_catalog()
        if catalog.get(name) is None:
            return dict(_UNKNOWN_SKILL)
        markdown = catalog.load_markdown(name)
        if markdown is None:
            return dict(_UNKNOWN_SKILL)
        return {"ok": True, "name": name, "markdown": markdown}


def wrap_untrusted_document(text: str, source: str) -> str:
    if len(source) > _SOURCE_MAX or not _SOURCE_RE.fullmatch(source):
        source = "unknown"
    safe = _UNTRUSTED_CLOSE_RE.sub("</untrusted-document>", text)
    return (
        f'<untrusted_document source="{source}">\n'
        f"{safe}\n"
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


def _glob_match(rel: str, pattern: str) -> bool:
    return _glob_parts(rel.split("/"), pattern.split("/"))


def _glob_parts(parts: list[str], pat: list[str]) -> bool:
    if not pat:
        return not parts
    if pat[0] == "**":
        if _glob_parts(parts, pat[1:]):
            return True
        return bool(parts) and _glob_parts(parts[1:], pat)
    if not parts:
        return False
    if not fnmatch.fnmatch(parts[0], pat[0]):
        return False
    return _glob_parts(parts[1:], pat[1:])

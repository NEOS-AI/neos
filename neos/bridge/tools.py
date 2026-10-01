"""브리지의 로컬 도구 -- 트랙 Q16a. 전부 READ_ONLY 이고 아무것도 실행하지 않는다.

경계:

- 루트는 사용자가 명시한 폴더 하나다(실경로로 고정). 파일시스템 루트와 홈 폴더 자체는 거절한다
- 경로는 루트 기준 상대 경로만. 절대 경로 · 드라이브 문자 · `..` · NUL 은 `path_escape`
- 심볼릭 링크로 루트 밖에 닿으면 `path_escape` -- 실경로로 다시 본다
- 비밀 경로(`.env`·`.ssh`·`id_rsa` ...)는 서버와 **같은 함수**(`is_denied_secret_path`)로 거절하고,
  목록에서는 숨긴다. 링크를 따라간 실경로도 같은 함수로 본다
- 파일은 `O_NOFOLLOW | O_NONBLOCK` 으로 연다(마지막 성분이 그 사이 링크로 바뀌거나 FIFO 면 막힌다)
- 읽기는 상한까지, 바이너리(NUL 또는 UTF-8 아님)는 `binary_file`
"""

from __future__ import annotations

import codecs
import os
import re
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neos.coding.domain.approvals import is_denied_secret_path

RISK = "read_only"
TOOL_NAMES = ("list_dir", "stat", "read_file")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_BINARY_SNIFF = 8192


class BridgeToolError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _kind(mode: int) -> str:
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "dir"
    if stat.S_ISREG(mode):
        return "file"
    return "other"


class LocalReadOnlyTools:
    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        max_read_bytes: int = 262_144,
        max_list_entries: int = 500,
    ) -> None:
        resolved = Path(os.path.realpath(os.path.expanduser(os.fspath(root))))
        if not resolved.is_dir():
            raise ValueError("the bridge root must be an existing directory")
        if resolved == Path(resolved.anchor):
            raise ValueError("refusing to share the filesystem root")
        try:
            home = Path(os.path.realpath(Path.home()))
        except RuntimeError:
            home = None
        if home is not None and resolved == home:
            raise ValueError("refusing to share the whole home folder; pick a subfolder")
        if max_read_bytes < 1 or max_list_entries < 1:
            raise ValueError("limits must be positive")
        self.root = resolved
        self._max_read = max_read_bytes
        self._max_entries = max_list_entries

    def declaration(self) -> list[dict[str, str]]:
        return [{"name": name, "risk": RISK} for name in TOOL_NAMES]

    def call(self, tool: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if tool == "list_dir":
            return self.list_dir(args.get("path", "."), max_entries=args.get("max_entries"))
        if tool == "stat":
            return self.stat(args.get("path"))
        if tool == "read_file":
            return self.read_file(args.get("path"), max_bytes=args.get("max_bytes"))
        raise BridgeToolError("unknown_tool")

    # -- 경로 ------------------------------------------------------------------------

    def resolve(self, raw: object) -> tuple[str, Path]:
        if not isinstance(raw, str) or "\0" in raw:
            raise BridgeToolError("path_escape")
        text = raw.replace("\\", "/")
        if text.startswith("/") or text.startswith("~") or _DRIVE_RE.match(text):
            raise BridgeToolError("path_escape")
        parts = [part for part in text.split("/") if part not in {"", "."}]
        if any(part == ".." for part in parts):
            raise BridgeToolError("path_escape")
        relative = "/".join(parts) or "."
        if is_denied_secret_path(relative):
            raise BridgeToolError("secret_path")
        real = Path(os.path.realpath(self.root.joinpath(*parts)))
        if real != self.root and self.root not in real.parents:
            raise BridgeToolError("path_escape")
        real_relative = real.relative_to(self.root).as_posix()
        if is_denied_secret_path(real_relative):
            raise BridgeToolError("secret_path")
        return relative, real

    @staticmethod
    def _cap(requested: object, ceiling: int) -> int:
        if isinstance(requested, int) and not isinstance(requested, bool) and requested > 0:
            return min(requested, ceiling)
        return ceiling

    # -- 도구 ------------------------------------------------------------------------

    def list_dir(self, path: object = ".", *, max_entries: object = None) -> dict[str, Any]:
        relative, real = self.resolve(path)
        cap = self._cap(max_entries, self._max_entries)
        try:
            with os.scandir(real) as iterator:
                items = sorted(iterator, key=lambda entry: entry.name)
        except FileNotFoundError as error:
            raise BridgeToolError("not_found") from error
        except NotADirectoryError as error:
            raise BridgeToolError("not_a_directory") from error
        except PermissionError as error:
            raise BridgeToolError("permission_denied") from error
        entries: list[dict[str, Any]] = []
        truncated = False
        for item in items:
            child = item.name if relative == "." else f"{relative}/{item.name}"
            if is_denied_secret_path(child):
                continue  # 비밀 경로는 있는지도 말하지 않는다
            if len(entries) >= cap:
                truncated = True
                break
            try:
                info = item.stat(follow_symlinks=False)
            except OSError:
                continue
            kind = _kind(info.st_mode)
            entries.append(
                {"name": item.name, "type": kind, "size": info.st_size if kind == "file" else None}
            )
        return {"entries": entries, "truncated": truncated}

    def stat(self, path: object) -> dict[str, Any]:
        _relative, real = self.resolve(path)
        try:
            info = os.stat(real)
        except FileNotFoundError as error:
            raise BridgeToolError("not_found") from error
        except PermissionError as error:
            raise BridgeToolError("permission_denied") from error
        kind = _kind(info.st_mode)
        return {
            "type": kind,
            "size": info.st_size if kind == "file" else None,
            "mtime": datetime.fromtimestamp(info.st_mtime, UTC).isoformat(),
        }

    def read_file(self, path: object, *, max_bytes: object = None) -> dict[str, Any]:
        _relative, real = self.resolve(path)
        cap = self._cap(max_bytes, self._max_read)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(real, flags)
        except FileNotFoundError as error:
            raise BridgeToolError("not_found") from error
        except PermissionError as error:
            raise BridgeToolError("permission_denied") from error
        except IsADirectoryError as error:
            raise BridgeToolError("not_a_file") from error
        except OSError as error:  # ELOOP: 마지막 성분이 링크로 바뀌었다
            raise BridgeToolError("path_escape") from error
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise BridgeToolError("not_a_file")
            chunks: list[bytes] = []
            remaining = cap
            while remaining > 0:
                chunk = os.read(fd, min(remaining, 65_536))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        finally:
            os.close(fd)
        data = b"".join(chunks)
        truncated = info.st_size > len(data)
        if b"\x00" in data[:_BINARY_SNIFF]:
            raise BridgeToolError("binary_file")
        try:
            # 잘린 끝에 걸친 멀티바이트 문자는 버린다(final=False) -- 바이너리로 오판하지 않게.
            text = codecs.getincrementaldecoder("utf-8")().decode(data, final=not truncated)
        except UnicodeDecodeError as error:
            raise BridgeToolError("binary_file") from error
        return {"text": text, "truncated": truncated, "size": info.st_size}


__all__ = ["BridgeToolError", "LocalReadOnlyTools", "RISK", "TOOL_NAMES"]

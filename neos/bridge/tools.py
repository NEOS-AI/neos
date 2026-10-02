"""브리지의 로컬 도구 -- 트랙 Q16a · Q16b. 아무것도 실행하지 않는다.

`LocalReadOnlyTools` 는 READ_ONLY 셋이다. 사용자가 `--allow-writes` 를 고르면
`LocalWritableTools` 가 `write_file` 하나를 더한다(경계는 그 클래스의 독스트링).

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
import contextlib
import errno
import hashlib
import os
import re
import secrets
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


# -- 쓰기 (트랙 Q16b) --------------------------------------------------------------------

WRITE_RISK = "workspace_write"
WRITE_TOOL_NAMES = ("write_file",)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TEMP_PREFIX = ".neos-bridge-"
_EXEC_BITS = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


def _digest_fd(fd: int) -> str:
    hasher = hashlib.sha256()
    while True:
        chunk = os.read(fd, 65_536)
        if not chunk:
            return hasher.hexdigest()
        hasher.update(chunk)


class LocalWritableTools(LocalReadOnlyTools):
    """읽기 셋에 `write_file` 하나를 더한다. 사용자가 `--allow-writes` 로 고른 경우에만 만든다.

    경계(BW5 ~ BW7):

    - 경로 규칙은 서버와 **같은 함수**(`device_write_refusal`) -- dot 성분 · 자동 실행 확장자 · 비밀 경로
    - 링크가 하나도 없는 경로만: 루트부터 성분마다 `O_NOFOLLOW|O_DIRECTORY` 로 디렉터리 fd 를 잡고,
      마지막 성분은 그 fd 안에서 다룬다(중간 디렉터리 바꿔치기 경쟁이 닫힌다). 부모는 있어야 한다
    - 덮기는 `base_sha256` 이 지금 파일의 다이제스트와 같아야 한다. 없는 파일은 `base_sha256` 이 없어야 한다
    - 같은 폴더 임시 파일 -> fsync -> 덮기는 rename, 새로 만들기는 link(있으면 실패). 실패하면 임시 파일을 지운다
    - 실행 비트를 세우지 않는다(새 파일은 0644 & ~umask). 실행 비트가 선 파일은 덮지 않는다
    - 텍스트만, 상한까지
    """

    def __init__(self, root, *, max_write_bytes: int = 262_144, **kwargs: Any) -> None:
        super().__init__(root, **kwargs)
        if max_write_bytes < 1:
            raise ValueError("limits must be positive")
        if os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd:
            raise ValueError("device writes need a POSIX system (openat)")
        self._max_write = max_write_bytes

    def declaration(self) -> list[dict[str, str]]:
        writes = [{"name": name, "risk": WRITE_RISK} for name in WRITE_TOOL_NAMES]
        return super().declaration() + writes

    def call(self, tool: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if tool == "write_file":
            return self.write_file(
                args.get("path"),
                args.get("content"),
                base_sha256=args.get("base_sha256"),
                max_bytes=args.get("max_bytes"),
            )
        return super().call(tool, args)

    def read_file(self, path: object, *, max_bytes: object = None) -> dict[str, Any]:
        """온전히 읽었으면 다이제스트를 싣는다 -- 덮어쓰기의 열쇠다(잘린 읽기에는 없다).

        엄격한 UTF-8 디코드를 다시 인코드하면 원래 바이트와 같다.
        """
        result = super().read_file(path, max_bytes=max_bytes)
        if not result["truncated"]:
            result["sha256"] = hashlib.sha256(result["text"].encode("utf-8")).hexdigest()
        return result

    def _open_parent(self, parts: list[str]) -> int:
        """루트부터 링크를 따라가지 않고 부모 디렉터리 fd 를 잡는다."""
        fd = os.open(self.root, _DIR_FLAGS)
        try:
            for part in parts:
                try:
                    info = os.stat(part, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError as error:
                    raise BridgeToolError("not_found") from error
                if stat.S_ISLNK(info.st_mode):
                    raise BridgeToolError("path_escape")
                if not stat.S_ISDIR(info.st_mode):
                    raise BridgeToolError("not_a_directory")
                try:
                    child = os.open(part, _DIR_FLAGS, dir_fd=fd)
                except OSError as error:  # 확인과 열기 사이에 링크로 바뀌었다
                    raise BridgeToolError("path_escape") from error
                os.close(fd)
                fd = child
            return fd
        except BaseException:
            os.close(fd)
            raise

    def write_file(
        self,
        path: object,
        content: object,
        *,
        base_sha256: object = None,
        max_bytes: object = None,
    ) -> dict[str, Any]:
        from neos.coding.bridge.write_policy import device_write_refusal

        relative, _real = self.resolve(path)
        refusal = device_write_refusal(relative)
        if refusal is not None:
            raise BridgeToolError(refusal)
        if base_sha256 is not None and not (
            isinstance(base_sha256, str) and _SHA256_RE.fullmatch(base_sha256)
        ):
            raise BridgeToolError("stale_read")
        if not isinstance(content, str) or "\0" in content:
            raise BridgeToolError("binary_file")
        payload = content.encode("utf-8")
        if len(payload) > self._cap(max_bytes, self._max_write):
            raise BridgeToolError("too_large")
        *parents, name = relative.split("/")
        parent = self._open_parent(parents)
        try:
            return self._write_in(parent, name, payload, base_sha256)
        finally:
            os.close(parent)

    def _write_in(
        self, parent: int, name: str, payload: bytes, base: str | None
    ) -> dict[str, Any]:
        try:
            existing = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if stat.S_ISLNK(existing.st_mode):
                raise BridgeToolError("path_escape")
            if not stat.S_ISREG(existing.st_mode):
                raise BridgeToolError("not_a_file")
            if existing.st_mode & _EXEC_BITS:
                raise BridgeToolError("executable_file")
            if base is None:
                raise BridgeToolError("read_required")
            if _current_digest(parent, name) != base:
                raise BridgeToolError("stale_read")
        elif base is not None:
            raise BridgeToolError("stale_read")  # 읽은 뒤 사라졌다
        temp = f"{_TEMP_PREFIX}{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        # 새 파일은 0644 & ~umask(커널이 적용한다). 덮을 때는 원래 권한에서 실행 비트를 뺀 값.
        fd = os.open(temp, flags, 0o644 if existing is None else 0o600, dir_fd=parent)
        committed = False
        try:
            try:
                if existing is not None:
                    os.fchmod(fd, stat.S_IMODE(existing.st_mode) & ~_EXEC_BITS)
                view = memoryview(payload)
                while view:
                    view = view[os.write(fd, view) :]
                os.fsync(fd)
            finally:
                os.close(fd)
            if existing is not None:
                # 검사와 교체 사이를 좁힌다 -- 한 번 더 본다(남는 경쟁은 위협 모델 §4).
                if _current_digest(parent, name) != base:
                    raise BridgeToolError("stale_read")
                os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
            else:
                try:
                    os.link(
                        temp, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False
                    )
                except FileExistsError as error:
                    raise BridgeToolError("stale_read") from error
            committed = True
        except OSError as error:
            if error.errno == errno.ENOSPC:
                raise BridgeToolError("no_space") from error
            raise BridgeToolError("permission_denied") from error
        finally:
            if not committed or existing is None:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(temp, dir_fd=parent)
        with contextlib.suppress(OSError):
            os.fsync(parent)
        return {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
            "created": existing is None,
        }


def _current_digest(parent: int, name: str) -> str:
    try:
        fd = os.open(name, _FILE_FLAGS, dir_fd=parent)
    except FileNotFoundError as error:
        raise BridgeToolError("stale_read") from error
    except OSError as error:  # 그 사이 링크로 바뀌었다
        raise BridgeToolError("path_escape") from error
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise BridgeToolError("not_a_file")
        return _digest_fd(fd)
    finally:
        os.close(fd)


__all__ = [
    "BridgeToolError",
    "LocalReadOnlyTools",
    "LocalWritableTools",
    "RISK",
    "TOOL_NAMES",
    "WRITE_RISK",
    "WRITE_TOOL_NAMES",
]

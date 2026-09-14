"""neos-sandboxd -- the immutable guest daemon for managed coding sandboxes.

This module is **stdlib only** and self-contained so it can be baked into a
sandbox image as one file and pinned by digest (`bundle_digest()`). It must
never download or update itself; the host refuses to open a session when the
handshake's protocol version, bundle digest, or capabilities differ from what
it expects (docs/MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md §8.1).

Wire format: a frame is a 4-byte big-endian length followed by a UTF-8 JSON
object. Requests are ``{"v": 1, "id": n, "op": "...", "args": {...}}``;
responses are ``{"v": 1, "id": n, "ok": true, "result": {...}}`` or
``{"v": 1, "id": n, "ok": false, "error": {"kind": "...", "code": "..."}}``.
Binary payloads travel base64-encoded. The first request on a connection must
be ``hello``.

Commands are argv arrays, never shell strings. Workspace paths are relative,
normalized, and resolved component by component with ``O_NOFOLLOW`` directory
fds, so a symlink planted by a command cannot redirect a file operation outside
the workspace. The daemon owns the monotonic workspace revision;
``write_file`` with ``expected_revision`` is an atomic compare-and-replace
under the workspace lock.

Modes:
  serve   --workspace W --state-dir S --socket P   long-lived; journals survive
                                                  reconnects
  stdio   --workspace W --state-dir S              one connection on stdin/stdout
  connect --socket P                               relay stdin/stdout to ``serve``
  digest                                           print the bundle digest

The semantics of paths, ignore rules, search, and glob follow
`neos/coding/sandbox/paths.py`, `ignore.py`, and `memory.py`; the tests in
`tests/coding/sandbox/test_sandboxd.py` hold them together.
"""

from __future__ import annotations

import argparse
import base64
import errno
import fcntl
import hashlib
import json
import os
import pty
import re
import select
import shutil
import signal
import socket
import stat as stat_mod
import struct
import subprocess
import sys
import termios
import threading
import time
import unicodedata
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import PurePosixPath

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 16 * 1024 * 1024
CAPABILITIES = (
    "checksum.v1",
    "exec.v1",
    "files.cas.v1",
    "files.v1",
    "pty.v1",
    "search.v1",
    "watch.v1",
)

GUEST_PATH = "/usr/bin:/bin"
GUEST_LANG = "C.UTF-8"
RESERVED_ENV = frozenset({"PATH", "HOME", "TMPDIR"})
TERMINATE_GRACE_SEC = 0.5
MAX_TIMEOUT_SEC = 3600.0
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_STDIN_BYTES = 64 * 1024 * 1024
MAX_TREE_ENTRIES = 20_000
MAX_PTYS = 8
MAX_READ_EVENTS = 256
MAX_WAIT_SEC = 5.0
JOURNAL_EVENTS = 1024
JOURNAL_BYTES = 1024 * 1024
DEFAULT_SEARCH_CAP_BYTES = 1024 * 1024

_HEADER = struct.Struct(">I")
_SHELLS = frozenset({"sh", "bash", "zsh"})
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | _CLOEXEC
_PROTECTED_GIT_FILES = frozenset(
    {".git/config", ".git/config.worktree", ".git/credentials"}
)
_BARE_GIT_ROOT_PARTS = frozenset({"HEAD", "objects", "refs", "hooks"})
_SECRET_NAMES = frozenset(
    {
        "id_rsa",
        "id_ed25519",
        ".envrc",
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".pgpass",
        ".git-credentials",
    }
)
DEFAULT_SKIP_DIRS = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        ".bzr",
        ".jj",
        ".sl",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
    }
)


def bundle_digest(path: str | None = None) -> str:
    """The digest the host pins. Computed over this module's exact bytes."""
    with open(path or __file__, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


# ---- framing -----------------------------------------------------------------


class FrameError(Exception):
    """A frame is oversized or not a JSON object."""


def encode_frame(message: dict) -> bytes:
    payload = json.dumps(
        message, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    if len(payload) > MAX_FRAME_BYTES:
        raise FrameError("frame_too_large")
    return _HEADER.pack(len(payload)) + payload


def frame_length(header: bytes) -> int:
    (size,) = _HEADER.unpack(header)
    if size > MAX_FRAME_BYTES:
        raise FrameError("frame_too_large")
    return size


def decode_payload(payload: bytes) -> dict:
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise FrameError("frame_invalid") from error
    if not isinstance(message, dict):
        raise FrameError("frame_invalid")
    return message


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(value: object) -> bytes:
    if not isinstance(value, str):
        raise GuestError("policy", "request_invalid")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as error:
        raise GuestError("policy", "request_invalid") from error


# ---- errors and path policy ---------------------------------------------------


class GuestError(Exception):
    """A sanitized failure: the host sees only ``kind`` and ``code``."""

    def __init__(self, kind: str, code: str) -> None:
        super().__init__(code)
        self.kind = kind
        self.code = code


def _policy(code: str) -> GuestError:
    return GuestError("policy", code)


def normalize(path: object) -> tuple[str, ...]:
    if not isinstance(path, str):
        raise _policy("workspace_path_invalid")
    if "\0" in path:
        raise _policy("workspace_path_contains_nul")
    if path.startswith("/"):
        raise _policy("workspace_path_is_absolute")
    parts = PurePosixPath(path or ".").parts
    if any(part == ".." for part in parts):
        raise _policy("workspace_path_escape")
    return tuple(part for part in parts if part not in {".", ""})


def is_secret(rel_path: str) -> bool:
    """Same rule as `neos.coding.domain.approvals.is_denied_secret_path`."""
    parts = tuple(
        part
        for part in rel_path.replace("\\", "/").split("/")
        if part not in {"", "."}
    )
    if not parts:
        return False
    folded = tuple(unicodedata.normalize("NFKC", part).casefold() for part in parts)
    name = folded[-1]
    if name == ".env" or name.startswith(".env."):
        return True
    if ".git" in folded or ".ssh" in folded:
        return True
    if name in _SECRET_NAMES:
        return True
    if any(
        part == ".neos" and folded[index + 1] == "secrets"
        for index, part in enumerate(folded[:-1])
    ):
        return True
    return any(
        part == ".aws" and folded[index + 1] == "credentials"
        for index, part in enumerate(folded[:-1])
    )


def ensure_mutable(parts: tuple[str, ...]) -> None:
    if not parts:
        raise _policy("workspace_path_is_root")
    rel = "/".join(parts)
    if rel in _PROTECTED_GIT_FILES or parts[:2] == (".git", "hooks"):
        raise _policy("protected_git_path")
    if parts[0] in _BARE_GIT_ROOT_PARTS:
        raise _policy("workspace_bare_git_path")


# ---- ignore rules (same semantics as neos/coding/sandbox/ignore.py) ----------


def posix_parts(path: str) -> tuple[str, ...]:
    return tuple(
        part for part in path.replace("\\", "/").split("/") if part not in {"", "."}
    )


def _glob_to_regex(pat: str) -> str:
    index = 0
    size = len(pat)
    out: list[str] = []
    while index < size:
        char = pat[index]
        if char == "*":
            if index + 1 < size and pat[index + 1] == "*":
                index += 2
                if index < size and pat[index] == "/":
                    out.append("(?:.*/)?")
                    index += 1
                else:
                    out.append(".*")
            else:
                out.append("[^/]*")
                index += 1
        elif char == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(char))
            index += 1
    return "".join(out)


def _relative_to_base(rel_path: str, base: str) -> str | None:
    rel = "/".join(posix_parts(rel_path))
    if not base:
        return rel
    base_n = "/".join(posix_parts(base))
    if not base_n:
        return rel
    if rel == base_n:
        return ""
    prefix = base_n + "/"
    if not rel.startswith(prefix):
        return None
    return rel[len(prefix) :]


def _match_one(candidate: str, pat: str, anchored: bool) -> bool:
    regex = _glob_to_regex(pat)
    if anchored:
        return re.fullmatch(regex, candidate) is not None
    return re.fullmatch("(?:.*/)?" + regex, candidate) is not None


def match_ignore_pattern(
    rel_path: str, pattern: str, base: str = "", is_dir: bool | None = None
) -> bool:
    pat = pattern.strip()
    if not pat:
        return False
    directory_only = pat.endswith("/")
    leading_slash = pat.startswith("/")
    if leading_slash:
        pat = pat[1:]
    if directory_only:
        pat = pat[:-1]
    if not pat:
        return False
    local = _relative_to_base(rel_path, base)
    if local is None or local == "":
        return False
    anchored = leading_slash or ("/" in pat)
    parts = posix_parts(local)
    for depth in range(1, len(parts) + 1):
        candidate = "/".join(parts[:depth])
        is_last = depth == len(parts)
        if not _match_one(candidate, pat, anchored):
            continue
        if directory_only and is_last and is_dir is False:
            continue
        return True
    return False


def ignored_by_rules(rel_path: str, rules, is_dir: bool | None = None) -> bool:
    ignored = False
    for base, raw in rules:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        pat = line[1:] if negated else line
        if match_ignore_pattern(rel_path, pat, base=base, is_dir=is_dir):
            ignored = not negated
    return ignored


def load_ignore_rules(workspace: str) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    if not os.path.isdir(workspace):
        return rules
    for dirpath, dirnames, _filenames in os.walk(workspace, followlinks=False):
        kept = []
        for name in dirnames:
            if os.path.islink(os.path.join(dirpath, name)) or name in DEFAULT_SKIP_DIRS:
                continue
            kept.append(name)
        dirnames[:] = kept
        rel_dir = os.path.relpath(dirpath, workspace).replace(os.sep, "/")
        base = "" if rel_dir == "." else rel_dir
        for name in (".gitignore", ".ignore"):
            candidate = os.path.join(dirpath, name)
            try:
                if os.path.islink(candidate) or not os.path.isfile(candidate):
                    continue
                with open(candidate, encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
            except OSError:
                continue
            for raw in text.splitlines():
                line = raw.strip()
                if line and not line.startswith("#"):
                    rules.append((base, line))
    return rules


def should_skip_walk(rel_path: str, rules, is_dir: bool | None = None) -> bool:
    """Same rule as `neos.coding.sandbox.ignore.should_skip_walk`."""
    if not rel_path:
        return False
    if is_secret(rel_path):
        return True
    parts = posix_parts(rel_path)
    if any(part in DEFAULT_SKIP_DIRS for part in parts):
        return True
    if ".git" in parts:
        return True
    return ignored_by_rules(rel_path, rules, is_dir=is_dir)


def _matches_path(path: str, pattern: str) -> bool:
    normalized = "/".join(normalize(pattern)) or "."
    if normalized.endswith("/**"):
        return path.startswith(normalized[:-3].rstrip("/") + "/")
    return PurePosixPath(path).match(normalized) or (
        normalized.startswith("**/") and PurePosixPath(path).match(normalized[3:])
    )


def _ignore_watch_path(path: str) -> bool:
    name = PurePosixPath(path).name
    return (
        path == ".git"
        or path.startswith(".git/")
        or name == ".DS_Store"
        or name.endswith((".swp", ".swo", "~"))
    )


# ---- bounded journals (PTY output, watcher batches) ---------------------------


class Journal:
    """Cursor-addressed bounded event log. An evicted cursor is a gap."""

    def __init__(self, max_events: int, max_bytes: int) -> None:
        self._max_events = max_events
        self._max_bytes = max_bytes
        self._events: deque[tuple[int, int, dict]] = deque()
        self._bytes = 0
        self._cursor = 0
        self._evicted_through = 0
        self._closed = False
        self._condition = threading.Condition()

    def append(self, payload: dict, size: int) -> int:
        with self._condition:
            if self._closed:
                return self._cursor
            self._cursor += 1
            self._events.append((self._cursor, size, payload))
            self._bytes += size
            while self._events and (
                len(self._events) > self._max_events or self._bytes > self._max_bytes
            ):
                cursor, evicted_size, _payload = self._events.popleft()
                self._bytes -= evicted_size
                self._evicted_through = cursor
            self._condition.notify_all()
            return self._cursor

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def read(
        self, after_cursor: int, *, max_events: int, wait_sec: float
    ) -> tuple[list[dict], bool]:
        with self._condition:
            self._check(after_cursor)
            if wait_sec > 0 and not self._closed and after_cursor >= self._cursor:
                self._condition.wait(wait_sec)
                self._check(after_cursor)
            events = [
                {"cursor": cursor, **payload}
                for cursor, _size, payload in self._events
                if cursor > after_cursor
            ][:max_events]
            drained = not events or events[-1]["cursor"] == self._cursor
            return events, self._closed and drained

    def _check(self, after_cursor: int) -> None:
        if after_cursor < 0:
            raise _policy("stream_cursor_is_negative")
        if after_cursor > self._cursor:
            raise _policy("stream_cursor_is_ahead")
        if after_cursor < self._evicted_through:
            raise GuestError("gap", "replay_gap")


# ---- processes ---------------------------------------------------------------


def _signal_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _terminate_group(process: subprocess.Popen) -> None:
    """SIGTERM the whole group, then SIGKILL it -- descendants included."""
    _signal_group(process.pid, signal.SIGTERM)
    try:
        process.wait(TERMINATE_GRACE_SEC)
    except subprocess.TimeoutExpired:
        pass
    _signal_group(process.pid, signal.SIGKILL)
    process.wait()


class _CappedReader(threading.Thread):
    def __init__(self, fd: int, cap: int, overflow: threading.Event) -> None:
        super().__init__(daemon=True)
        self._fd = fd
        self._cap = cap
        self._overflow = overflow
        # Not `_stop`: that name is an internal `threading.Thread` method.
        self._halt = threading.Event()
        self.data = bytearray()
        self.truncated = False

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                ready, _, _ = select.select([self._fd], [], [], 0.1)
            except (OSError, ValueError):
                return
            if not ready:
                continue
            try:
                chunk = os.read(self._fd, 65536)
            except OSError:
                return
            if not chunk:
                return
            room = self._cap - len(self.data)
            if len(chunk) > room:
                self.data.extend(chunk[: max(room, 0)])
                self.truncated = True
                self._overflow.set()
                return
            self.data.extend(chunk)


def guest_env(workspace: str, tmp_dir: str, overlay: dict | None = None) -> dict:
    """Built from constants. The daemon's own environment is never inherited."""
    environment = {
        "PATH": GUEST_PATH,
        "HOME": workspace,
        "TMPDIR": tmp_dir,
        "LANG": GUEST_LANG,
        "LC_ALL": GUEST_LANG,
    }
    for key, value in (overlay or {}).items():
        if key not in RESERVED_ENV:
            environment[key] = value
    return environment


def _validate_argv(argv: object) -> list[str]:
    if not isinstance(argv, list) or not argv:
        raise _policy("command_argv_empty")
    if not all(isinstance(value, str) for value in argv):
        raise _policy("request_invalid")
    if any("\0" in value for value in argv):
        raise _policy("command_argv_contains_nul")
    executable = argv[0].rsplit("/", 1)[-1]
    if executable in _SHELLS and len(argv) > 1 and argv[1] == "-c":
        raise _policy("shell_command_not_allowed")
    return argv


def _validate_env(env: object) -> dict:
    if env is None:
        return {}
    if not isinstance(env, dict):
        raise _policy("request_invalid")
    for key, value in env.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise _policy("request_invalid")
        if _ENV_NAME.match(key) is None or "\0" in value:
            raise _policy("command_environment_invalid")
    return env


# ---- PTY ---------------------------------------------------------------------


class GuestPty:
    def __init__(self, pty_id: str, argv: list[str], cwd: str, env: dict) -> None:
        self.pty_id = pty_id
        self.journal = Journal(JOURNAL_EVENTS, JOURNAL_BYTES)
        self._reason: str | None = None
        master, slave = pty.openpty()
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        try:
            self._process = subprocess.Popen(
                argv,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=cwd,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        self._master = master
        self._done = threading.Event()
        threading.Thread(target=self._read_loop, daemon=True).start()

    @property
    def closed(self) -> bool:
        return self._done.is_set()

    def _read_loop(self) -> None:
        try:
            while True:
                try:
                    ready, _, _ = select.select([self._master], [], [], 0.2)
                except (OSError, ValueError):
                    break
                if not ready:
                    if self._process.poll() is not None:
                        break
                    continue
                try:
                    data = os.read(self._master, 65536)
                except OSError:
                    break
                if not data:
                    break
                self.journal.append({"kind": "output", "data": _b64(data)}, len(data))
        finally:
            if self._process.poll() is None:
                _terminate_group(self._process)
            else:
                _signal_group(self._process.pid, signal.SIGKILL)
            reason = self._reason or "process_exited"
            exit_code = None if self._reason else self._process.returncode
            self.journal.append(
                {"kind": "closed", "reason": reason, "exit_code": exit_code}, 32
            )
            self.journal.close()
            try:
                os.close(self._master)
            except OSError:
                pass
            self._done.set()

    def write(self, data: bytes) -> None:
        if self.closed:
            raise GuestError("conflict", "pty_closed")
        view = memoryview(data)
        while view:
            written = os.write(self._master, view)
            view = view[written:]

    def resize(self, rows: int, cols: int) -> None:
        if rows < 1 or cols < 1 or rows > 1000 or cols > 1000:
            raise _policy("pty_size_invalid")
        if self.closed:
            raise GuestError("conflict", "pty_closed")
        fcntl.ioctl(self._master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def kill(self, reason: str) -> None:
        if self.closed:
            return
        self._reason = reason
        _terminate_group(self._process)
        self._done.wait(5)


# ---- workspace ---------------------------------------------------------------


def _entry(path: str, info: os.stat_result) -> dict:
    if stat_mod.S_ISLNK(info.st_mode):
        kind = "symlink"
    elif stat_mod.S_ISDIR(info.st_mode):
        kind = "directory"
    else:
        kind = "file"
    return {
        "path": path,
        "kind": kind,
        "size": info.st_size,
        "modified_at": datetime.fromtimestamp(info.st_mtime, tz=timezone.utc).isoformat(),
    }


def _clip(line: str, max_columns: int) -> str:
    if max_columns <= 0:
        return line
    encoded = line.encode("utf-8")
    if len(encoded) <= max_columns:
        return line
    return encoded[:max_columns].decode("utf-8", errors="ignore")


class Workspace:
    def __init__(self, root: str, state_dir: str) -> None:
        self.root = os.path.realpath(root)
        self.state_dir = os.path.realpath(state_dir)
        self.tmp_dir = os.path.join(self.state_dir, "tmp")
        os.makedirs(self.root, exist_ok=True)
        os.makedirs(self.tmp_dir, mode=0o700, exist_ok=True)
        self.lock = threading.RLock()
        self.watch = Journal(JOURNAL_EVENTS, JOURNAL_BYTES)
        self.revision = self._load_revision()
        self._ptys: dict[str, GuestPty] = {}
        self._pty_lock = threading.Lock()
        self._pty_seq = 0
        self._processes: set[subprocess.Popen] = set()

    # -- revision --

    def _revision_path(self) -> str:
        return os.path.join(self.state_dir, "revision")

    def _load_revision(self) -> int:
        try:
            with open(self._revision_path(), encoding="ascii") as handle:
                return max(0, int(handle.read().strip() or "0"))
        except (OSError, ValueError):
            return 0

    def _persist_revision(self) -> None:
        temporary = self._revision_path() + ".tmp"
        with open(temporary, "w", encoding="ascii") as handle:
            handle.write(str(self.revision))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self._revision_path())

    def bump(self, changes: list[dict]) -> int:
        with self.lock:
            self.revision += 1
            self._persist_revision()
            size = sum(len(change["path"].encode("utf-8")) + 32 for change in changes)
            self.watch.append({"revision": self.revision, "changes": changes}, size)
            return self.revision

    # -- fd-based resolution --

    def _open_dir_at(self, parent_fd: int, name: str) -> int:
        try:
            return os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            raise
        except OSError:
            try:
                info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                raise
            except OSError as error:
                raise _policy("workspace_path_not_resolvable") from error
            if stat_mod.S_ISLNK(info.st_mode):
                raise _policy("workspace_symlink_parent") from None
            raise _policy("workspace_path_not_resolvable") from None

    @contextmanager
    def directory(self, parts: tuple[str, ...], *, create: bool = False):
        """Yield an fd for ``parts`` as a directory; no symlink component."""
        fd = os.open(self.root, _DIR_FLAGS)
        try:
            for part in parts:
                try:
                    child = self._open_dir_at(fd, part)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(part, 0o755, dir_fd=fd)
                    except FileExistsError:
                        pass
                    child = self._open_dir_at(fd, part)
                os.close(fd)
                fd = child
            yield fd
        finally:
            os.close(fd)

    def parent(self, parts: tuple[str, ...], *, create: bool = False):
        return self.directory(parts[:-1], create=create)

    def _lstat_at(self, dir_fd: int, name: str) -> os.stat_result | None:
        try:
            return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None

    def _open_leaf_nofollow(self, dir_fd: int, name: str) -> int:
        try:
            return os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC, dir_fd=dir_fd
            )
        except FileNotFoundError:
            raise
        except OSError as error:
            if error.errno in {errno.ELOOP, errno.EMLINK}:
                raise _policy("workspace_symlink_leaf") from None
            raise _policy("workspace_path_not_resolvable") from None

    def _open_regular(self, dir_fd: int, name: str) -> int:
        fd = self._open_leaf_nofollow(dir_fd, name)
        info = os.fstat(fd)
        if not stat_mod.S_ISREG(info.st_mode):
            os.close(fd)
            raise _policy("workspace_path_is_not_file")
        if info.st_nlink > 1:
            os.close(fd)
            raise _policy("workspace_hardlink")
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
        return fd

    def real_dir(self, parts: tuple[str, ...]) -> str:
        with self.directory(parts):
            pass
        return os.path.join(self.root, *parts)

    # -- file operations --

    def op_revision(self, _args: dict) -> dict:
        return {"revision": self.revision}

    def op_stat(self, args: dict) -> dict:
        parts = normalize(args.get("path"))
        rel = "/".join(parts)
        if rel and is_secret(rel):
            raise _policy("workspace_secret_path")
        if not parts:
            return {"entry": _entry(".", os.stat(self.root))}
        try:
            with self.parent(parts) as dir_fd:
                info = self._lstat_at(dir_fd, parts[-1])
        except FileNotFoundError as error:
            raise _policy("workspace_path_not_resolvable") from error
        if info is None:
            raise _policy("workspace_path_not_resolvable")
        if stat_mod.S_ISLNK(info.st_mode):
            raise _policy("workspace_symlink_leaf")
        return {"entry": _entry(rel, info)}

    def op_list_tree(self, args: dict) -> dict:
        parts = normalize(args.get("path", "."))
        if parts:
            try:
                with self.parent(parts) as dir_fd:
                    info = self._lstat_at(dir_fd, parts[-1])
            except FileNotFoundError as error:
                raise _policy("workspace_path_not_resolvable") from error
            if info is None:
                raise _policy("workspace_path_not_resolvable")
            if stat_mod.S_ISLNK(info.st_mode) or not stat_mod.S_ISDIR(info.st_mode):
                return {"entries": []}
        start = os.path.join(self.root, *parts)
        rules = load_ignore_rules(self.root)
        entries: list[dict] = []
        for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
            kept = []
            for name in dirnames:
                item = os.path.join(dirpath, name)
                relative = os.path.relpath(item, self.root).replace(os.sep, "/")
                if should_skip_walk(relative, rules, is_dir=True):
                    continue
                kept.append(name)
                entries.append(_entry(relative, os.lstat(item)))
            dirnames[:] = kept
            for name in filenames:
                item = os.path.join(dirpath, name)
                relative = os.path.relpath(item, self.root).replace(os.sep, "/")
                if should_skip_walk(relative, rules, is_dir=False):
                    continue
                entries.append(_entry(relative, os.lstat(item)))
            if len(entries) > MAX_TREE_ENTRIES:
                raise _policy("workspace_tree_limit_exceeded")
        entries.sort(key=lambda entry: entry["path"])
        return {"entries": entries}

    def op_read_file(self, args: dict) -> dict:
        parts = normalize(args.get("path"))
        rel = "/".join(parts)
        if rel and is_secret(rel):
            raise _policy("workspace_secret_path")
        offset = int(args.get("offset", 1))
        limit = args.get("limit")
        cap = int(args["max_bytes"])
        if offset < 1 or cap < 1 or (limit is not None and int(limit) < 1):
            raise _policy("invalid_read_request")
        if not parts:
            raise _policy("workspace_path_is_not_file")
        try:
            with self.parent(parts) as dir_fd:
                fd = self._open_regular(dir_fd, parts[-1])
        except FileNotFoundError as error:
            raise _policy("workspace_path_not_resolvable") from error
        with os.fdopen(fd, "rb") as handle:
            if limit is None:
                if os.fstat(handle.fileno()).st_size > cap:
                    raise _policy("file_read_limit_exceeded")
                data = handle.read(cap + 1)
                if len(data) > cap:
                    raise _policy("file_read_limit_exceeded")
            else:
                end = offset + int(limit) - 1
                chunks = []
                remaining = cap
                for index, line in enumerate(handle, start=1):
                    if index < offset:
                        continue
                    if index > end:
                        break
                    if len(line) >= remaining:
                        chunks.append(line[:remaining])
                        break
                    chunks.append(line)
                    remaining -= len(line)
                data = b"".join(chunks)
        return {"data": _b64(data)}

    def op_write_file(self, args: dict) -> dict:
        parts = normalize(args.get("path"))
        ensure_mutable(parts)
        rel = "/".join(parts)
        data = _unb64(args.get("data"))
        if len(data) > int(args["max_bytes"]):
            raise _policy("workspace_write_limit_exceeded")
        parents = bool(args.get("parents", True))
        expected = args.get("expected_revision")
        with self.lock:
            # CAS: the revision check and the replace happen under one lock, so
            # no other mutation (including a command's) can land in between.
            if expected is not None and int(expected) != self.revision:
                raise GuestError("conflict", "workspace_revision_conflict")
            try:
                with self.parent(parts, create=parents) as dir_fd:
                    existed = self._replace_at(dir_fd, parts[-1], data)
            except FileNotFoundError as error:
                raise GuestError("file_not_found", "workspace_parent_missing") from error
            revision = self.bump(
                [{"path": rel, "kind": "modified" if existed else "created"}]
            )
        return {"revision": revision}

    def _replace_at(self, dir_fd: int, name: str, data: bytes) -> bool:
        info = self._lstat_at(dir_fd, name)
        if info is not None and stat_mod.S_ISLNK(info.st_mode):
            raise _policy("workspace_symlink_leaf")
        if info is not None and stat_mod.S_ISDIR(info.st_mode):
            raise _policy("workspace_path_is_directory")
        mode = (
            stat_mod.S_IMODE(info.st_mode) & 0o777
            if info is not None and stat_mod.S_ISREG(info.st_mode)
            else 0o644
        )
        temporary = f".neos-write-{os.getpid()}-{threading.get_ident()}-{time.monotonic_ns()}"
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | _CLOEXEC,
            0o600,
            dir_fd=dir_fd,
        )
        try:
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view) :]
                os.fchmod(fd, mode)
                os.fsync(fd)
            finally:
                os.close(fd)
            # rename replaces the directory entry: a hardlinked target keeps
            # its other names untouched instead of being written through.
            os.replace(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=dir_fd)
            except OSError:
                pass
            raise
        return info is not None

    def op_mkdir(self, args: dict) -> dict:
        parts = normalize(args.get("path"))
        ensure_mutable(parts)
        rel = "/".join(parts)
        if is_secret(rel):
            raise _policy("workspace_secret_path")
        parents = bool(args.get("parents", False))
        with self.lock:
            try:
                with self.parent(parts, create=parents) as dir_fd:
                    try:
                        os.mkdir(parts[-1], 0o755, dir_fd=dir_fd)
                    except FileExistsError:
                        info = self._lstat_at(dir_fd, parts[-1])
                        if not parents or info is None or not stat_mod.S_ISDIR(info.st_mode):
                            raise _policy("workspace_path_exists") from None
            except FileNotFoundError as error:
                raise _policy("workspace_path_not_resolvable") from error
            revision = self.bump([{"path": rel, "kind": "created"}])
        return {"revision": revision}

    def op_rm(self, args: dict) -> dict:
        parts = normalize(args.get("path"))
        ensure_mutable(parts)
        rel = "/".join(parts)
        if is_secret(rel):
            raise _policy("workspace_secret_path")
        recursive = bool(args.get("recursive", False))
        with self.lock:
            try:
                with self.parent(parts) as dir_fd:
                    info = self._lstat_at(dir_fd, parts[-1])
                    if info is None:
                        raise _policy("workspace_path_not_resolvable")
                    if stat_mod.S_ISDIR(info.st_mode):
                        self._remove_dir_at(dir_fd, parts[-1], recursive=recursive)
                    else:
                        os.unlink(parts[-1], dir_fd=dir_fd)
            except FileNotFoundError as error:
                raise _policy("workspace_path_not_resolvable") from error
            revision = self.bump([{"path": rel, "kind": "deleted"}])
        return {"revision": revision}

    def _remove_dir_at(self, dir_fd: int, name: str, *, recursive: bool) -> None:
        if recursive:
            # dir_fd-based rmtree does not follow symlinks placed inside.
            shutil.rmtree(name, dir_fd=dir_fd)
            return
        try:
            os.rmdir(name, dir_fd=dir_fd)
        except OSError as error:
            if error.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                raise _policy("workspace_directory_not_empty") from None
            raise

    def op_mv(self, args: dict) -> dict:
        src = normalize(args.get("src"))
        dest = normalize(args.get("dest"))
        ensure_mutable(src)
        ensure_mutable(dest)
        if is_secret("/".join(src)) or is_secret("/".join(dest)):
            raise _policy("workspace_secret_path")
        overwrite = bool(args.get("overwrite", False))
        with self.lock:
            try:
                with self.parent(src) as src_fd, self.parent(dest) as dest_fd:
                    if self._lstat_at(src_fd, src[-1]) is None:
                        raise _policy("workspace_path_not_resolvable")
                    existing = self._lstat_at(dest_fd, dest[-1])
                    if existing is not None:
                        if not overwrite:
                            raise _policy("workspace_path_exists")
                        if stat_mod.S_ISDIR(existing.st_mode):
                            shutil.rmtree(dest[-1], dir_fd=dest_fd)
                        else:
                            os.unlink(dest[-1], dir_fd=dest_fd)
                    os.rename(src[-1], dest[-1], src_dir_fd=src_fd, dst_dir_fd=dest_fd)
            except FileNotFoundError as error:
                raise _policy("workspace_path_not_resolvable") from error
            revision = self.bump([{"path": "/".join(dest), "kind": "modified"}])
        return {"revision": revision}

    def op_chmod(self, args: dict) -> dict:
        parts = normalize(args.get("path"))
        ensure_mutable(parts)
        mode = int(args["mode"])
        if mode < 0 or mode > 0o7777:
            raise _policy("workspace_mode_invalid")
        if mode & 0o6000:
            raise _policy("workspace_mode_not_allowed")
        rel = "/".join(parts)
        if is_secret(rel) and mode & 0o002:
            raise _policy("workspace_secret_path")
        with self.lock:
            try:
                with self.parent(parts) as dir_fd:
                    fd = self._open_leaf_nofollow(dir_fd, parts[-1])
                    try:
                        info = os.fstat(fd)
                        if not stat_mod.S_ISDIR(info.st_mode) and info.st_nlink > 1:
                            raise _policy("workspace_hardlink")
                        if not (stat_mod.S_ISDIR(info.st_mode) or stat_mod.S_ISREG(info.st_mode)):
                            raise _policy("workspace_path_is_not_file")
                        os.fchmod(fd, mode)
                    finally:
                        os.close(fd)
            except FileNotFoundError as error:
                raise _policy("workspace_path_not_resolvable") from error
            revision = self.bump([{"path": rel, "kind": "modified"}])
        return {"revision": revision}

    # -- search --

    def _iter_files(self, start_parts: tuple[str, ...], rules):
        start = os.path.join(self.root, *start_parts)
        if os.path.islink(start):
            return
        if os.path.isfile(start):
            relative = "/".join(start_parts)
            if not should_skip_walk(relative, rules, is_dir=False):
                yield start, relative
            return
        if not os.path.isdir(start):
            return
        for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
            dirnames.sort()
            filenames.sort()
            kept = []
            for name in dirnames:
                item = os.path.join(dirpath, name)
                if os.path.islink(item):
                    continue
                relative = os.path.relpath(item, self.root).replace(os.sep, "/")
                if should_skip_walk(relative, rules, is_dir=True):
                    continue
                kept.append(name)
            dirnames[:] = kept
            for name in filenames:
                item = os.path.join(dirpath, name)
                if os.path.islink(item) or not os.path.isfile(item):
                    continue
                relative = os.path.relpath(item, self.root).replace(os.sep, "/")
                if should_skip_walk(relative, rules, is_dir=False):
                    continue
                yield item, relative

    def _search_start(self, path: object) -> tuple[str, ...]:
        if path is None:
            return ()
        parts = normalize(path)
        if parts:
            try:
                self.real_dir(parts[:-1])
            except FileNotFoundError as error:
                raise _policy("workspace_path_not_resolvable") from error
        return parts

    def op_search(self, args: dict) -> dict:
        query = args.get("query")
        limit = int(args.get("limit", 100))
        if not isinstance(query, str) or not query or limit < 1:
            raise _policy("invalid_search_request")
        output_mode = args.get("output_mode", "content")
        if output_mode not in {"files", "content", "count"}:
            output_mode = "content"
        before = max(0, min(int(args.get("before", 0)), 20))
        after = max(0, min(int(args.get("after", 0)), 20))
        max_columns = int(args.get("max_columns", 500))
        flags = 0
        if args.get("ignore_case"):
            flags |= re.IGNORECASE
        multiline = bool(args.get("multiline"))
        if multiline:
            flags |= re.DOTALL
        try:
            expression = re.compile(query if args.get("regex") else re.escape(query), flags)
        except re.error as error:
            raise _policy("invalid_search_request") from error
        patterns = [str(pattern) for pattern in args.get("paths") or ["**/*"]]
        excludes = [str(pattern) for pattern in args.get("exclude") or []]
        max_file_bytes = int(args.get("max_file_bytes", DEFAULT_SEARCH_CAP_BYTES))
        if max_file_bytes <= 0:
            max_file_bytes = DEFAULT_SEARCH_CAP_BYTES
        start = self._search_start(args.get("path"))
        rules = load_ignore_rules(self.root)
        matches: list[dict] = []

        def emit(relative, number, column, line, lines):
            first = max(0, number - 1 - before)
            matches.append(
                {
                    "path": relative,
                    "line": number,
                    "column": column,
                    "text": _clip(line, max_columns),
                    "before": [_clip(item, max_columns) for item in lines[first : number - 1]],
                    "after": [_clip(item, max_columns) for item in lines[number : number + after]],
                }
            )

        for item, relative in self._iter_files(start, rules):
            if not any(_matches_path(relative, pattern) for pattern in patterns):
                continue
            if excludes and any(_matches_path(relative, pattern) for pattern in excludes):
                continue
            text = self._read_search_text(item, max_file_bytes)
            if text is None:
                continue
            lines = text.splitlines()
            hits = 0
            if multiline:
                for match in expression.finditer(text):
                    hits += 1
                    if output_mode != "content":
                        continue
                    number = text.count("\n", 0, match.start()) + 1
                    line_start = text.rfind("\n", 0, match.start()) + 1
                    line_end = text.find("\n", match.start())
                    if line_end < 0:
                        line_end = len(text)
                    line = text[line_start:line_end].rstrip("\r")
                    emit(relative, number, match.start() - line_start + 1, line, lines)
                    if len(matches) >= limit:
                        return {"matches": matches}
            else:
                for number, line in enumerate(lines, start=1):
                    match = expression.search(line)
                    if match is None:
                        continue
                    hits += 1
                    if output_mode != "content":
                        continue
                    emit(relative, number, match.start() + 1, line, lines)
                    if len(matches) >= limit:
                        return {"matches": matches}
            if hits == 0 or output_mode == "content":
                continue
            entry = {"path": relative, "line": 0, "column": 0, "text": ""}
            if output_mode == "count":
                entry["count"] = hits
            matches.append(entry)
            if len(matches) >= limit:
                break
        return {"matches": matches}

    @staticmethod
    def _read_search_text(item: str, max_bytes: int) -> str | None:
        try:
            with open(item, "rb") as handle:
                if b"\0" in handle.read(8192):
                    return None
            if os.stat(item).st_size > max_bytes:
                return None
            with open(item, "rb") as handle:
                data = handle.read(max_bytes + 1)
        except OSError:
            return None
        if len(data) > max_bytes or b"\0" in data[:8192]:
            return None
        return data.decode("utf-8", errors="replace")

    def op_glob(self, args: dict) -> dict:
        pattern = args.get("pattern")
        limit = int(args.get("limit", 100))
        if not isinstance(pattern, str) or not pattern or limit < 1:
            raise _policy("invalid_glob_request")
        normalize(pattern.replace("*", "x").replace("?", "x") or "x")
        start = self._search_start(args.get("path"))
        rules = load_ignore_rules(self.root)
        base = os.path.join(self.root, *start)
        found: list[tuple[float, str]] = []
        for item, relative in self._iter_files(start, rules):
            from_start = os.path.relpath(item, base).replace(os.sep, "/") if start else relative
            if _matches_path(relative, pattern) or _matches_path(from_start, pattern):
                try:
                    mtime = os.stat(item).st_mtime
                except OSError:
                    mtime = 0.0
                found.append((mtime, relative))
        found.sort(key=lambda pair: (-pair[0], pair[1]))
        return {"paths": [relative for _mtime, relative in found[:limit]]}

    # -- checksum --

    def op_checksum(self, _args: dict) -> dict:
        digest = hashlib.sha256()
        with self.lock:
            for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
                dirnames.sort()
                filenames.sort()
                for name in dirnames:
                    item = os.path.join(dirpath, name)
                    relative = os.path.relpath(item, self.root).replace(os.sep, "/")
                    info = os.lstat(item)
                    if stat_mod.S_ISLNK(info.st_mode):
                        digest.update(b"L\0" + relative.encode() + b"\0" + os.readlink(item).encode() + b"\0")
                    else:
                        digest.update(b"D\0" + relative.encode() + b"\0%o\0" % (info.st_mode & 0o777))
                for name in filenames:
                    item = os.path.join(dirpath, name)
                    relative = os.path.relpath(item, self.root).replace(os.sep, "/")
                    info = os.lstat(item)
                    if stat_mod.S_ISLNK(info.st_mode):
                        digest.update(b"L\0" + relative.encode() + b"\0" + os.readlink(item).encode() + b"\0")
                    elif stat_mod.S_ISREG(info.st_mode):
                        content = hashlib.sha256()
                        with open(item, "rb") as handle:
                            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                                content.update(chunk)
                        digest.update(
                            b"F\0" + relative.encode() + b"\0%o\0%d\0" % (info.st_mode & 0o777, info.st_size)
                            + content.digest()
                        )
                    else:
                        digest.update(b"X\0" + relative.encode() + b"\0")
            return {"checksum": "sha256:" + digest.hexdigest(), "revision": self.revision}

    # -- commands --

    def _fingerprint(self) -> dict[str, tuple[int, int]]:
        result: dict[str, tuple[int, int]] = {}
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            kept = []
            for name in dirnames:
                item = os.path.join(dirpath, name)
                if os.path.islink(item):
                    continue
                relative = os.path.relpath(item, self.root).replace(os.sep, "/")
                if is_secret(relative) or _ignore_watch_path(relative):
                    continue
                kept.append(name)
            dirnames[:] = kept
            for name in filenames:
                item = os.path.join(dirpath, name)
                if os.path.islink(item) or not os.path.isfile(item):
                    continue
                relative = os.path.relpath(item, self.root).replace(os.sep, "/")
                if is_secret(relative) or _ignore_watch_path(relative):
                    continue
                info = os.lstat(item)
                result[relative] = (info.st_size, info.st_mtime_ns)
        return result

    def op_exec(self, args: dict) -> dict:
        argv = _validate_argv(args.get("argv"))
        overlay = _validate_env(args.get("env"))
        stdin = _unb64(args.get("stdin", ""))
        max_stdin = min(int(args["max_stdin_bytes"]), MAX_STDIN_BYTES)
        if len(stdin) > max_stdin:
            raise _policy("command_stdin_limit_exceeded")
        timeout = float(args["timeout_sec"])
        if timeout <= 0:
            raise _policy("command_timeout_must_be_positive")
        timeout = min(timeout, MAX_TIMEOUT_SEC)
        cap = int(args["max_output_bytes"])
        if cap <= 0:
            raise _policy("command_output_limit_must_be_positive")
        cap = min(cap, MAX_OUTPUT_BYTES)
        try:
            cwd = self.real_dir(normalize(args.get("cwd", ".")))
        except (FileNotFoundError, GuestError) as error:
            raise _policy("command_cwd_is_not_directory") from error
        env = guest_env(self.root, self.tmp_dir, overlay)
        with self.lock:
            before = self._fingerprint()
            result = self._run_bounded(argv, cwd, env, stdin, timeout, cap)
            after = self._fingerprint()
            changes = [
                {"path": path, "kind": "created"} for path in sorted(after.keys() - before.keys())
            ]
            changes.extend(
                {"path": path, "kind": "modified"}
                for path in sorted(before.keys() & after.keys())
                if before[path] != after[path]
            )
            changes.extend(
                {"path": path, "kind": "deleted"} for path in sorted(before.keys() - after.keys())
            )
            result["revision"] = self.bump(changes) if changes else self.revision
        return result

    def _run_bounded(self, argv, cwd, env, stdin, timeout, cap) -> dict:
        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                close_fds=True,
            )
        except FileNotFoundError as error:
            raise _policy("command_not_found") from error
        except PermissionError as error:
            raise _policy("command_not_executable") from error
        self._processes.add(process)
        overflow = threading.Event()
        stdout = _CappedReader(process.stdout.fileno(), cap, overflow)
        stderr = _CappedReader(process.stderr.fileno(), cap, overflow)
        stdout.start()
        stderr.start()

        def feed() -> None:
            try:
                if stdin:
                    process.stdin.write(stdin)
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        deadline = time.monotonic() + timeout
        timed_out = False
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    process.wait(min(0.05, remaining))
                    break
                except subprocess.TimeoutExpired:
                    if overflow.is_set():
                        break
            if timed_out or overflow.is_set():
                _terminate_group(process)
            else:
                # The leader exited. Commands may not leave descendants behind:
                # anything still in the group would outlive the call.
                _signal_group(process.pid, signal.SIGKILL)
            for reader in (stdout, stderr):
                reader.join(1.0)
                reader.stop()
                reader.join(1.0)
            feeder.join(1.0)
        finally:
            for stream in (process.stdout, process.stderr):
                try:
                    stream.close()
                except OSError:
                    pass
            self._processes.discard(process)
        if timed_out:
            return {
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
                "timed_out": True,
            }
        return {
            "exit_code": process.returncode,
            "stdout": _b64(bytes(stdout.data)),
            "stderr": _b64(bytes(stderr.data)),
            "stdout_truncated": stdout.truncated,
            "stderr_truncated": stderr.truncated,
            "timed_out": False,
        }

    # -- PTY --

    def _pty(self, args: dict) -> GuestPty:
        pty_id = args.get("pty_id")
        terminal = self._ptys.get(pty_id) if isinstance(pty_id, str) else None
        if terminal is None:
            raise GuestError("not_found", "pty_not_found")
        return terminal

    def op_pty_create(self, args: dict) -> dict:
        argv = _validate_argv(args.get("argv"))
        limit = min(int(args.get("max_sessions", MAX_PTYS)), MAX_PTYS)
        with self._pty_lock:
            active = [terminal for terminal in self._ptys.values() if not terminal.closed]
            if len(active) >= limit:
                raise _policy("pty_session_limit_exceeded")
            self._pty_seq += 1
            pty_id = f"pty_{self._pty_seq}_{os.urandom(8).hex()}"
            try:
                terminal = GuestPty(
                    pty_id, argv, self.root, guest_env(self.root, self.tmp_dir)
                )
            except FileNotFoundError as error:
                raise _policy("command_not_found") from error
            self._ptys[pty_id] = terminal
        return {"pty_id": pty_id}

    def op_pty_write(self, args: dict) -> dict:
        data = _unb64(args.get("data"))
        if len(data) > min(int(args["max_bytes"]), MAX_STDIN_BYTES):
            raise _policy("pty_input_limit_exceeded")
        self._pty(args).write(data)
        return {}

    def op_pty_resize(self, args: dict) -> dict:
        self._pty(args).resize(int(args["rows"]), int(args["cols"]))
        return {}

    def op_pty_kill(self, args: dict) -> dict:
        terminal = self._pty(args)
        terminal.kill("killed")
        with self._pty_lock:
            self._ptys.pop(terminal.pty_id, None)
        return {}

    def op_pty_read(self, args: dict) -> dict:
        terminal = self._pty(args)
        events, closed = terminal.journal.read(
            int(args.get("after_cursor", 0)),
            max_events=max(1, min(int(args.get("max_events", MAX_READ_EVENTS)), MAX_READ_EVENTS)),
            wait_sec=max(0.0, min(float(args.get("wait_sec", 0)), MAX_WAIT_SEC)),
        )
        return {"events": events, "closed": closed}

    def op_watch_read(self, args: dict) -> dict:
        events, closed = self.watch.read(
            int(args.get("after_cursor", 0)),
            max_events=max(1, min(int(args.get("max_events", MAX_READ_EVENTS)), MAX_READ_EVENTS)),
            wait_sec=max(0.0, min(float(args.get("wait_sec", 0)), MAX_WAIT_SEC)),
        )
        return {"events": events, "closed": closed}

    def shutdown(self) -> None:
        for terminal in list(self._ptys.values()):
            terminal.kill("sandbox_shutdown")
        for process in list(self._processes):
            _signal_group(process.pid, signal.SIGKILL)
        self.watch.close()


# ---- server ------------------------------------------------------------------


def _read_exact(stream, size: int) -> bytes | None:
    buffer = bytearray()
    while len(buffer) < size:
        chunk = stream.read(size - len(buffer))
        if not chunk:
            return None
        buffer.extend(chunk)
    return bytes(buffer)


class Server:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.digest = bundle_digest()
        self._executor = ThreadPoolExecutor(max_workers=16)
        ws = workspace
        self._handlers = {
            "revision": ws.op_revision,
            "stat": ws.op_stat,
            "list_tree": ws.op_list_tree,
            "read_file": ws.op_read_file,
            "write_file": ws.op_write_file,
            "mkdir": ws.op_mkdir,
            "rm": ws.op_rm,
            "mv": ws.op_mv,
            "chmod": ws.op_chmod,
            "search": ws.op_search,
            "glob": ws.op_glob,
            "checksum": ws.op_checksum,
            "exec": ws.op_exec,
            "pty.create": ws.op_pty_create,
            "pty.write": ws.op_pty_write,
            "pty.resize": ws.op_pty_resize,
            "pty.kill": ws.op_pty_kill,
            "pty.read": ws.op_pty_read,
            "watch.read": ws.op_watch_read,
        }

    def hello(self, args: dict) -> dict:
        base = args.get("base_revision", 0)
        if isinstance(base, int) and base > 0:
            with self.workspace.lock:
                if base > self.workspace.revision:
                    self.workspace.revision = base
                    self.workspace._persist_revision()
        return {
            "protocol_version": PROTOCOL_VERSION,
            "bundle_digest": self.digest,
            "capabilities": list(CAPABILITIES),
            "revision": self.workspace.revision,
        }

    def handle(self, rfile, wfile) -> None:
        write_lock = threading.Lock()

        def respond(message: dict) -> None:
            try:
                frame = encode_frame(message)
            except FrameError:
                frame = encode_frame(
                    {
                        "v": PROTOCOL_VERSION,
                        "id": message.get("id"),
                        "ok": False,
                        "error": {"kind": "unavailable", "code": "response_too_large"},
                    }
                )
            with write_lock:
                try:
                    wfile.write(frame)
                    wfile.flush()
                except (BrokenPipeError, OSError, ValueError):
                    pass

        def error(message_id, kind: str, code: str) -> None:
            respond(
                {
                    "v": PROTOCOL_VERSION,
                    "id": message_id,
                    "ok": False,
                    "error": {"kind": kind, "code": code},
                }
            )

        greeted = False
        while True:
            header = _read_exact(rfile, _HEADER.size)
            if header is None:
                return
            try:
                size = frame_length(header)
                payload = _read_exact(rfile, size)
                if payload is None:
                    return
                message = decode_payload(payload)
            except FrameError as failure:
                # A malformed or oversized frame cannot be resynchronized.
                error(None, "protocol", str(failure))
                return
            message_id = message.get("id")
            if message.get("v") != PROTOCOL_VERSION:
                error(message_id, "protocol", "protocol_version_unsupported")
                return
            op = message.get("op")
            args = message.get("args") or {}
            if not isinstance(args, dict):
                error(message_id, "policy", "request_invalid")
                continue
            if not greeted:
                if op != "hello":
                    error(message_id, "protocol", "handshake_required")
                    return
                greeted = True
                respond({"v": PROTOCOL_VERSION, "id": message_id, "ok": True, "result": self.hello(args)})
                continue
            self._executor.submit(self._dispatch, message_id, op, args, respond, error)

    def _dispatch(self, message_id, op, args, respond, error) -> None:
        handler = self._handlers.get(op)
        if handler is None:
            error(message_id, "policy", "operation_unknown")
            return
        try:
            result = handler(args)
        except GuestError as failure:
            error(message_id, failure.kind, failure.code)
            return
        except (KeyError, TypeError, ValueError):
            error(message_id, "policy", "request_invalid")
            return
        except OSError as failure:
            name = errno.errorcode.get(failure.errno or 0, "EIO")
            error(message_id, "policy", f"workspace_io_error:{name}")
            return
        except Exception:  # noqa: BLE001 - never leak guest internals to the host
            error(message_id, "unavailable", "guest_internal_error")
            return
        respond({"v": PROTOCOL_VERSION, "id": message_id, "ok": True, "result": result})


def _serve(args) -> int:
    workspace = Workspace(args.workspace, args.state_dir)
    server = Server(workspace)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        os.unlink(args.socket)
    except FileNotFoundError:
        pass
    listener.bind(args.socket)
    os.chmod(args.socket, 0o600)
    listener.listen(16)

    def stop(_signum, _frame) -> None:
        workspace.shutdown()
        os._exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while True:
        connection, _address = listener.accept()
        rfile = connection.makefile("rb", buffering=0)
        wfile = connection.makefile("wb", buffering=0)

        def run(conn=connection, reader=rfile, writer=wfile) -> None:
            try:
                server.handle(reader, writer)
            finally:
                for closable in (reader, writer, conn):
                    try:
                        closable.close()
                    except OSError:
                        pass

        threading.Thread(target=run, daemon=True).start()


def _stdio(args) -> int:
    workspace = Workspace(args.workspace, args.state_dir)
    try:
        Server(workspace).handle(sys.stdin.buffer, sys.stdout.buffer)
    finally:
        workspace.shutdown()
    return 0


def _connect(args) -> int:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(args.socket)
    done = threading.Event()

    def upstream() -> None:
        source = sys.stdin.buffer
        try:
            while True:
                chunk = source.read1(65536) if hasattr(source, "read1") else source.read(65536)
                if not chunk:
                    break
                connection.sendall(chunk)
        except OSError:
            pass
        finally:
            done.set()

    def downstream() -> None:
        sink = sys.stdout.buffer
        try:
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                sink.write(chunk)
                sink.flush()
        except OSError:
            pass
        finally:
            done.set()

    threading.Thread(target=upstream, daemon=True).start()
    threading.Thread(target=downstream, daemon=True).start()
    done.wait()
    connection.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="neos-sandboxd")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--workspace", required=True)
    serve.add_argument("--state-dir", required=True)
    serve.add_argument("--socket", required=True)
    stdio = commands.add_parser("stdio")
    stdio.add_argument("--workspace", required=True)
    stdio.add_argument("--state-dir", required=True)
    connect = commands.add_parser("connect")
    connect.add_argument("--socket", required=True)
    commands.add_parser("digest")
    args = parser.parse_args(argv)
    os.umask(0o022)
    if args.command == "digest":
        sys.stdout.write(bundle_digest() + "\n")
        return 0
    if args.command == "serve":
        return _serve(args)
    if args.command == "stdio":
        return _stdio(args)
    return _connect(args)


if __name__ == "__main__":
    raise SystemExit(main())

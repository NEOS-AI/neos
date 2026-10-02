"""Workspace session implemented with helper scripts run inside the guest.

Every file, search, and git operation is a short Python helper executed
against `/workspace` inside the sandbox. The Docker provider uses it;
subclasses supply only the transport -- how a helper or a command runs -- plus
the liveness check and PTYs. Managed sandboxes (E2B, Modal) do not: they speak
the `neos-sandboxd` RPC (`neos/coding/sandboxd/`) instead of `python -c`
helpers.

Transport contract for `_run_helper`: raise
`SandboxUnavailable("<transport>_command_failed:<exit code>")` on a non-zero
exit. The helper exit codes (2 missing, 3 symlink parent, 4 symlink leaf,
5 exists, 6 not empty) are part of the helper scripts' contract.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from neos.coding.sandbox.base import (
    CommandRequest,
    CommandResult,
    FileEntry,
    SandboxPolicyViolation,
    SandboxStateConflict,
    SandboxUnavailable,
    SearchMatch,
    read_byte_cap,
)
from neos.coding.sandbox.events import WorkspaceChange, WorkspaceChangeKind
from neos.coding.sandbox.helper_scripts import (
    _CHMOD_HELPER,
    _FILE_METADATA_HELPER,
    _GIT_SAFE,
    _GLOB_FILES_HELPER,
    _MKDIR_HELPER,
    _MV_HELPER,
    _READ_FILE_HELPER,
    _RM_HELPER,
    _SCAN_HELPER,
    _SEARCH_TEXT_HELPER,
    _WRITE_FILE_HELPER,
)
from neos.coding.sandbox.paths import (
    ensure_mutable_workspace_path,
    normalize_workspace_path,
)

_RESERVED_GUEST_ENV = frozenset({"PATH", "HOME", "TMPDIR"})


class HelperScriptSandboxSession:
    """`SandboxSession` over a helper-script transport.

    `record` carries the mutable per-sandbox state: `sandbox`, `lock`,
    `watcher`, `known_paths`, and `watching`.
    """

    _INVALID_OUTPUT = "sandbox_helper_output_invalid"

    def __init__(self, record: Any) -> None:
        self._record = record

    # ---- transport hooks -------------------------------------------------

    async def _ensure_running(self) -> None:
        raise NotImplementedError

    async def _run_helper(
        self,
        helper: str,
        *args: str,
        input: bytes = b"",
    ) -> Any:
        raise NotImplementedError

    async def _run_command(
        self,
        request: CommandRequest,
        *,
        workdir: str,
        env: Mapping[str, str],
        timeout_sec: float,
        secret_env: Mapping[str, str] | None = None,
    ) -> Any:
        """Run `request.argv` in `workdir`; return exit_code/stdout/stderr.

        A non-zero exit is a result, not an error. `secret_env` (track Q6)
        must never reach an argv -- it would show in the host process table.
        """
        raise NotImplementedError

    @property
    def _allowed_env_names(self) -> frozenset[str]:
        raise NotImplementedError

    def _now(self) -> datetime:
        raise NotImplementedError

    # ---- session ---------------------------------------------------------

    @property
    def sandbox_id(self) -> str:
        return self._record.sandbox.sandbox_id

    async def workspace_revision(self) -> int:
        await self._ensure_running()
        return self._record.sandbox.workspace_revision

    @staticmethod
    def _helper_exit_code(error: SandboxUnavailable) -> int | None:
        prefix, separator, code = str(error).rpartition(":")
        if not separator or not prefix.endswith("_command_failed") or not code.isdigit():
            return None
        return int(code)

    async def list_tree(self, path: str = ".") -> tuple[FileEntry, ...]:
        from neos.coding.sandbox.ignore import should_skip_walk

        relative = normalize_workspace_path(path)
        result = await self._run_helper(
            _FILE_METADATA_HELPER,
            relative.as_posix(),
            "tree",
        )
        return tuple(
            entry
            for entry in (
                self._file_entry(value) for value in self._load_json(result.stdout)
            )
            if not should_skip_walk(entry.path)
        )

    async def stat(self, path: str) -> FileEntry:
        from neos.coding.domain.approvals import is_denied_secret_path
        from neos.coding.sandbox.base import SandboxNotFound

        relative = normalize_workspace_path(path)
        if is_denied_secret_path(relative.as_posix()):
            raise SandboxPolicyViolation("workspace_secret_path")
        try:
            result = await self._run_helper(
                _FILE_METADATA_HELPER,
                relative.as_posix(),
                "stat",
            )
        except SandboxUnavailable as error:
            if self._helper_exit_code(error) == 2:
                raise SandboxNotFound(relative.as_posix()) from error
            raise
        return self._file_entry(self._load_json(result.stdout))

    async def read_file(
        self,
        path: str,
        *,
        offset: int = 1,
        limit: int | None = None,
        max_bytes: int | None = None,
    ) -> bytes:
        relative = normalize_workspace_path(path)
        if offset < 1 or (limit is not None and limit < 1):
            raise SandboxPolicyViolation("invalid_read_request")
        cap = read_byte_cap(self._record.sandbox.limits.max_output_bytes, max_bytes)
        try:
            result = await self._run_helper(
                _READ_FILE_HELPER,
                relative.as_posix(),
                str(offset),
                "" if limit is None else str(limit),
                str(cap),
            )
        except SandboxUnavailable as error:
            if self._helper_exit_code(error) == 3:
                raise SandboxPolicyViolation("file_read_limit_exceeded") from error
            raise
        return result.stdout[:cap]

    async def write_file(
        self, path: str, content: bytes, *, parents: bool = True
    ) -> int:
        return await self._write_file(
            path, content, expected_revision=None, parents=parents
        )

    async def write_file_if_revision(
        self,
        path: str,
        content: bytes,
        *,
        expected_revision: int,
    ) -> int:
        return await self._write_file(
            path,
            content,
            expected_revision=expected_revision,
        )

    async def _write_file(
        self,
        path: str,
        content: bytes,
        *,
        expected_revision: int | None,
        parents: bool = True,
    ) -> int:
        relative = ensure_mutable_workspace_path(path)
        limits = self._record.sandbox.limits
        if len(content) > min(limits.workspace_bytes, limits.max_stdin_bytes):
            raise SandboxPolicyViolation("workspace_write_limit_exceeded")
        async with self._record.lock:
            await self._ensure_running()
            if (
                expected_revision is not None
                and self._record.sandbox.workspace_revision
                != expected_revision
            ):
                raise SandboxStateConflict("workspace_revision_conflict")
            try:
                await self._run_helper(
                    _WRITE_FILE_HELPER,
                    relative.as_posix(),
                    "1" if parents else "0",
                    input=content,
                )
            except SandboxUnavailable as error:
                code = self._helper_exit_code(error)
                if code == 2:
                    raise FileNotFoundError(relative.as_posix()) from error
                if code == 3:
                    raise SandboxPolicyViolation(
                        "workspace_symlink_parent"
                    ) from error
                if code == 4:
                    raise SandboxPolicyViolation(
                        "workspace_symlink_leaf"
                    ) from error
                raise
            existed = relative.as_posix() in self._record.known_paths
            self._record.known_paths.add(relative.as_posix())
            self._record.sandbox = replace(
                self._record.sandbox,
                workspace_revision=self._record.sandbox.workspace_revision + 1,
                updated_at=self._now(),
            )
            await self._record.watcher.record(
                WorkspaceChange(
                    path=relative.as_posix(),
                    kind=(
                        WorkspaceChangeKind.MODIFIED
                        if existed
                        else WorkspaceChangeKind.CREATED
                    ),
                ),
                revision=self._record.sandbox.workspace_revision,
            )
            return self._record.sandbox.workspace_revision

    async def _record_mutation(
        self, path: str, *, kind: WorkspaceChangeKind
    ) -> int:
        self._record.known_paths.add(path)
        self._record.sandbox = replace(
            self._record.sandbox,
            workspace_revision=self._record.sandbox.workspace_revision + 1,
            updated_at=self._now(),
        )
        await self._record.watcher.record(
            WorkspaceChange(path=path, kind=kind),
            revision=self._record.sandbox.workspace_revision,
        )
        return self._record.sandbox.workspace_revision

    def _raise_helper_error(self, error: SandboxUnavailable) -> None:
        code = self._helper_exit_code(error)
        if code == 2:
            raise SandboxPolicyViolation("workspace_path_not_resolvable") from error
        if code == 3:
            raise SandboxPolicyViolation("workspace_symlink_parent") from error
        if code == 5:
            raise SandboxPolicyViolation("workspace_path_exists") from error
        if code == 6:
            raise SandboxPolicyViolation("workspace_directory_not_empty") from error
        raise error

    async def mkdir(self, path: str, *, parents: bool = False) -> int:
        from neos.coding.domain.approvals import is_denied_secret_path

        relative = ensure_mutable_workspace_path(path)
        if is_denied_secret_path(relative.as_posix()):
            raise SandboxPolicyViolation("workspace_secret_path")
        async with self._record.lock:
            await self._ensure_running()
            try:
                await self._run_helper(
                    _MKDIR_HELPER, relative.as_posix(), "1" if parents else "0"
                )
            except SandboxUnavailable as error:
                self._raise_helper_error(error)
            return await self._record_mutation(
                relative.as_posix(), kind=WorkspaceChangeKind.CREATED
            )

    async def rm(self, path: str, *, recursive: bool = False) -> int:
        from neos.coding.domain.approvals import is_denied_secret_path

        relative = ensure_mutable_workspace_path(path)
        if is_denied_secret_path(relative.as_posix()):
            raise SandboxPolicyViolation("workspace_secret_path")
        async with self._record.lock:
            await self._ensure_running()
            try:
                await self._run_helper(
                    _RM_HELPER, relative.as_posix(), "1" if recursive else "0"
                )
            except SandboxUnavailable as error:
                self._raise_helper_error(error)
            return await self._record_mutation(
                relative.as_posix(), kind=WorkspaceChangeKind.DELETED
            )

    async def mv(
        self, src: str, dest: str, *, overwrite: bool = False
    ) -> int:
        from neos.coding.domain.approvals import is_denied_secret_path

        src_rel = ensure_mutable_workspace_path(src)
        dest_rel = ensure_mutable_workspace_path(dest)
        if is_denied_secret_path(src_rel.as_posix()) or is_denied_secret_path(
            dest_rel.as_posix()
        ):
            raise SandboxPolicyViolation("workspace_secret_path")
        async with self._record.lock:
            await self._ensure_running()
            try:
                await self._run_helper(
                    _MV_HELPER,
                    src_rel.as_posix(),
                    dest_rel.as_posix(),
                    "1" if overwrite else "0",
                )
            except SandboxUnavailable as error:
                self._raise_helper_error(error)
            return await self._record_mutation(
                dest_rel.as_posix(), kind=WorkspaceChangeKind.MODIFIED
            )

    async def chmod(self, path: str, mode: int) -> int:
        from neos.coding.domain.approvals import is_denied_secret_path

        relative = ensure_mutable_workspace_path(path)
        if is_denied_secret_path(relative.as_posix()) and mode & 0o002:
            raise SandboxPolicyViolation("workspace_secret_path")
        async with self._record.lock:
            await self._ensure_running()
            try:
                await self._run_helper(
                    _CHMOD_HELPER, relative.as_posix(), str(int(mode))
                )
            except SandboxUnavailable as error:
                self._raise_helper_error(error)
            return await self._record_mutation(
                relative.as_posix(), kind=WorkspaceChangeKind.MODIFIED
            )

    async def watch_files(self, *, after_cursor: int = 0):
        await self._ensure_running()
        self._record.watching = True
        return self._record.watcher.open(after_cursor=after_cursor)

    async def search_text(
        self,
        query: str,
        *,
        paths: tuple[str, ...] = ("**/*",),
        regex: bool = False,
        limit: int = 100,
        before: int = 0,
        after: int = 0,
        output_mode: str = "content",
        ignore_case: bool = False,
        multiline: bool = False,
        context: int = 0,
        path: str | None = None,
        max_columns: int = 500,
        exclude: tuple[str, ...] = (),
    ) -> tuple[SearchMatch, ...]:
        if not query or limit < 1:
            raise SandboxPolicyViolation("invalid_search_request")
        if output_mode not in {"files", "content", "count"}:
            output_mode = "content"
        if context > 0:
            before = after = context
        before = max(0, min(int(before), 20))
        after = max(0, min(int(after), 20))
        for candidate in paths:
            normalize_workspace_path(candidate)
        for candidate in exclude:
            normalize_workspace_path(candidate)
        search_path = ""
        if path is not None:
            normalized = normalize_workspace_path(path)
            search_path = "" if normalized.as_posix() == "." else normalized.as_posix()
        result = await self._run_helper(
            _SEARCH_TEXT_HELPER,
            query,
            "1" if regex else "0",
            str(limit),
            str(before),
            str(after),
            output_mode,
            "1" if ignore_case else "0",
            "1" if multiline else "0",
            str(max_columns),
            search_path,
            json.dumps(list(exclude)),
            *paths,
        )
        try:
            values = json.loads(result.stdout)
            return tuple(
                SearchMatch(
                    path=value["path"],
                    line=value["line"],
                    column=value["column"],
                    text=value["text"],
                    before=tuple(value.get("before") or ()),
                    after=tuple(value.get("after") or ()),
                    count=value.get("count"),
                )
                for value in values
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            KeyError,
        ) as error:
            raise SandboxUnavailable(self._INVALID_OUTPUT) from error

    async def glob_files(
        self,
        pattern: str,
        *,
        limit: int = 100,
        path: str | None = None,
    ) -> tuple[str, ...]:
        if not pattern or limit < 1:
            raise SandboxPolicyViolation("invalid_glob_request")
        normalize_workspace_path(
            pattern.replace("*", "x").replace("?", "x") or "x"
        )
        args = [pattern, str(min(int(limit), 500))]
        if path:
            args.append(normalize_workspace_path(path).as_posix())
        result = await self._run_helper(
            _GLOB_FILES_HELPER,
            *args,
        )
        try:
            values = json.loads(result.stdout)
            return tuple(values)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise SandboxUnavailable(self._INVALID_OUTPUT) from error

    async def git_status(self) -> CommandResult:
        return await self.execute(
            CommandRequest(
                argv=(
                    *_GIT_SAFE,
                    "status",
                    "--short",
                    "--untracked-files=all",
                )
            )
        )

    async def git_diff(self, *, staged: bool = False) -> CommandResult:
        argv = (
            (*_GIT_SAFE, "diff", "--cached", "--no-ext-diff")
            if staged
            else (*_GIT_SAFE, "diff", "--no-ext-diff")
        )
        return await self.execute(CommandRequest(argv=argv))

    async def git_log(self, *, limit: int = 20) -> CommandResult:
        if limit < 1 or limit > 100:
            raise SandboxPolicyViolation("git_log_limit_invalid")
        return await self.execute(
            CommandRequest(
                argv=(
                    *_GIT_SAFE,
                    "log",
                    "--no-ext-diff",
                    f"--max-count={limit}",
                    "--oneline",
                )
            )
        )

    @classmethod
    def _load_json(cls, payload: bytes):
        try:
            return json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SandboxUnavailable(cls._INVALID_OUTPUT) from error

    @classmethod
    def _file_entry(cls, value) -> FileEntry:
        try:
            return FileEntry(
                path=value["path"],
                kind=value["kind"],
                size=value["size"],
                modified_at=datetime.fromisoformat(value["modified_at"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SandboxUnavailable(cls._INVALID_OUTPUT) from error

    async def execute(self, request: CommandRequest) -> CommandResult:
        await self._ensure_running()
        disallowed = set(request.env) - self._allowed_env_names
        if disallowed:
            raise SandboxPolicyViolation("environment_not_allowed")
        if len(request.stdin) > self._record.sandbox.limits.max_stdin_bytes:
            raise SandboxPolicyViolation("command_stdin_limit_exceeded")
        relative_cwd = normalize_workspace_path(request.cwd)
        workdir = "/workspace"
        if relative_cwd != normalize_workspace_path("."):
            workdir = f"/workspace/{relative_cwd.as_posix()}"
        env = {
            key: value
            for key, value in request.env.items()
            if key not in _RESERVED_GUEST_ENV
        }
        secret_env = {
            key: value
            for key, value in request.secret_env.items()
            if key not in _RESERVED_GUEST_ENV
        }
        async with self._record.lock:
            await self._ensure_running()
            before = await self._scan_workspace()
            result = await self._run_command(
                request,
                workdir=workdir,
                env=env,
                secret_env=secret_env,
                timeout_sec=min(
                    request.timeout_sec,
                    self._record.sandbox.limits.command_timeout_sec,
                ),
            )
            after = await self._scan_workspace()
            await self._record_scan_changes(before, after)
        limit = min(
            request.max_output_bytes,
            self._record.sandbox.limits.max_output_bytes,
        )
        return CommandResult(
            exit_code=result.exit_code,
            stdout=result.stdout[:limit],
            stderr=result.stderr[:limit],
            stdout_truncated=len(result.stdout) > limit,
            stderr_truncated=len(result.stderr) > limit,
        )

    async def _scan_workspace(self) -> dict[str, tuple[int, int]]:
        result = await self._run_helper(_SCAN_HELPER)
        values = self._load_json(result.stdout)
        try:
            return {path: tuple(value) for path, value in values.items()}
        except (AttributeError, TypeError) as error:
            raise SandboxUnavailable(self._INVALID_OUTPUT) from error

    async def _record_scan_changes(
        self,
        before: dict[str, tuple[int, int]],
        after: dict[str, tuple[int, int]],
    ) -> None:
        changes = []
        for path in sorted(before.keys() | after.keys()):
            if path not in before:
                kind = WorkspaceChangeKind.CREATED
            elif path not in after:
                kind = WorkspaceChangeKind.DELETED
            elif before[path] != after[path]:
                kind = WorkspaceChangeKind.MODIFIED
            else:
                continue
            changes.append(WorkspaceChange(path=path, kind=kind))
        if not changes:
            return
        self._record.sandbox = replace(
            self._record.sandbox,
            workspace_revision=self._record.sandbox.workspace_revision + 1,
            updated_at=self._now(),
        )
        self._record.known_paths = set(after)
        for change in changes:
            await self._record.watcher.record(
                change,
                revision=self._record.sandbox.workspace_revision,
            )

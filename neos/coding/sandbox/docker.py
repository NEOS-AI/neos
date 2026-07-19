from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from neos.coding.sandbox.base import (
    CommandRequest,
    CommandResult,
    FileEntry,
    SearchMatch,
    Sandbox,
    SandboxLimits,
    SandboxNotFound,
    SandboxPolicyViolation,
    SandboxState,
    SandboxStateConflict,
    SandboxUnavailable,
)
from neos.coding.sandbox.command import (
    DockerCommandRunner,
    build_create_args,
)
from neos.coding.sandbox.paths import (
    ensure_mutable_workspace_path,
    normalize_workspace_path,
)


_READ_FILE_HELPER = """\
from pathlib import Path
import sys
p = Path('/workspace') / sys.argv[1]
if not p.is_file() or p.is_symlink(): raise SystemExit(2)
sys.stdout.buffer.write(p.read_bytes())
"""
_WRITE_FILE_HELPER = """\
from pathlib import Path
import sys
p = Path('/workspace') / sys.argv[1]
p.parent.mkdir(parents=True, exist_ok=True)
p.write_bytes(sys.stdin.buffer.read())
"""
_SEARCH_TEXT_HELPER = """\
import fnmatch, json, re, sys
from pathlib import Path
query, regex, limit, *patterns = sys.argv[1:]
expression = re.compile(query if regex == '1' else re.escape(query))
matches = []
for p in sorted(Path('/workspace').rglob('*')):
    if not p.is_file() or p.is_symlink(): continue
    relative = p.relative_to('/workspace').as_posix()
    if not any(fnmatch.fnmatch(relative, pattern) for pattern in patterns): continue
    for number, line in enumerate(p.read_text(errors='replace').splitlines(), 1):
        match = expression.search(line)
        if match:
            matches.append({'path': relative, 'line': number,
                            'column': match.start() + 1, 'text': line})
            if len(matches) >= int(limit): break
    if len(matches) >= int(limit): break
sys.stdout.write(json.dumps(matches))
"""
_FILE_METADATA_HELPER = """\
import json, sys
from datetime import UTC, datetime
from pathlib import Path
root = Path('/workspace')
p = root / sys.argv[1]
def encode(item):
    value = item.lstat()
    kind = 'symlink' if item.is_symlink() else ('directory' if item.is_dir() else 'file')
    return {'path': item.relative_to(root).as_posix(), 'kind': kind,
            'size': value.st_size,
            'modified_at': datetime.fromtimestamp(value.st_mtime, UTC).isoformat()}
result = [encode(item) for item in sorted(p.rglob('*'))] if sys.argv[2] == 'tree' else encode(p)
sys.stdout.write(json.dumps(result))
"""


@dataclass(frozen=True, slots=True)
class DockerSandboxConfig:
    image: str
    create_timeout_sec: float = 30.0
    operation_timeout_sec: float = 30.0
    network_mode: str = "none"
    allow_unpinned_image: bool = False
    tmpfs_bytes: int = 64 * 1024 * 1024
    allowed_env_names: frozenset[str] = frozenset(
        {"HOME", "LANG", "LC_ALL", "PATH", "TERM", "TMPDIR"}
    )


@dataclass(slots=True)
class _DockerRecord:
    sandbox: Sandbox
    container_name: str
    volume_name: str
    lock: asyncio.Lock


class DockerSandboxProvider:
    def __init__(
        self,
        *,
        runner: DockerCommandRunner,
        config: DockerSandboxConfig,
        clock=None,
    ) -> None:
        self._runner = runner
        self._config = config
        self._clock = clock or (lambda: datetime.now(UTC))
        self._records: dict[str, _DockerRecord] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        owner_id: str,
        limits: SandboxLimits,
    ) -> Sandbox:
        sandbox_id = f"sb_{uuid.uuid4().hex}"
        container_name = f"neos-{sandbox_id}"
        volume_name = f"neos-sandbox-{sandbox_id}"
        now = self._clock()
        sandbox = Sandbox.creating(
            sandbox_id,
            owner_id,
            limits,
            now,
            provider="docker",
            image_digest=self._config.image,
        )
        volume_created = False
        container_created = False
        try:
            await self._runner.run(
                "volume",
                "create",
                "--label",
                "com.neos.coding.sandbox=true",
                "--label",
                f"com.neos.coding.sandbox-id={sandbox_id}",
                volume_name,
                timeout_sec=self._config.create_timeout_sec,
            )
            volume_created = True
            create_args = build_create_args(
                sandbox_id=sandbox_id,
                image=self._config.image,
                limits=limits,
                network_mode=self._config.network_mode,
                allow_unpinned_image=self._config.allow_unpinned_image,
                tmpfs_bytes=self._config.tmpfs_bytes,
            )
            await self._runner.run(
                *create_args,
                timeout_sec=self._config.create_timeout_sec,
            )
            container_created = True
            await self._runner.run(
                "start",
                container_name,
                timeout_sec=self._config.create_timeout_sec,
            )
            await self._probe(container_name)
        except BaseException:
            if container_created:
                await self._cleanup_command("rm", "--force", container_name)
            if volume_created:
                await self._cleanup_command("volume", "rm", volume_name)
            raise

        running = sandbox.transition(SandboxState.RUNNING, self._clock())
        async with self._lock:
            self._records[sandbox_id] = _DockerRecord(
                sandbox=running,
                container_name=container_name,
                volume_name=volume_name,
                lock=asyncio.Lock(),
            )
        return running

    async def get(self, sandbox_id: str) -> Sandbox:
        return (await self._record(sandbox_id)).sandbox

    async def suspend(self, sandbox_id: str) -> Sandbox:
        record = await self._running_record(sandbox_id)
        async with record.lock:
            await self._runner.run(
                "stop",
                record.container_name,
                timeout_sec=self._config.operation_timeout_sec,
            )
            record.sandbox = record.sandbox.transition(
                SandboxState.SUSPENDED,
                self._clock(),
            )
            return record.sandbox

    async def resume(self, sandbox_id: str) -> Sandbox:
        record = await self._record(sandbox_id)
        async with record.lock:
            if record.sandbox.state is not SandboxState.SUSPENDED:
                raise SandboxStateConflict(
                    f"sandbox_{record.sandbox.state.value}"
                )
            await self._runner.run(
                "start",
                record.container_name,
                timeout_sec=self._config.operation_timeout_sec,
            )
            await self._probe(record.container_name)
            record.sandbox = record.sandbox.transition(
                SandboxState.RUNNING,
                self._clock(),
            )
            return record.sandbox

    async def destroy(self, sandbox_id: str) -> None:
        async with self._lock:
            record = self._records.pop(sandbox_id, None)
        if record is None:
            return
        async with record.lock:
            await self._cleanup_command(
                "rm",
                "--force",
                record.container_name,
            )
            await self._cleanup_command(
                "volume",
                "rm",
                record.volume_name,
            )
            record.sandbox = record.sandbox.transition(
                SandboxState.DESTROYED,
                self._clock(),
            )

    async def open_session(self, sandbox_id: str) -> DockerSandboxSession:
        record = await self._running_record(sandbox_id)
        return DockerSandboxSession(self, record)

    async def close(self) -> None:
        async with self._lock:
            sandbox_ids = tuple(self._records)
        for sandbox_id in sandbox_ids:
            await self.destroy(sandbox_id)

    async def _record(self, sandbox_id: str) -> _DockerRecord:
        async with self._lock:
            record = self._records.get(sandbox_id)
        if record is None:
            raise SandboxNotFound(sandbox_id)
        return record

    async def _running_record(self, sandbox_id: str) -> _DockerRecord:
        record = await self._record(sandbox_id)
        if record.sandbox.state is not SandboxState.RUNNING:
            raise SandboxStateConflict(
                f"sandbox_{record.sandbox.state.value}"
            )
        return record

    async def _probe(self, container_name: str) -> None:
        await self._runner.run(
            "exec",
            container_name,
            "test",
            "-d",
            "/workspace",
            timeout_sec=self._config.create_timeout_sec,
        )

    async def _cleanup_command(self, *args: str) -> None:
        try:
            await self._runner.run(
                *args,
                timeout_sec=self._config.operation_timeout_sec,
            )
        except SandboxUnavailable:
            pass


class DockerSandboxSession:
    def __init__(
        self,
        provider: DockerSandboxProvider,
        record: _DockerRecord,
    ) -> None:
        self._provider = provider
        self._record = record

    @property
    def sandbox_id(self) -> str:
        return self._record.sandbox.sandbox_id

    async def list_tree(self, path: str = ".") -> tuple[FileEntry, ...]:
        relative = normalize_workspace_path(path)
        result = await self._run_helper(
            _FILE_METADATA_HELPER,
            relative.as_posix(),
            "tree",
        )
        return tuple(self._file_entry(value) for value in self._load_json(result.stdout))

    async def stat(self, path: str) -> FileEntry:
        relative = normalize_workspace_path(path)
        result = await self._run_helper(
            _FILE_METADATA_HELPER,
            relative.as_posix(),
            "stat",
        )
        return self._file_entry(self._load_json(result.stdout))

    async def read_file(self, path: str) -> bytes:
        relative = normalize_workspace_path(path)
        result = await self._run_helper(_READ_FILE_HELPER, relative.as_posix())
        return result.stdout

    async def write_file(self, path: str, content: bytes) -> int:
        relative = ensure_mutable_workspace_path(path)
        limits = self._record.sandbox.limits
        if len(content) > min(limits.workspace_bytes, limits.max_stdin_bytes):
            raise SandboxPolicyViolation("workspace_write_limit_exceeded")
        async with self._record.lock:
            await self._provider._running_record(self.sandbox_id)
            await self._run_helper(
                _WRITE_FILE_HELPER,
                relative.as_posix(),
                input=content,
            )
            self._record.sandbox = replace(
                self._record.sandbox,
                workspace_revision=self._record.sandbox.workspace_revision + 1,
                updated_at=self._provider._clock(),
            )
            return self._record.sandbox.workspace_revision

    async def search_text(
        self,
        query: str,
        *,
        paths: tuple[str, ...] = ("**/*",),
        regex: bool = False,
        limit: int = 100,
    ) -> tuple[SearchMatch, ...]:
        if not query or limit < 1:
            raise SandboxPolicyViolation("invalid_search_request")
        for path in paths:
            normalize_workspace_path(path)
        result = await self._run_helper(
            _SEARCH_TEXT_HELPER,
            query,
            "1" if regex else "0",
            str(limit),
            *paths,
        )
        try:
            values = json.loads(result.stdout)
            return tuple(SearchMatch(**value) for value in values)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            raise SandboxUnavailable("docker_helper_output_invalid") from error

    async def git_status(self) -> CommandResult:
        return await self.execute(
            CommandRequest(
                argv=("git", "status", "--short", "--untracked-files=all")
            )
        )

    async def git_diff(self, *, staged: bool = False) -> CommandResult:
        argv = ("git", "diff", "--cached") if staged else ("git", "diff")
        return await self.execute(CommandRequest(argv=argv))

    async def git_log(self, *, limit: int = 20) -> CommandResult:
        if limit < 1 or limit > 100:
            raise SandboxPolicyViolation("git_log_limit_invalid")
        return await self.execute(
            CommandRequest(
                argv=("git", "log", f"--max-count={limit}", "--oneline")
            )
        )

    async def _run_helper(
        self,
        helper: str,
        *args: str,
        input: bytes = b"",
    ):
        await self._provider._running_record(self.sandbox_id)
        return await self._provider._runner.run(
            "exec",
            "-i",
            self._record.container_name,
            "python",
            "-c",
            helper,
            *args,
            timeout_sec=self._provider._config.operation_timeout_sec,
            input=input,
        )

    @staticmethod
    def _load_json(payload: bytes):
        try:
            return json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SandboxUnavailable("docker_helper_output_invalid") from error

    @staticmethod
    def _file_entry(value) -> FileEntry:
        try:
            return FileEntry(
                path=value["path"],
                kind=value["kind"],
                size=value["size"],
                modified_at=datetime.fromisoformat(value["modified_at"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SandboxUnavailable("docker_helper_output_invalid") from error

    async def execute(self, request: CommandRequest) -> CommandResult:
        await self._provider._running_record(self.sandbox_id)
        disallowed = set(request.env) - self._provider._config.allowed_env_names
        if disallowed:
            raise SandboxPolicyViolation("environment_not_allowed")
        if len(request.stdin) > self._record.sandbox.limits.max_stdin_bytes:
            raise SandboxPolicyViolation("command_stdin_limit_exceeded")
        relative_cwd = normalize_workspace_path(request.cwd)
        workdir = "/workspace"
        if relative_cwd != normalize_workspace_path("."):
            workdir = f"/workspace/{relative_cwd.as_posix()}"
        args = ["exec"]
        if request.stdin:
            args.append("-i")
        args.extend(("--workdir", workdir))
        for key, value in request.env.items():
            args.extend(("--env", f"{key}={value}"))
        args.append(self._record.container_name)
        args.extend(request.argv)
        result = await self._provider._runner.run(
            *args,
            timeout_sec=min(
                request.timeout_sec,
                self._record.sandbox.limits.command_timeout_sec,
            ),
            allowed_exit_codes=tuple(range(256)),
            input=request.stdin,
        )
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

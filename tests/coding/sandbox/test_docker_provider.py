from datetime import UTC, datetime
import io
import json
import tarfile

import pytest

from neos.coding.sandbox.base import (
    CommandRequest,
    SandboxLimits,
    SandboxPolicyViolation,
    SandboxState,
    SandboxStateConflict,
)
from neos.coding.sandbox.command import DockerCommandResult
from neos.coding.sandbox.docker import (
    DockerSandboxConfig,
    DockerSandboxProvider,
    _GLOB_FILES_HELPER,
    _READ_FILE_HELPER,
    _SEARCH_TEXT_HELPER,
    _WRITE_FILE_HELPER,
)


IMAGE = "neos-sandbox@sha256:" + "a" * 64


class ScriptedDockerRunner:
    def __init__(self, results=None) -> None:
        self.results = list(results or [])
        self.calls = []
        self.inputs = []

    async def run(
        self,
        *args: str,
        timeout_sec: float,
        allowed_exit_codes=(0,),
        input: bytes = b"",
    ) -> DockerCommandResult:
        self.calls.append(args)
        self.inputs.append(input)
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return DockerCommandResult(exit_code=0, stdout=b"", stderr=b"")


def _config() -> DockerSandboxConfig:
    return DockerSandboxConfig(image=IMAGE, create_timeout_sec=5)


def _tar_bytes(name: str, content: bytes) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


async def test_create_is_running_only_after_readiness() -> None:
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(
        runner=runner,
        config=_config(),
        clock=lambda: datetime(2026, 7, 19, tzinfo=UTC),
    )

    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )

    assert sandbox.state is SandboxState.RUNNING
    assert [call[0] for call in runner.calls] == [
        "volume",
        "create",
        "start",
        "exec",
    ]
    assert runner.calls[-1][-2:] == ("test", "-d") or runner.calls[-1][-3:] == (
        "test",
        "-d",
        "/workspace",
    )
    assert "com.neos.coding.owner-id=u1" in runner.calls[1]


async def test_suspend_resume_and_command_execution_share_lifecycle() -> None:
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(runner=runner, config=_config())
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )

    assert (await provider.suspend(sandbox.sandbox_id)).state is SandboxState.SUSPENDED
    assert (await provider.resume(sandbox.sandbox_id)).state is SandboxState.RUNNING
    session = await provider.open_session(sandbox.sandbox_id)
    runner.results.extend(
        [
            DockerCommandResult(exit_code=0, stdout=b"{}", stderr=b""),
            DockerCommandResult(exit_code=7, stdout=b"out", stderr=b"err"),
            DockerCommandResult(exit_code=0, stdout=b"{}", stderr=b""),
        ]
    )
    result = await session.execute(CommandRequest(argv=("python", "-V")))

    assert result.exit_code == 7
    assert result.stdout == b"out"
    assert runner.calls[-2][0:3] == ("exec", "--workdir", "/workspace")


async def test_execute_forwards_bounded_stdin_and_rejects_unknown_env() -> None:
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(runner=runner, config=_config())
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)

    runner.results.extend(
        [
            DockerCommandResult(0, b"{}", b""),
            DockerCommandResult(0, b"", b""),
            DockerCommandResult(0, b"{}", b""),
        ]
    )
    await session.execute(CommandRequest(argv=("python", "-"), stdin=b"print(1)"))
    assert runner.inputs[-2] == b"print(1)"
    with pytest.raises(SandboxPolicyViolation, match="environment_not_allowed"):
        await session.execute(
            CommandRequest(argv=("env",), env={"TOKEN": "secret"})
        )


async def test_execute_does_not_forward_reserved_guest_env() -> None:
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(runner=runner, config=_config())
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    runner.results.extend(
        [
            DockerCommandResult(0, b"{}", b""),
            DockerCommandResult(0, b"", b""),
            DockerCommandResult(0, b"{}", b""),
        ]
    )

    await session.execute(
        CommandRequest(
            argv=("env",),
            env={
                "PATH": "/evil",
                "HOME": "/evil",
                "TMPDIR": "/evil",
                "LANG": "C.UTF-8",
            },
        )
    )

    forwarded = " ".join(runner.calls[-2])
    assert "--env PATH=/evil" not in forwarded
    assert "--env HOME=/evil" not in forwarded
    assert "--env TMPDIR=/evil" not in forwarded
    assert "--env LANG=C.UTF-8" in forwarded


async def test_session_file_tree_search_and_git_use_fixed_helpers() -> None:
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(runner=runner, config=_config())
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)

    assert await session.workspace_revision() == 0
    revision = await session.write_file("src/app.py", b"print('needle')\n")
    runner.results.extend(
        [
            DockerCommandResult(
                exit_code=0,
                stdout=b"print('needle')\n",
                stderr=b"",
            ),
            DockerCommandResult(
                exit_code=0,
                stdout=json.dumps(
                    [
                        {
                            "path": "src/app.py",
                            "line": 1,
                            "column": 8,
                            "text": "print('needle')",
                        }
                    ]
                ).encode(),
                stderr=b"",
            ),
            DockerCommandResult(exit_code=0, stdout=b"{}", stderr=b""),
            DockerCommandResult(0, b"?? src/app.py\n", b""),
            DockerCommandResult(exit_code=0, stdout=b"{}", stderr=b""),
        ]
    )

    content = await session.read_file("src/app.py")
    matches = await session.search_text(
        "needle",
        paths=("src/**",),
        limit=10,
    )
    status = await session.git_status()

    assert revision == 1
    assert await session.workspace_revision() == revision
    assert runner.inputs[4] == b"print('needle')\n"
    assert content == b"print('needle')\n"
    assert [(match.path, match.line) for match in matches] == [
        ("src/app.py", 1)
    ]
    assert matches[0].before == ()
    assert matches[0].after == ()
    assert status.stdout == b"?? src/app.py\n"


async def test_session_search_context_and_glob_use_fixed_helpers() -> None:
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(runner=runner, config=_config())
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    runner.results.extend(
        [
            DockerCommandResult(
                exit_code=0,
                stdout=json.dumps(
                    [
                        {
                            "path": "src/app.py",
                            "line": 2,
                            "column": 6,
                            "text": "beta needle",
                            "before": ["alpha"],
                            "after": ["gamma", "delta"],
                        }
                    ]
                ).encode(),
                stderr=b"",
            ),
            DockerCommandResult(
                exit_code=0,
                stdout=json.dumps(["src/app.py", "src/util.py"]).encode(),
                stderr=b"",
            ),
        ]
    )

    matches = await session.search_text(
        "needle",
        paths=("src/**",),
        limit=10,
        before=1,
        after=2,
    )
    found = await session.glob_files("src/*.py", limit=1000)
    calls_after_glob = len(runner.calls)

    assert matches[0].before == ("alpha",)
    assert matches[0].after == ("gamma", "delta")
    assert found == ("src/app.py", "src/util.py")
    assert runner.calls[-2][-12:] == (
        "needle",
        "0",
        "10",
        "1",
        "2",
        "content",
        "0",
        "0",
        "500",
        "",
        "[]",
        "src/**",
    )
    assert runner.calls[-1][-2:] == ("src/*.py", "500")
    with pytest.raises(SandboxPolicyViolation, match="workspace_path_escape"):
        await session.glob_files("../secret.py")
    with pytest.raises(SandboxPolicyViolation, match="invalid_glob_request"):
        await session.glob_files("", limit=10)
    assert len(runner.calls) == calls_after_glob


def test_docker_helpers_do_not_follow_dir_symlinks_and_cap_reads() -> None:
    assert "followlinks=False" in _SEARCH_TEXT_HELPER
    assert "followlinks=False" in _GLOB_FILES_HELPER
    assert "is_file()" in _GLOB_FILES_HELPER
    assert "max_bytes" in _READ_FILE_HELPER
    assert ".jj" in _SEARCH_TEXT_HELPER
    assert ".sl" in _GLOB_FILES_HELPER
    assert "exclude_json" in _SEARCH_TEXT_HELPER
    assert "encode('utf-8')" in _SEARCH_TEXT_HELPER


def test_write_file_helper_fsyncs_before_replace() -> None:
    write_at = _WRITE_FILE_HELPER.index("handle.write")
    replace_at = _WRITE_FILE_HELPER.index("os.replace")
    flush_at = _WRITE_FILE_HELPER.index("flush")
    fsync_at = _WRITE_FILE_HELPER.index("fsync")
    assert write_at < flush_at < fsync_at < replace_at



async def test_docker_git_commands_disable_external_diff_and_pager() -> None:
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(runner=runner, config=_config())
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    runner.results.extend(
        [
            DockerCommandResult(0, b"{}", b""),
            DockerCommandResult(0, b"", b""),
            DockerCommandResult(0, b"{}", b""),
            DockerCommandResult(0, b"{}", b""),
            DockerCommandResult(0, b"", b""),
            DockerCommandResult(0, b"{}", b""),
            DockerCommandResult(0, b"{}", b""),
            DockerCommandResult(0, b"", b""),
            DockerCommandResult(0, b"{}", b""),
        ]
    )

    await session.git_status()
    await session.git_diff()
    await session.git_log(limit=5)

    git_calls = [call for call in runner.calls if "git" in call]
    assert len(git_calls) == 3
    for call in git_calls:
        assert "--no-pager" in call
        assert "core.pager=cat" in call
    assert "--no-ext-diff" in git_calls[1]
    assert "--no-ext-diff" in git_calls[2]


async def test_conditional_write_rejects_stale_revision_before_docker_exec() -> None:
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(runner=runner, config=_config())
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    assert (
        await session.write_file_if_revision(
            "src/app.py",
            b"first",
            expected_revision=0,
        )
        == 1
    )
    calls_after_first_write = len(runner.calls)

    with pytest.raises(
        SandboxStateConflict, match="workspace_revision_conflict"
    ):
        await session.write_file_if_revision(
            "src/app.py",
            b"stale",
            expected_revision=0,
        )

    assert len(runner.calls) == calls_after_first_write
    assert await session.workspace_revision() == 1


async def test_session_list_tree_and_stat_parse_fixed_helper_output() -> None:
    payload = {
        "path": "src/app.py",
        "kind": "file",
        "size": 12,
        "modified_at": "2026-07-19T10:00:00+00:00",
    }
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(runner=runner, config=_config())
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    runner.results.extend(
        [
            DockerCommandResult(0, json.dumps([payload]).encode(), b""),
            DockerCommandResult(0, json.dumps(payload).encode(), b""),
        ]
    )

    tree = await session.list_tree("src")
    entry = await session.stat("src/app.py")

    assert tree == (entry,)
    assert entry.path == "src/app.py"
    assert entry.modified_at == datetime(2026, 7, 19, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    "path",
    [".env", ".ssh/id_rsa", ".git/config"],
)
async def test_docker_stat_denies_secret_paths(path: str) -> None:
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(runner=runner, config=_config())
    sandbox = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    calls_before = len(runner.calls)

    with pytest.raises(SandboxPolicyViolation):
        await session.stat(path)

    assert len(runner.calls) == calls_before


async def test_snapshot_restore_transfers_validated_archive_and_revision(
    tmp_path,
) -> None:
    archive = _tar_bytes("state.txt", b"v1")
    runner = ScriptedDockerRunner()
    provider = DockerSandboxProvider(
        runner=runner,
        config=DockerSandboxConfig(image=IMAGE, snapshot_root=tmp_path),
    )
    source = await provider.create(
        owner_id="u1",
        limits=SandboxLimits.safe_defaults(),
    )
    session = await provider.open_session(source.sandbox_id)
    await session.write_file("state.txt", b"v1")
    runner.results.append(DockerCommandResult(0, archive, b""))

    snapshot = await provider.snapshot(source.sandbox_id)
    restored = await provider.restore(snapshot.snapshot_id, owner_id="u2")

    assert snapshot.workspace_revision == 1
    assert restored.workspace_revision == 1
    assert restored.sandbox_id != source.sandbox_id
    assert runner.inputs[-1] == archive


async def test_provider_rediscovers_only_owned_labeled_containers() -> None:
    runner = ScriptedDockerRunner(
        results=[
            DockerCommandResult(0, b"container-owned\ncontainer-other\n", b""),
            DockerCommandResult(
                0,
                json.dumps(
                    [
                        {
                            "Id": "container-owned",
                            "Name": "/neos-sb_owned",
                            "Config": {
                                "Labels": {
                                    "com.neos.coding.sandbox": "true",
                                    "com.neos.coding.sandbox-id": "sb_owned",
                                    "com.neos.coding.owner-id": "u1",
                                    "com.neos.coding.created-at": "2026-07-19T10:00:00+00:00",
                                    "com.neos.coding.workspace-revision": "3",
                                }
                            },
                            "State": {"Running": True},
                        },
                        {
                            "Id": "container-other",
                            "Name": "/unrelated",
                            "Config": {"Labels": {}},
                            "State": {"Running": True},
                        },
                    ]
                ).encode(),
                b"",
            ),
        ]
    )
    provider = DockerSandboxProvider(runner=runner, config=_config())

    recovered = await provider.reconcile()

    assert [(item.sandbox_id, item.workspace_revision) for item in recovered] == [
        ("sb_owned", 3)
    ]
    assert runner.calls[0][:3] == ("ps", "--all", "--filter")

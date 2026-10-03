"""Q16c: the reference client's command runner -- pinned executables, scrubbed environment,
confined cwd, process-group kill, capped output, and the only module that starts a process.

Real processes under tmp_path (POSIX). The end-to-end test wires the real runner to the real
server socket session and service.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

from neos.bridge.client import _encode_result, serve
from neos.bridge.tools import BridgeToolError, LocalReadOnlyTools

pytestmark = [
    pytest.mark.no_db,
    pytest.mark.skipif(os.name != "posix", reason="device commands need POSIX process groups"),
]

BRIDGE_SRC = Path(__file__).resolve().parents[2] / "neos" / "bridge"
PY = Path(sys.executable).name


@pytest.fixture
def shared(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "shared"
    (root / "pkg").mkdir(parents=True)
    (root / ".ssh").mkdir()
    (root / "notes.md").write_text("hi\n")
    (tmp_path / "outside").mkdir()
    # The interpreter running the tests is the one allowed executable.
    monkeypatch.setenv("PATH", f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}")
    return root


def _runner(root: Path, executables=(PY,), **kw):
    from neos.bridge.commands import CommandRunner

    return CommandRunner(LocalReadOnlyTools(root), executables, **kw)


def _script(root: Path, name: str, body: str) -> str:
    (root / name).write_text(body)
    return name


def _code(fn, *args, **kwargs) -> str:
    with pytest.raises(BridgeToolError) as error:
        fn(*args, **kwargs)
    return error.value.code


def test_the_client_runs_only_its_pinned_executables(shared: Path, monkeypatch) -> None:
    """BC7. Mutation: resolve argv[0] on PATH at call time (or skip `device_command_refusal`
    in `run_command`) -> an undeclared or later-planted executable runs."""
    runner = _runner(shared)
    script = _script(shared, "hello.py", "print('hello from the device')\n")

    done = runner.call("run_command", {"argv": [PY, script]})
    assert done["exit_code"] == 0 and done["stdout"].strip() == "hello from the device"
    assert runner.declaration()[-1] == {"name": "run_command", "risk": "command", "executables": [PY]}

    assert _code(runner.run_command, ["ruff", "check"]) == "command_not_allowed"
    assert _code(runner.run_command, [PY, "-c", "print(1)"]) == "command_refused"
    assert _code(runner.run_command, "python hello.py") == "command_refused"

    for bad in (["bash"], ["env"], ["definitely-not-installed-q16c"]):
        with pytest.raises(ValueError):
            _runner(shared, bad)
    # An executable that lives inside the shared folder is refused at startup.
    planted = shared / "bin"
    planted.mkdir()
    (planted / "q16c-tool").write_text("#!/bin/sh\necho planted\n")
    (planted / "q16c-tool").chmod(0o755)
    monkeypatch.setenv("PATH", f"{planted}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(ValueError, match="inside the shared folder"):
        _runner(shared, ["q16c-tool"])
    # A runner pinned before the PATH changed keeps its pinned path.
    assert runner.call("run_command", {"argv": [PY, script]})["exit_code"] == 0


def test_the_child_process_gets_a_scrubbed_environment(shared: Path, monkeypatch) -> None:
    """BC7. Mutation: pass `os.environ` to the child -> the bridge token reaches it."""
    from neos.bridge.commands import PASSED_ENV

    monkeypatch.setenv("NEOS_BRIDGE_TOKEN", "ndb_should_never_leave")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-should-never-leave")
    script = _script(
        shared,
        "env.py",
        "import json, os, sys\nprint(json.dumps({'env': sorted(os.environ), 'stdin': sys.stdin.read()}))\n",
    )
    out = _runner(shared).run_command([PY, script])

    seen = json.loads(out["stdout"])
    assert "ndb_should_never_leave" not in out["stdout"] and "aws-should" not in out["stdout"]
    allowed = set(PASSED_ENV) | {"TERM", "NO_COLOR"}
    # The interpreter may add its own (e.g. macOS __CF_USER_TEXT_ENCODING, LC_CTYPE) -- none of ours.
    assert not {"NEOS_BRIDGE_TOKEN", "AWS_SECRET_ACCESS_KEY"} & set(seen["env"])
    assert {"TERM", "NO_COLOR"} <= set(seen["env"]) and set(seen["env"]) - allowed <= {
        "__CF_USER_TEXT_ENCODING",
        "LC_CTYPE",
    }
    assert seen["stdin"] == ""


def test_the_client_confines_cwd_to_the_root(shared: Path, tmp_path: Path) -> None:
    """BC8 on the device. Mutation: pass `cwd` to Popen without `resolve` -> a link out of the
    root becomes the working directory."""
    runner = _runner(shared)
    script = _script(shared, "where.py", "import os\nprint(os.getcwd())\n")
    _script(shared, "pkg/where.py", "import os\nprint(os.getcwd())\n")
    (shared / "out").symlink_to(tmp_path / "outside")

    assert _code(runner.run_command, [PY, script], cwd="../") == "path_escape"
    assert _code(runner.run_command, [PY, script], cwd="out") == "path_escape"
    assert _code(runner.run_command, [PY, script], cwd="notes.md") == "not_a_directory"
    assert _code(runner.run_command, [PY, script], cwd=".ssh") == "secret_path"
    assert _code(runner.run_command, [PY, script, "/etc/passwd"]) == "path_escape"
    assert _code(runner.run_command, [PY, "../where.py"], cwd="pkg") == "path_escape"
    done = runner.run_command([PY, "where.py"], cwd="pkg")
    assert Path(done["stdout"].strip()).resolve() == (shared / "pkg").resolve()


def test_a_command_that_overruns_is_killed_with_its_process_group(shared: Path) -> None:
    """BC8. Mutation: kill only the direct child (or skip the after-exit group kill) -> the
    background grandchild keeps running after the call returns."""
    pid_file = shared / "child.pid"
    script = _script(
        shared,
        "linger.py",
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "print('started', flush=True)\n"
        "time.sleep(60)\n",
    )
    started = time.monotonic()
    out = _runner(shared, max_timeout_sec=1.5).run_command([PY, script], timeout_sec=30)

    assert out["timed_out"] is True and out["exit_code"] is None
    assert time.monotonic() - started < 15 and "started" in out["stdout"]
    grandchild = int(pid_file.read_text())
    for _ in range(50):
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the grandchild outlived the call")


def test_command_output_is_capped_on_the_device_and_never_blocks(shared: Path) -> None:
    script = _script(shared, "loud.py", "import sys\nsys.stdout.write('x' * 2_000_000)\nsys.stderr.write('e' * 10)\n")
    out = _runner(shared, max_output_bytes=1024).run_command([PY, script], max_output_bytes=4096)

    assert out["exit_code"] == 0 and out["truncated"] is True
    assert len(out["stdout"]) == 1024 and out["stderr"] == "e" * 10
    # The wire encoder halves a stream rather than failing the answer.
    payload = {"ok": True, "result": {**out, "stdout": "y" * 10_000}}
    encoded = json.loads(_encode_result("r1", payload, 4096))
    assert encoded["ok"] is True and encoded["result"]["truncated"] is True
    assert encoded["result"]["exit_code"] == 0


def test_only_the_command_module_may_start_a_process() -> None:
    """BC7: `commands.py` is the single exception to "the client executes nothing", and it starts
    processes one way only: `subprocess.Popen(..., shell=False)`. Nothing imports it at module
    level -- `__main__` imports it inside `main()` when `--allow-commands` names something.
    Mutation: add `shell=True`, `os.system`, or a top-level `import neos.bridge.commands` -> red."""
    tree = ast.parse((BRIDGE_SRC / "commands.py").read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    names = [
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in calls
    ]
    popens = [node for node, name in zip(calls, names, strict=True) if name == "Popen"]
    assert len(popens) == 1
    [shell] = [kw for kw in popens[0].keywords if kw.arg == "shell"]
    assert isinstance(shell.value, ast.Constant) and shell.value.value is False
    module_calls = [
        (node.func.value.id, node.func.attr)
        for node in calls
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
    ]
    assert [attr for mod, attr in module_calls if mod == "subprocess"] == ["Popen"]
    assert not [
        attr
        for mod, attr in module_calls
        if mod == "os" and (attr in {"system", "popen", "startfile"} or attr.startswith(("exec", "spawn", "posix_spawn")))
    ]
    assert not [n for n in names if n in {"eval", "exec"}]

    for path in sorted(BRIDGE_SRC.glob("*.py")):
        module = ast.parse(path.read_text())
        top = [
            node
            for node in module.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and "neos.bridge.commands" in (
                [alias.name for alias in node.names] + [getattr(node, "module", "") or ""]
            )
        ]
        assert top == [], path.name


async def test_end_to_end_a_command_runs_through_the_client(shared: Path) -> None:
    from neos.coding.bridge.catalog import parse_bridge_declaration
    from neos.coding.bridge.relay import BridgeView, InProcessDeviceBridgeRelay
    from neos.coding.bridge.service import DeviceBridgeService
    from neos.coding.bridge.session import BridgeSocketSession
    from neos.coding.tools.registry import CodingToolRegistry
    from neos.config.schema import DeviceBridgeConfig
    from tests.bridge.test_bridge_client import _Pipe

    script = _script(shared, "hello.py", "print('\\x1b[31mred\\x1b[0m and fine')\n")
    pipe = _Pipe()
    relay = InProcessDeviceBridgeRelay()
    config = DeviceBridgeConfig(command_allowlist=[PY], command_timeout_seconds=20)
    client = asyncio.create_task(serve(pipe, _runner(shared)))

    hello = json.loads(await pipe.receive_text())
    names, executables = parse_bridge_declaration(
        hello["tools"], allow_commands=True, command_allowlist=config.command_allowlist
    )
    view = BridgeView("alice", "dbr_1", "c1", names, False, executables)

    class Live:
        allow_unattended = False
        allow_commands = True

    async def recheck():
        return Live()

    server = asyncio.create_task(
        BridgeSocketSession(pipe, view, relay, config=config, recheck=recheck).run()
    )
    service = DeviceBridgeService(relay, config)
    while await service.view("alice") is None:
        await asyncio.sleep(0)
    registry = CodingToolRegistry.default(
        command_allowlist=frozenset({"git"}),
        device_tools=True,
        device_command_allowlist=frozenset(config.command_allowlist),
    )

    ran = await service.execute(
        "alice", registry.validate("device_run_command.v1", {"argv": [PY, script]}), unattended=False
    )

    assert ran.status == "ok" and ran.exit_code == 0
    assert "red and fine" in ran.preview and "\x1b" not in ran.preview
    assert ran.preview.startswith("exit_code: 0\n----- begin untrusted device content -----")

    server.cancel()
    client.cancel()
    for task in (server, client):
        with pytest.raises(BaseException):
            await task

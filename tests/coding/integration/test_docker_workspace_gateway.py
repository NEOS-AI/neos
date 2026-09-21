import os
import shutil

import pytest

from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.command import DockerCommandRunner
from neos.coding.sandbox.docker import DockerSandboxConfig, DockerSandboxProvider
from neos.coding.sandbox.events import PtyOutput


DOCKER_ENABLED = os.getenv("CODING_TEST_DOCKER") == "1"
DOCKER_IMAGE = os.getenv("CODING_TEST_DOCKER_IMAGE", "")

pytestmark = pytest.mark.skipif(
    not DOCKER_ENABLED or "@sha256:" not in DOCKER_IMAGE or shutil.which("docker") is None,
    reason=(
        "set CODING_TEST_DOCKER=1 and a digest-pinned "
        "CODING_TEST_DOCKER_IMAGE to run the workspace gateway slice"
    ),
)


async def test_real_docker_workspace_watcher_and_pty_reconnect(tmp_path) -> None:
    provider = DockerSandboxProvider(
        runner=DockerCommandRunner(),
        config=DockerSandboxConfig(
            image=DOCKER_IMAGE,
            snapshot_root=tmp_path / "snapshots",
        ),
    )
    sandbox = await provider.create(
        owner_id="ct_docker_gateway",
        limits=SandboxLimits.safe_defaults(),
    )
    try:
        session = await provider.open_session(sandbox.sandbox_id)
        watcher = await session.watch_files(after_cursor=0)
        revision = await session.write_file_if_revision(
            "src/app.py",
            b"print('gateway')\n",
            expected_revision=0,
        )
        changed = await anext(watcher)
        assert changed.value.workspace_revision == revision

        terminal = await session.create_pty(argv=("/bin/sh",))
        await session.write_pty(terminal.pty_id, b"printf docker-gateway\\n")
        async for event in terminal.subscribe(after_cursor=0):
            if isinstance(event.value, PtyOutput) and b"docker-gateway" in event.value.data:
                replay = await terminal.replay(after_cursor=event.cursor - 1)
                # Anchor, not tail: the shell keeps emitting after the match.
                assert replay[0].cursor == event.cursor
                break
        await session.kill_pty(terminal.pty_id)
        await watcher.aclose()
    finally:
        await provider.destroy(sandbox.sandbox_id)
        await provider.close()

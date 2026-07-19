import sys
from pathlib import Path

from neos.coding.sandbox.base import CommandRequest
from neos.coding.sandbox.process import BoundedProcessRunner


async def test_process_timeout_kills_child_group(tmp_path: Path) -> None:
    result = await BoundedProcessRunner().run(
        CommandRequest(
            argv=(
                sys.executable,
                "-c",
                "import time; time.sleep(5)",
            ),
            timeout_sec=0.05,
        ),
        cwd=tmp_path,
        env={},
    )

    assert result.timed_out is True
    assert result.exit_code is None


async def test_process_truncates_stdout_and_stderr_independently(
    tmp_path: Path,
) -> None:
    result = await BoundedProcessRunner().run(
        CommandRequest(
            argv=(
                sys.executable,
                "-c",
                "import sys; print('o' * 20); print('e' * 20, file=sys.stderr)",
            ),
            timeout_sec=2,
            max_output_bytes=8,
        ),
        cwd=tmp_path,
        env={},
    )

    assert result.exit_code == 0
    assert result.stdout == b"oooooooo"
    assert result.stderr == b"eeeeeeee"
    assert result.stdout_truncated is True
    assert result.stderr_truncated is True

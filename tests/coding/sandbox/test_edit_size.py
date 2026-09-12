import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from neos.coding.sandbox.base import SandboxLimits, SandboxPolicyViolation
from neos.coding.sandbox.memory import MemorySandboxProvider
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import ToolRisk, ValidatedToolCall

pytestmark = pytest.mark.no_db


def call(name: str, input: dict[str, object]) -> ValidatedToolCall:
    risk = (
        ToolRisk.WORKSPACE_WRITE
        if name in {"write_file.v1", "edit_file.v1"}
        else ToolRisk.READ_ONLY
    )
    return ValidatedToolCall(name, input, risk)


async def test_edit_file_larger_than_read_preview_cap_succeeds(tmp_path: Path) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=replace(SandboxLimits.safe_defaults(), max_output_bytes=32),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    payload = b"alpha\n" + (b"x" * 80) + b"\n"
    await session.write_file("big.txt", payload)
    stamp = await session.stat("big.txt")

    with pytest.raises(SandboxPolicyViolation, match="file_read_limit_exceeded"):
        await session.read_file("big.txt")

    result = await SandboxToolExecutor(64, 10).execute(
        session,
        call(
            "edit_file.v1",
            {"path": "big.txt", "old_string": "alpha", "new_string": "beta"},
        ),
        known_reads=frozenset({"big.txt"}),
        known_stamps={
            "big.txt": {
                "mtime": stamp.modified_at.isoformat(),
                "digest": hashlib.sha256(payload).hexdigest(),
                "full": True,
            }
        },
    )

    assert result.status == "ok"
    assert await session.read_file("big.txt", offset=1, limit=1) == b"beta\n"
    await provider.close()


async def test_stale_since_read_on_file_larger_than_preview_cap_denies(
    tmp_path: Path,
) -> None:
    provider = MemorySandboxProvider(root=tmp_path)
    sandbox = await provider.create(
        owner_id="u1",
        limits=replace(SandboxLimits.safe_defaults(), max_output_bytes=32),
    )
    session = await provider.open_session(sandbox.sandbox_id)
    original = b"old-line\n" + (b"y" * 80) + b"\n"
    await session.write_file("big.txt", original)
    stamp = await session.stat("big.txt")
    changed = b"changed\n" + (b"z" * 80) + b"\n"
    await session.write_file("big.txt", changed)

    with pytest.raises(SandboxPolicyViolation, match="file_read_limit_exceeded"):
        await session.read_file("big.txt")

    result = await SandboxToolExecutor(64, 10).execute(
        session,
        call("write_file.v1", {"path": "big.txt", "content": "new\n"}),
        known_reads=frozenset({"big.txt"}),
        known_stamps={
            "big.txt": {
                "mtime": stamp.modified_at.isoformat(),
                "digest": hashlib.sha256(original).hexdigest(),
                "full": True,
            }
        },
    )

    assert (result.status, result.reason_code) == (
        "denied",
        "precondition_stale_read",
    )
    assert await session.hash_file("big.txt") == hashlib.sha256(changed).hexdigest()
    await provider.close()

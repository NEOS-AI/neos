"""진짜 Docker 에서 조사 샌드박스의 두 벽을 두드려 본다 (계약 §3.2).

가짜 러너는 인자 목록만 본다. 인자가 맞아도 데몬이 그것을 어떻게 적용하는지
-- 읽기 전용 볼륨이 정말 `EROFS` 를 내는지, `--network none` 이 정말 루프백만
남기는지 -- 는 컨테이너 안에서 시도해 봐야 안다.

`test_docker_sandbox.py` 와 같은 조건으로 돈다: `CODING_TEST_DOCKER=1` 과
digest 고정 `CODING_TEST_DOCKER_IMAGE`(python 이 든 이미지). 예:

    CODING_TEST_DOCKER=1 \\
    CODING_TEST_DOCKER_IMAGE=python@sha256:<digest> \\
    pytest tests/coding/integration/test_docker_research_profile.py
"""

from __future__ import annotations

import os
import shutil
import uuid

import pytest

from neos.coding.sandbox.base import CommandRequest, SandboxLimits, SandboxUnavailable
from neos.coding.sandbox.command import DockerCommandRunner
from neos.coding.sandbox.docker import DockerSandboxConfig, DockerSandboxProvider

DOCKER_ENABLED = os.getenv("CODING_TEST_DOCKER") == "1"
DOCKER_IMAGE = os.getenv("CODING_TEST_DOCKER_IMAGE", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.no_db,
    pytest.mark.timeout(180),
    pytest.mark.skipif(
        not DOCKER_ENABLED or not DOCKER_IMAGE or shutil.which("docker") is None,
        reason=(
            "set CODING_TEST_DOCKER=1, set a digest-pinned "
            "CODING_TEST_DOCKER_IMAGE, and install Docker"
        ),
    ),
]

REF = "abc123def456ffff"


@pytest.fixture
async def provider():
    # 설정은 일부러 bridge 다. profile 이 설정을 이겨야 한다.
    provider = DockerSandboxProvider(
        runner=DockerCommandRunner(),
        config=DockerSandboxConfig(
            image=DOCKER_IMAGE, create_timeout_sec=60, network_mode="bridge"
        ),
    )
    try:
        yield provider
    finally:
        await provider.close()


async def _python(session, code: str):
    return await session.execute(CommandRequest(argv=("python3", "-c", code)))


async def test_the_worker_cannot_touch_evidence_and_has_no_network(provider) -> None:
    sandbox = await provider.create(
        owner_id="q_integration",
        limits=SandboxLimits.safe_defaults(),
        profile="research-offline-v1",
        evidence=True,
    )
    await provider.write_evidence(sandbox.sandbox_id, f"{REF}.txt", b"original")
    session = await provider.open_session(sandbox.sandbox_id)

    # 계약 경로와 워크스페이스 경로 둘 다에서 읽힌다.
    read = await _python(session, f"print(open('/evidence/{REF}.txt').read())")
    assert (read.exit_code, read.stdout) == (0, b"original\n")
    assert await session.read_file(f"evidence/{REF}.txt") == b"original"

    # 고쳐 쓰기, 새 파일 끼워 넣기 -- 두 자리 모두 커널이 거절한다.
    for code in (
        f"open('/evidence/{REF}.txt', 'w').write('forged')",
        "open('/evidence/planted.txt', 'w').write('forged')",
        f"open('/workspace/evidence/{REF}.txt', 'w').write('forged')",
        "open('/workspace/evidence/planted.txt', 'w').write('forged')",
        f"import os; os.remove('/evidence/{REF}.txt')",
    ):
        attempt = await _python(session, code)
        assert attempt.exit_code != 0, code
        assert b"Read-only file system" in attempt.stderr, (code, attempt.stderr)
    with pytest.raises(SandboxUnavailable):
        await session.write_file(f"evidence/{REF}.txt", b"forged")

    after = await _python(
        session,
        "import os; print(sorted(os.listdir('/evidence')), "
        f"open('/evidence/{REF}.txt').read())",
    )
    assert after.stdout == f"['{REF}.txt'] original\n".encode()

    # 오케스트레이터 쪽 쓰기는 워커의 /evidence 에 바로 나타난다(§3.1 순서).
    await provider.write_evidence(sandbox.sandbox_id, "second0000000000.txt", b"2")
    listed = await _python(session, "import os; print(sorted(os.listdir('/evidence')))")
    assert listed.stdout == f"['{REF}.txt', 'second0000000000.txt']\n".encode()

    # 설정은 bridge 인데 인터페이스는 루프백뿐이고 바깥으로 나가지 못한다.
    interfaces = await _python(session, "import os; print(os.listdir('/sys/class/net'))")
    assert interfaces.stdout == b"['lo']\n"
    reach = await _python(
        session,
        "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)",
    )
    assert reach.exit_code != 0
    assert b"Network is unreachable" in reach.stderr


async def test_an_unsatisfiable_profile_creates_nothing(provider) -> None:
    owner = f"q_{uuid.uuid4().hex}"
    with pytest.raises(SandboxUnavailable, match="hard_workspace_quota_unavailable"):
        await provider.create(
            owner_id=owner,
            limits=SandboxLimits.safe_defaults(),
            profile="strict-workspace-quota-v1",
        )

    recovered = await provider.reconcile()
    assert [item for item in recovered if item.owner_id == owner] == []

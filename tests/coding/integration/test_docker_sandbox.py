import os
import shutil

import pytest

from neos.coding.sandbox.command import DockerCommandRunner
from neos.coding.sandbox.docker import DockerSandboxConfig, DockerSandboxProvider
from tests.coding.sandbox.conformance import SandboxProviderConformance


DOCKER_ENABLED = os.getenv("CODING_TEST_DOCKER") == "1"
DOCKER_IMAGE = os.getenv("CODING_TEST_DOCKER_IMAGE", "")
SKIP_REASON = (
    "set CODING_TEST_DOCKER=1, set a digest-pinned "
    "CODING_TEST_DOCKER_IMAGE, and install Docker to run sandbox conformance"
)

pytestmark = pytest.mark.skipif(
    not DOCKER_ENABLED or not DOCKER_IMAGE or shutil.which("docker") is None,
    reason=SKIP_REASON,
)


class TestDockerSandboxConformance(SandboxProviderConformance):
    @pytest.fixture
    async def provider(self, tmp_path):
        provider = DockerSandboxProvider(
            runner=DockerCommandRunner(),
            config=DockerSandboxConfig(
                image=DOCKER_IMAGE,
                snapshot_root=tmp_path / "snapshots",
            ),
        )
        try:
            yield provider
        finally:
            await provider.close()

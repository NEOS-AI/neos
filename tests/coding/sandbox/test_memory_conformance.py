from pathlib import Path

import pytest

from tests.coding.sandbox.conformance import (
    SandboxProviderConformance,
    memory_provider,
)


class TestMemorySandboxConformance(SandboxProviderConformance):
    @pytest.fixture
    async def provider(self, tmp_path: Path):
        async with memory_provider(tmp_path) as provider:
            yield provider

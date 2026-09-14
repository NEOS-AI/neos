"""The shared `SandboxProvider` conformance suite on managed E2B and Modal.

Both run on fake vendor SDKs over a real local `neos-sandboxd` and the
in-memory ledger. This is the B2 gate item 1 on fakes only; the same suite
against real accounts is still open (docs/PLAN_260913.md §B2).
"""

from pathlib import Path

import pytest

from tests.coding.sandbox.conformance import SandboxProviderConformance
from tests.coding.sandbox.managed_fakes import managed_stack

pytestmark = pytest.mark.no_db


class TestManagedE2BConformance(SandboxProviderConformance):
    @pytest.fixture
    async def provider(self, tmp_path: Path):
        async with managed_stack(tmp_path, "e2b") as stack:
            yield stack.provider


class TestManagedModalConformance(SandboxProviderConformance):
    @pytest.fixture
    async def provider(self, tmp_path: Path):
        async with managed_stack(tmp_path, "modal") as stack:
            yield stack.provider

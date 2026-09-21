"""The shared `SandboxProvider` conformance suite on managed E2B and Modal.

Both run on fake vendor SDKs over a real local `neos-sandboxd`, the in-memory
runtime ledger, and the real allocation / cleanup services. Every `create`
goes through admission and `advance()` first -- the managed provider only
attaches. This is B2 gate item 1 on fakes only; the same suite against real
accounts is still open (docs/PLAN_260913.md §B2).

One test differs from the shared contract, on purpose. 045 allows one live
allocation per task, so a managed restore cannot run next to its live source
for the same task. The managed variant restores into a prepared target
allocation after the source is cleaned up, and proves the refusal without one.
"""

from pathlib import Path

import pytest

from neos.coding.sandbox.base import SandboxLimits, SandboxUnavailable
from tests.coding.sandbox.conformance import SandboxProviderConformance
from tests.coding.sandbox.managed_fakes import ManagedStack, managed_stack

pytestmark = pytest.mark.no_db


class ProvisioningProvider:
    """Admits and allocates a task's sandbox before the provider attaches."""

    def __init__(self, stack: ManagedStack) -> None:
        self.stack = stack

    def __getattr__(self, name: str):
        return getattr(self.stack.provider, name)

    async def create(self, *, owner_id: str, limits: SandboxLimits):
        if await self.stack.ledger.allocation_for_task(owner_id) is None:
            await self.stack.provision(owner_id, limits=limits)
        return await self.stack.provider.create(owner_id=owner_id, limits=limits)


class _ManagedConformance(SandboxProviderConformance):
    async def test_snapshot_restore_is_independent(self, provider) -> None:
        stack: ManagedStack = provider.stack
        limits = SandboxLimits.safe_defaults()
        source = await provider.create(owner_id="u1", limits=limits)
        source_session = await provider.open_session(source.sandbox_id)
        await source_session.write_file("state.txt", b"v1")
        snapshot = await provider.snapshot(source.sandbox_id)

        with pytest.raises(SandboxUnavailable, match="managed_restore_target_required"):
            await provider.restore(snapshot.snapshot_id, owner_id="u1")

        source_allocation = await stack.allocation_of(source.sandbox_id)
        await provider.destroy(source.sandbox_id)
        await stack.cleanup(source_allocation.allocation_id)
        target = await stack.admit("u1", source_snapshot_id=snapshot.snapshot_id)
        await stack.advance(target.allocation_id)

        restored = await provider.restore(snapshot.snapshot_id, owner_id="u1")
        assert restored.sandbox_id != source.sandbox_id
        assert restored.workspace_revision == snapshot.workspace_revision
        restored_session = await provider.open_session(restored.sandbox_id)
        assert await restored_session.read_file("state.txt") == b"v1"
        await restored_session.write_file("state.txt", b"v2")
        assert (await stack.ledger.get_snapshot(snapshot.snapshot_id)).workspace_revision == 1


class TestManagedE2BConformance(_ManagedConformance):
    @pytest.fixture
    async def provider(self, tmp_path: Path):
        async with managed_stack(tmp_path, "e2b") as stack:
            yield ProvisioningProvider(stack)


class TestManagedModalConformance(_ManagedConformance):
    @pytest.fixture
    async def provider(self, tmp_path: Path):
        async with managed_stack(tmp_path, "modal") as stack:
            yield ProvisioningProvider(stack)

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from neos.coding.sandbox.base import (
    Sandbox,
    SandboxLimits,
    SandboxNotFound,
    SandboxState,
    Snapshot,
)
from neos.coding.sandbox.bindings import (
    SandboxBinding,
    SandboxBindingError,
    SandboxBindingService,
)


NOW = datetime(2026, 7, 19, 10, tzinfo=UTC)
LIMITS = SandboxLimits.safe_defaults()


def sandbox(
    sandbox_id: str,
    *,
    state: SandboxState = SandboxState.RUNNING,
    image_digest: str | None = "sha256:image",
    revision: int = 0,
) -> Sandbox:
    return Sandbox(
        sandbox_id=sandbox_id,
        owner_id="ct_1",
        state=state,
        limits=LIMITS,
        created_at=NOW,
        updated_at=NOW,
        workspace_revision=revision,
        provider="fake",
        image_digest=image_digest,
    )


def binding(
    *,
    sandbox_id: str = "sb_old",
    snapshot_id: str | None = None,
    version: int = 1,
    mutation_count: int = 0,
) -> SandboxBinding:
    return SandboxBinding(
        task_id="ct_1",
        run_id="cr_1",
        sandbox_id=sandbox_id,
        provider="fake",
        image_digest="sha256:image",
        workspace_revision="0",
        latest_snapshot_id=snapshot_id,
        health_state="healthy",
        mutation_count=mutation_count,
        version=version,
    )


class Repository:
    def __init__(self, current: SandboxBinding | None = None) -> None:
        self.current = current
        self.created: list[SandboxBinding] = []
        self.replaced: list[tuple[SandboxBinding, int]] = []
        self.deleted: list[tuple[str, int]] = []
        self.lose_next_cas_to: SandboxBinding | None = None

    async def get(self, task_id: str) -> SandboxBinding | None:
        return self.current if self.current and self.current.task_id == task_id else None

    async def create(self, value: SandboxBinding, *, now: datetime) -> bool:
        self.created.append(value)
        if self.current is not None:
            return False
        self.current = value
        return True

    async def replace(
        self, value: SandboxBinding, *, expected_version: int, now: datetime
    ) -> SandboxBinding | None:
        self.replaced.append((value, expected_version))
        if self.lose_next_cas_to is not None:
            self.current = self.lose_next_cas_to
            self.lose_next_cas_to = None
            return None
        if self.current is None or self.current.version != expected_version:
            return None
        self.current = replace(value, version=expected_version + 1)
        return self.current

    async def delete(self, task_id: str, *, expected_version: int) -> bool:
        self.deleted.append((task_id, expected_version))
        if self.current is None or self.current.version != expected_version:
            return False
        self.current = None
        return True


class Provider:
    def __init__(self, sandboxes: dict[str, Sandbox] | None = None) -> None:
        self.sandboxes = dict(sandboxes or {})
        self.calls: list[tuple[str, str]] = []
        self.session_ids: list[str] = []
        self.created_id = "sb_created"
        self.restored_id = "sb_restored"
        self.snapshot_number = 0

    async def create(self, *, owner_id: str, limits: SandboxLimits) -> Sandbox:
        self.calls.append(("create", owner_id))
        value = sandbox(self.created_id)
        self.sandboxes[value.sandbox_id] = value
        return value

    async def get(self, sandbox_id: str) -> Sandbox:
        self.calls.append(("get", sandbox_id))
        try:
            return self.sandboxes[sandbox_id]
        except KeyError as error:
            raise SandboxNotFound(sandbox_id) from error

    async def resume(self, sandbox_id: str) -> Sandbox:
        self.calls.append(("resume", sandbox_id))
        value = replace(self.sandboxes[sandbox_id], state=SandboxState.RUNNING)
        self.sandboxes[sandbox_id] = value
        return value

    async def restore(self, snapshot_id: str, *, owner_id: str) -> Sandbox:
        self.calls.append(("restore", snapshot_id))
        value = sandbox(self.restored_id, revision=4)
        self.sandboxes[value.sandbox_id] = value
        return value

    async def destroy(self, sandbox_id: str) -> None:
        self.calls.append(("destroy", sandbox_id))
        self.sandboxes.pop(sandbox_id, None)

    async def snapshot(self, sandbox_id: str) -> Snapshot:
        self.calls.append(("snapshot", sandbox_id))
        self.snapshot_number += 1
        return Snapshot(
            snapshot_id=f"ss_{self.snapshot_number}",
            source_sandbox_id=sandbox_id,
            workspace_revision=self.sandboxes[sandbox_id].workspace_revision,
            created_at=NOW,
            content_checksum="checksum",
            image_digest=self.sandboxes[sandbox_id].image_digest,
        )

    async def suspend(self, sandbox_id: str) -> Sandbox:
        self.calls.append(("suspend", sandbox_id))
        value = replace(self.sandboxes[sandbox_id], state=SandboxState.SUSPENDED)
        self.sandboxes[sandbox_id] = value
        return value

    async def open_session(self, sandbox_id: str):
        self.calls.append(("open_session", sandbox_id))
        self.session_ids.append(sandbox_id)
        return object()


def service(repository: Repository, provider: Provider, *, cadence: int = 2):
    return SandboxBindingService(
        repository=repository,
        provider=provider,
        limits=LIMITS,
        snapshot_cadence=cadence,
        image_digest="sha256:image",
        clock=lambda: NOW,
    )


async def test_new_creation_is_persisted_before_session_open() -> None:
    repository = Repository()
    provider = Provider()

    bound = await service(repository, provider).resolve("ct_1", "cr_1")

    assert bound.binding.sandbox_id == "sb_created"
    assert repository.created == [bound.binding]
    assert provider.calls == [
        ("create", "ct_1"),
        ("open_session", "sb_created"),
    ]


async def test_healthy_running_sandbox_is_reused() -> None:
    repository = Repository(binding())
    provider = Provider({"sb_old": sandbox("sb_old")})

    bound = await service(repository, provider).resolve("ct_1", "cr_2")

    assert bound.binding.sandbox_id == "sb_old"
    assert bound.binding.run_id == "cr_2"
    assert provider.calls == [("get", "sb_old"), ("open_session", "sb_old")]


async def test_suspended_sandbox_is_resumed() -> None:
    repository = Repository(binding())
    provider = Provider({"sb_old": sandbox("sb_old", state=SandboxState.SUSPENDED)})

    await service(repository, provider).resolve("ct_1", "cr_2")

    assert ("resume", "sb_old") in provider.calls


async def test_missing_sandbox_restores_latest_snapshot_and_swaps_binding() -> None:
    repository = Repository(binding(snapshot_id="ss_latest"))
    provider = Provider()

    bound = await service(repository, provider).resolve("ct_1", "cr_2")

    assert bound.binding.sandbox_id == "sb_restored"
    assert bound.binding.version == 2
    assert ("restore", "ss_latest") in provider.calls


async def test_missing_sandbox_without_snapshot_is_retryable_error() -> None:
    repository = Repository(binding())

    with pytest.raises(SandboxBindingError) as raised:
        await service(repository, Provider()).resolve("ct_1", "cr_2")

    assert raised.value.code == "sandbox_unrecoverable"
    assert raised.value.retryable is True


async def test_image_mismatch_is_rejected() -> None:
    repository = Repository(binding())
    provider = Provider({"sb_old": sandbox("sb_old", image_digest="sha256:other")})

    with pytest.raises(SandboxBindingError) as raised:
        await service(repository, provider).resolve("ct_1", "cr_2")

    assert raised.value.code == "sandbox_image_mismatch"
    assert raised.value.retryable is False


async def test_cas_loser_destroys_only_newly_restored_sandbox() -> None:
    winner = binding(sandbox_id="sb_winner", snapshot_id="ss_latest", version=2)
    repository = Repository(binding(snapshot_id="ss_latest"))
    repository.lose_next_cas_to = winner
    provider = Provider({"sb_winner": sandbox("sb_winner")})

    bound = await service(repository, provider).resolve("ct_1", "cr_2")

    assert bound.binding.sandbox_id == "sb_winner"
    assert ("destroy", "sb_restored") in provider.calls
    assert ("destroy", "sb_winner") not in provider.calls


async def test_successful_mutations_snapshot_at_cadence() -> None:
    repository = Repository(binding())
    provider = Provider({"sb_old": sandbox("sb_old", revision=2)})
    subject = service(repository, provider, cadence=2)

    first = await subject.record_mutation("ct_1", workspace_revision=1)
    second = await subject.record_mutation("ct_1", workspace_revision=2)

    assert first.latest_snapshot_id is None
    assert second.latest_snapshot_id == "ss_1"
    assert second.mutation_count == 0


async def test_suspend_snapshots_before_provider_suspend() -> None:
    repository = Repository(binding(mutation_count=1))
    provider = Provider({"sb_old": sandbox("sb_old", revision=1)})

    updated = await service(repository, provider).suspend("ct_1")

    assert updated.latest_snapshot_id == "ss_1"
    assert provider.calls[-2:] == [("snapshot", "sb_old"), ("suspend", "sb_old")]


async def test_terminal_destruction_removes_binding_after_destroy() -> None:
    repository = Repository(binding())
    provider = Provider({"sb_old": sandbox("sb_old")})

    await service(repository, provider).destroy_terminal("ct_1")

    assert provider.calls == [("destroy", "sb_old")]
    assert repository.current is None

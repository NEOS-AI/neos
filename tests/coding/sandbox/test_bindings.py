from dataclasses import replace
from datetime import UTC, datetime

import pytest

from neos.coding.domain.durability import ExecutionLease
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


def lease(run_id: str = "cr_1", *, token: int = 1) -> ExecutionLease:
    return ExecutionLease(
        "ct_1",
        run_id,
        "worker",
        token,
        NOW,
        datetime(2026, 7, 19, 10, 1, tzinfo=UTC),
    )


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
    health_state: str = "healthy",
    workspace_revision: str = "0",
) -> SandboxBinding:
    return SandboxBinding(
        task_id="ct_1",
        run_id="cr_1",
        sandbox_id=sandbox_id,
        provider="fake",
        image_digest="sha256:image",
        workspace_revision=workspace_revision,
        latest_snapshot_id=snapshot_id,
        health_state=health_state,
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
        self.stale = False

    async def get(self, task_id: str) -> SandboxBinding | None:
        return self.current if self.current and self.current.task_id == task_id else None

    async def create_fenced(
        self, value: SandboxBinding, *, lease, now: datetime
    ) -> bool:
        self.created.append(value)
        if self.current is not None:
            return False
        self.current = value
        return True

    async def validate_fenced(self, *, lease, now: datetime) -> None:
        if self.stale or lease.expires_at <= now:
            from neos.coding.domain.durability import StaleExecutionLease

            raise StaleExecutionLease(lease.task_id)

    async def replace_fenced(
        self,
        value: SandboxBinding,
        *,
        expected_version: int,
        now: datetime,
        lease,
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

    async def replace_admin(
        self, value: SandboxBinding, *, expected_version: int, now: datetime
    ) -> SandboxBinding | None:
        return await self.replace_fenced(
            value,
            expected_version=expected_version,
            lease=lease_for_binding(value),
            now=now,
        )

    async def delete_admin(self, task_id: str, *, expected_version: int) -> bool:
        self.deleted.append((task_id, expected_version))
        if self.current is None or self.current.version != expected_version:
            return False
        self.current = None
        return True


def lease_for_binding(value: SandboxBinding) -> ExecutionLease:
    return lease(value.run_id)


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

    bound = await service(repository, provider).resolve(lease("cr_1"))

    assert bound.binding.sandbox_id == "sb_created"
    assert repository.created == [bound.binding]
    assert provider.calls == [
        ("create", "ct_1"),
        ("open_session", "sb_created"),
    ]


async def test_healthy_running_sandbox_is_reused() -> None:
    repository = Repository(binding())
    provider = Provider({"sb_old": sandbox("sb_old")})

    bound = await service(repository, provider).resolve(lease("cr_2"))

    assert bound.binding.sandbox_id == "sb_old"
    assert bound.binding.run_id == "cr_2"
    assert provider.calls == [("get", "sb_old"), ("open_session", "sb_old")]


async def test_suspended_sandbox_is_resumed() -> None:
    repository = Repository(binding(health_state="suspended"))
    provider = Provider({"sb_old": sandbox("sb_old", state=SandboxState.SUSPENDED)})

    bound = await service(repository, provider).resolve(lease("cr_1"))

    assert ("resume", "sb_old") in provider.calls
    assert bound.binding.health_state == "healthy"
    assert repository.current == bound.binding


async def test_stale_lease_cannot_resume_suspended_sandbox() -> None:
    repository = Repository(binding(health_state="suspended"))
    repository.stale = True
    provider = Provider({"sb_old": sandbox("sb_old", state=SandboxState.SUSPENDED)})

    from neos.coding.domain.durability import StaleExecutionLease

    with pytest.raises(StaleExecutionLease):
        await service(repository, provider).resolve(lease())

    assert provider.sandboxes["sb_old"].state is SandboxState.SUSPENDED
    assert ("resume", "sb_old") not in provider.calls


async def test_suspended_sandbox_resume_persists_health_and_changed_run() -> None:
    repository = Repository(binding(health_state="suspended"))
    provider = Provider({"sb_old": sandbox("sb_old", state=SandboxState.SUSPENDED)})

    bound = await service(repository, provider).resolve(lease("cr_2"))

    assert bound.binding.health_state == "healthy"
    assert bound.binding.run_id == "cr_2"
    assert repository.current == bound.binding


@pytest.mark.parametrize(
    ("sandbox_state", "health_state", "run_id", "expected_lifecycle_call"),
    [
        (SandboxState.RUNNING, "healthy", "cr_2", None),
        (SandboxState.SUSPENDED, "suspended", "cr_1", ("resume", "sb_old")),
    ],
)
async def test_reuse_cas_loss_to_terminal_does_not_recreate_or_destroy(
    sandbox_state: SandboxState,
    health_state: str,
    run_id: str,
    expected_lifecycle_call: tuple[str, str] | None,
) -> None:
    class TerminalRaceRepository(Repository):
        async def replace_fenced(
            self, value, *, expected_version, lease, now
        ):
            self.current = None
            return None

    repository = TerminalRaceRepository(binding(health_state=health_state))
    provider = Provider({"sb_old": sandbox("sb_old", state=sandbox_state)})

    with pytest.raises(SandboxBindingError) as raised:
        await service(repository, provider).resolve(lease(run_id))

    assert raised.value.code == "sandbox_binding_ownership_lost"
    assert raised.value.retryable is False
    assert ("create", "ct_1") not in provider.calls
    assert ("destroy", "sb_old") not in provider.calls
    if expected_lifecycle_call is not None:
        assert expected_lifecycle_call in provider.calls


async def test_missing_sandbox_restores_latest_snapshot_and_swaps_binding() -> None:
    repository = Repository(binding(snapshot_id="ss_latest"))
    provider = Provider()

    bound = await service(repository, provider).resolve(lease("cr_2"))

    assert bound.binding.sandbox_id == "sb_restored"
    assert bound.binding.version == 2
    assert ("restore", "ss_latest") in provider.calls


async def test_missing_sandbox_without_snapshot_is_retryable_error() -> None:
    repository = Repository(binding())

    with pytest.raises(SandboxBindingError) as raised:
        await service(repository, Provider()).resolve(lease("cr_2"))

    assert raised.value.code == "sandbox_unrecoverable"
    assert raised.value.retryable is True


async def test_image_mismatch_is_rejected() -> None:
    repository = Repository(binding())
    provider = Provider({"sb_old": sandbox("sb_old", image_digest="sha256:other")})

    with pytest.raises(SandboxBindingError) as raised:
        await service(repository, provider).resolve(lease("cr_2"))

    assert raised.value.code == "sandbox_image_mismatch"
    assert raised.value.retryable is False


async def test_cas_loser_destroys_only_newly_restored_sandbox() -> None:
    winner = binding(sandbox_id="sb_winner", snapshot_id="ss_latest", version=2)
    repository = Repository(binding(snapshot_id="ss_latest"))
    repository.lose_next_cas_to = winner
    provider = Provider({"sb_winner": sandbox("sb_winner")})

    bound = await service(repository, provider).resolve(lease("cr_2"))

    assert bound.binding.sandbox_id == "sb_winner"
    assert ("destroy", "sb_restored") in provider.calls
    assert ("destroy", "sb_winner") not in provider.calls


async def test_restore_cas_loss_to_terminal_does_not_recreate() -> None:
    class TerminalRaceRepository(Repository):
        async def replace_fenced(
            self, value, *, expected_version, lease, now
        ):
            self.current = None
            return None

    repository = TerminalRaceRepository(binding(snapshot_id="ss_latest"))
    provider = Provider()

    with pytest.raises(SandboxBindingError) as raised:
        await service(repository, provider).resolve(lease("cr_2"))

    assert raised.value.code == "sandbox_binding_ownership_lost"
    assert raised.value.retryable is False
    assert provider.calls == [
        ("get", "sb_old"),
        ("restore", "ss_latest"),
        ("destroy", "sb_restored"),
    ]


async def test_successful_mutations_snapshot_at_cadence() -> None:
    repository = Repository(binding())
    provider = Provider({"sb_old": sandbox("sb_old", revision=2)})
    subject = service(repository, provider, cadence=2)

    first = await subject.record_mutation(lease(), workspace_revision=1)
    second = await subject.record_mutation(lease(), workspace_revision=2)

    assert first.latest_snapshot_id is None
    assert second.latest_snapshot_id == "ss_1"
    assert second.mutation_count == 0


async def test_mutation_cas_conflict_reconciles_winner_and_snapshots_once() -> None:
    winner = binding(
        version=2,
        mutation_count=1,
        workspace_revision="4",
    )
    repository = Repository(binding())
    repository.lose_next_cas_to = winner
    provider = Provider({"sb_old": sandbox("sb_old", revision=5)})

    updated = await service(repository, provider, cadence=2).record_mutation(
        lease(), workspace_revision=5
    )

    assert updated.workspace_revision == "5"
    assert updated.mutation_count == 0
    assert updated.latest_snapshot_id == "ss_1"
    assert provider.calls == [("snapshot", "sb_old")]


async def test_mutation_cas_conflict_with_changed_owner_is_nonretryable() -> None:
    winner = binding(sandbox_id="sb_winner", version=2)
    repository = Repository(binding())
    repository.lose_next_cas_to = winner
    provider = Provider({"sb_old": sandbox("sb_old", revision=5)})

    with pytest.raises(SandboxBindingError) as raised:
        await service(repository, provider, cadence=3).record_mutation(
            lease(), workspace_revision=5
        )

    assert raised.value.code == "sandbox_mutation_bookkeeping_lost"
    assert raised.value.retryable is False


async def test_mutation_cas_conflict_with_deleted_binding_is_nonretryable() -> None:
    class DeletedRaceRepository(Repository):
        async def replace_fenced(
            self, value, *, expected_version, lease, now
        ):
            self.current = None
            return None

    repository = DeletedRaceRepository(binding())
    provider = Provider({"sb_old": sandbox("sb_old", revision=5)})

    with pytest.raises(SandboxBindingError) as raised:
        await service(repository, provider, cadence=3).record_mutation(
            lease(), workspace_revision=5
        )

    assert raised.value.code == "sandbox_mutation_bookkeeping_lost"
    assert raised.value.retryable is False


async def test_mutation_same_owner_conflicts_are_bounded_and_retryable() -> None:
    class BusyRepository(Repository):
        async def replace_fenced(
            self, value, *, expected_version, lease, now
        ):
            assert self.current is not None
            self.current = replace(self.current, version=self.current.version + 1)
            return None

    repository = BusyRepository(binding())
    provider = Provider({"sb_old": sandbox("sb_old", revision=5)})

    with pytest.raises(SandboxBindingError) as raised:
        await service(repository, provider, cadence=10).record_mutation(
            lease(), workspace_revision=5
        )

    assert raised.value.code == "sandbox_mutation_bookkeeping_conflict"
    assert raised.value.retryable is True
    assert repository.current is not None and repository.current.version == 4


async def test_create_repository_exception_destroys_allocated_sandbox() -> None:
    class FailingRepository(Repository):
        async def create_fenced(self, value, *, lease, now):
            raise RuntimeError("sandbox id conflict")

    provider = Provider()

    with pytest.raises(RuntimeError, match="sandbox id conflict"):
        await service(FailingRepository(), provider).resolve(lease("cr_1"))

    assert provider.calls == [("create", "ct_1"), ("destroy", "sb_created")]


async def test_create_compatibility_failure_destroys_allocated_sandbox() -> None:
    class WrongImageProvider(Provider):
        async def create(self, *, owner_id, limits):
            value = await super().create(owner_id=owner_id, limits=limits)
            value = replace(value, image_digest="sha256:other")
            self.sandboxes[value.sandbox_id] = value
            return value

    provider = WrongImageProvider()

    with pytest.raises(SandboxBindingError, match="sandbox_image_mismatch"):
        await service(Repository(), provider).resolve(lease("cr_1"))

    assert provider.calls == [("create", "ct_1"), ("destroy", "sb_created")]


async def test_create_cas_loser_destroys_only_allocated_sandbox() -> None:
    winner = binding(sandbox_id="sb_winner")

    class CreateRaceRepository(Repository):
        def __init__(self):
            super().__init__()
            self.first_get = True

        async def get(self, task_id):
            if self.first_get:
                self.first_get = False
                return None
            return await super().get(task_id)

        async def create_fenced(self, value, *, lease, now):
            self.current = winner
            return False

    repository = CreateRaceRepository()
    provider = Provider({"sb_winner": sandbox("sb_winner")})

    bound = await service(repository, provider).resolve(lease("cr_1"))

    assert bound.binding.sandbox_id == "sb_winner"
    assert ("destroy", "sb_created") in provider.calls
    assert ("destroy", "sb_winner") not in provider.calls


async def test_suspend_snapshots_before_provider_suspend() -> None:
    repository = Repository(binding(mutation_count=1))
    provider = Provider({"sb_old": sandbox("sb_old", revision=1)})

    updated = await service(repository, provider).suspend_admin("ct_1")

    assert updated.latest_snapshot_id == "ss_1"
    assert provider.calls[-2:] == [("snapshot", "sb_old"), ("suspend", "sb_old")]


async def test_terminal_destruction_removes_binding_after_destroy() -> None:
    log = []

    class OrderedRepository(Repository):
        async def delete_admin(self, task_id, *, expected_version):
            log.append("delete")
            return await super().delete_admin(
                task_id, expected_version=expected_version
            )

    class OrderedProvider(Provider):
        async def destroy(self, sandbox_id):
            log.append("destroy")
            await super().destroy(sandbox_id)

    repository = OrderedRepository(binding())
    provider = OrderedProvider({"sb_old": sandbox("sb_old")})

    await service(repository, provider).destroy_terminal_admin("ct_1")

    assert provider.calls == [("destroy", "sb_old")]
    assert repository.current is None
    assert log == ["delete", "destroy"]

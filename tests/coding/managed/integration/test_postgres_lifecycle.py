"""Task 6이 새로 낸 SQL 을 **실제 Postgres** 에서 확인한다.

`test_lifecycle.py`가 보는 것은 판정이고, 이 파일이 보는 것은 그 판정이
기대는 SQL 이다 -- 조인 조건, 상태 필터, 045의 CHECK 제약, 그리고 상태 전이와
시도 기록이 정말로 **한 트랜잭션**인지.

발행되는 SQL 만 읽어서는 원리적으로 못 잡는 종류가 여기 있다 (2026-08-19에
`coding_checkpoints_task_id_seq_key` 위반을 그렇게 처음 잡았다).
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from neos.coding.managed.allocation import (
    ManagedSandboxNotFound,
    StaleManagedSandboxLease,
)
from neos.coding.managed.domain import ManagedSandboxState, ProviderErrorCode
from neos.coding.managed.lifecycle import CleanupAttemptOutcome
from neos.coding.managed.repository import PostgresManagedSandboxRepository


NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)


async def _seed_allocation(
    session_factory,
    allocation_id: str,
    *,
    state: str = "active",
    task_status: str = "running",
    task_deleted: bool = False,
    absolute_expires_at: datetime = NOW + timedelta(hours=1),
    lease_expires_at: datetime | None = None,
    provider_ref: bytes | None = b"sealed",
    ownership_digest: str | None = "sha256:seed",
) -> str:
    """할당 하나를 원하는 상태로 심는다. `task_id`를 돌려준다.

    `created_at`은 `absolute_expires_at`에서 거꾸로 잡는다 -- 045의
    `CHECK (absolute_expires_at > created_at)` 때문이다. 이미 만료가 지난
    행을 `created_at = NOW`로 심으려 하면 제약이 거부하는데, 그건 제품 결함이
    아니라 **프로덕션에서 그런 행이 만들어지는 순서**를 픽스처가 어긴 것이다:
    실제로는 한 시간 전에 만들어진 샌드박스의 TTL 이 방금 지나는 것이지,
    지금 만들어지면서 이미 만료돼 있는 것이 아니다.
    """
    created_at = min(NOW, absolute_expires_at) - timedelta(hours=1)
    task_id = f"ct_{uuid4().hex}"
    run_id = f"cr_{uuid4().hex}"
    admission_id = f"adm_{uuid4().hex}"
    async with await session_factory() as session:
        async with session.begin():
            owner = await session.execute(text("SELECT user_id FROM users LIMIT 1"))
            owner_row = owner.first()
            if owner_row is None:
                pytest.skip("prepared PostgreSQL schema has no test user")
            await session.execute(
                text(
                    """
                    INSERT INTO coding_tasks
                        (task_id, owner_id, prompt, status, version, last_seq,
                         created_at, updated_at, last_activity_at, deleted_at)
                    VALUES
                        (:task_id, :owner_id, 'Fix it', :status, 1, 0,
                         :now, :now, :now, :deleted_at)
                    """
                ),
                {
                    "task_id": task_id,
                    "owner_id": owner_row[0],
                    "status": task_status,
                    "deleted_at": NOW if task_deleted else None,
                    "now": NOW,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO coding_runs
                        (run_id, task_id, attempt, status, started_at)
                    VALUES (:run_id, :task_id, 1, 'running', :now)
                    """
                ),
                {"run_id": run_id, "task_id": task_id, "now": NOW},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO coding_sandbox_admissions (
                        admission_id, idempotency_key, tenant_id, task_id,
                        provider, region, policy_version, decision, reason,
                        reservation_id, reservation_expires_at,
                        reservation_state, created_at
                    ) VALUES (
                        :admission_id, :idempotency_key, 'tenant_1', :task_id,
                        'fake', 'local', 'managed-v1', 'admitted', 'allowed',
                        :reservation_id, :reservation_expires_at, 'reserved',
                        :now
                    )
                    """
                ),
                {
                    "admission_id": admission_id,
                    "idempotency_key": f"idem_{allocation_id}",
                    "task_id": task_id,
                    "reservation_id": f"rsv_{allocation_id}",
                    "reservation_expires_at": absolute_expires_at,
                    "now": NOW,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO coding_managed_sandboxes (
                        allocation_id, admission_id, tenant_id, task_id,
                        run_id, provider, region, provider_ref,
                        ownership_digest, state, generation, fencing_token,
                        lease_expires_at, absolute_expires_at, version,
                        created_at, updated_at
                    ) VALUES (
                        :allocation_id, :admission_id, 'tenant_1', :task_id,
                        :run_id, 'fake', 'local', :provider_ref,
                        :ownership_digest, :state, 1, 1, :lease_expires_at,
                        :absolute_expires_at, 1, :created_at, :created_at
                    )
                    """
                ),
                {
                    "allocation_id": allocation_id,
                    "admission_id": admission_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "provider_ref": provider_ref,
                    "ownership_digest": ownership_digest,
                    "state": state,
                    "lease_expires_at": lease_expires_at,
                    "absolute_expires_at": absolute_expires_at,
                    "created_at": created_at,
                },
            )
    return task_id


@pytest.mark.integration
async def test_a_terminal_task_promotes_its_sandbox_to_cleanup_pending(
    managed_postgres_session_factory,
) -> None:
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_allocation(
        managed_postgres_session_factory, "msa_1", task_status="completed"
    )

    candidates = await repo.discover_lifecycle_candidates(now=NOW, limit=10)

    assert [item.allocation_id for item in candidates.cleanup] == ["msa_1"]
    assert (await repo.read_allocation("msa_1")).state is (
        ManagedSandboxState.CLEANUP_PENDING
    )


@pytest.mark.integration
async def test_a_deleted_task_promotes_its_sandbox(
    managed_postgres_session_factory,
) -> None:
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_allocation(
        managed_postgres_session_factory, "msa_1", task_deleted=True
    )

    candidates = await repo.discover_lifecycle_candidates(now=NOW, limit=10)

    assert [item.allocation_id for item in candidates.cleanup] == ["msa_1"]


@pytest.mark.integration
async def test_absolute_expiry_promotes_even_while_the_task_still_runs(
    managed_postgres_session_factory,
) -> None:
    """절대 TTL 은 태스크가 살아 있어도 적용된다 -- 그게 상한의 의미다."""
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_allocation(
        managed_postgres_session_factory,
        "msa_1",
        task_status="running",
        absolute_expires_at=NOW - timedelta(seconds=1),
    )

    candidates = await repo.discover_lifecycle_candidates(now=NOW, limit=10)

    assert [item.allocation_id for item in candidates.cleanup] == ["msa_1"]


@pytest.mark.integration
async def test_a_running_task_within_its_ttl_is_left_alone(
    managed_postgres_session_factory,
) -> None:
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_allocation(managed_postgres_session_factory, "msa_1")

    candidates = await repo.discover_lifecycle_candidates(now=NOW, limit=10)

    assert candidates.cleanup == ()
    assert candidates.recovery == ()


@pytest.mark.integration
async def test_a_stalled_allocation_comes_back_as_a_recovery_candidate(
    managed_postgres_session_factory,
) -> None:
    """리스가 만료된 ALLOCATING 은 정리가 아니라 **전진** 대상이다."""
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_allocation(
        managed_postgres_session_factory,
        "msa_1",
        state="allocating",
        lease_expires_at=NOW - timedelta(seconds=1),
    )

    candidates = await repo.discover_lifecycle_candidates(now=NOW, limit=10)

    assert candidates.cleanup == ()
    assert candidates.recovery == ("msa_1",)


@pytest.mark.integration
async def test_a_live_lease_is_not_rediscovered(
    managed_postgres_session_factory,
) -> None:
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_allocation(
        managed_postgres_session_factory,
        "msa_1",
        state="cleanup_pending",
        lease_expires_at=NOW + timedelta(seconds=60),
    )

    candidates = await repo.discover_lifecycle_candidates(now=NOW, limit=10)

    assert candidates.cleanup == ()


@pytest.mark.integration
async def test_a_retry_that_is_not_due_yet_is_not_rediscovered(
    managed_postgres_session_factory,
) -> None:
    """백오프가 실제로 지켜지는지 -- 시도 행의 next_retry_at 이 필터가 된다."""
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_allocation(
        managed_postgres_session_factory, "msa_1", state="cleanup_pending"
    )
    lease = await repo.claim_allocation(
        "msa_1", "cleanup_1", now=NOW, lease_seconds=60
    )
    await repo.commit_cleanup_outcome(
        lease,
        target=ManagedSandboxState.CLEANUP_RETRY,
        outcome=CleanupAttemptOutcome.UNCONFIRMED,
        error_code=ProviderErrorCode.CLEANUP_UNCONFIRMED,
        retry_at=NOW + timedelta(seconds=45),
        started_at=NOW,
        now=NOW,
    )

    too_early = await repo.discover_lifecycle_candidates(now=NOW, limit=10)
    due = await repo.discover_lifecycle_candidates(
        now=NOW + timedelta(seconds=46), limit=10
    )

    assert too_early.cleanup == ()
    assert [item.allocation_id for item in due.cleanup] == ["msa_1"]


@pytest.mark.integration
async def test_cleanup_attempt_count_tracks_recorded_attempts(
    managed_postgres_session_factory,
) -> None:
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_allocation(
        managed_postgres_session_factory, "msa_1", state="cleanup_pending"
    )
    assert await repo.cleanup_attempt_count("msa_1") == 0

    lease = await repo.claim_allocation(
        "msa_1", "cleanup_1", now=NOW, lease_seconds=60
    )
    await repo.commit_cleanup_outcome(
        lease,
        target=ManagedSandboxState.CLEANUP_RETRY,
        outcome=CleanupAttemptOutcome.RETRY,
        error_code=ProviderErrorCode.PROVIDER_TIMEOUT,
        retry_at=NOW + timedelta(seconds=5),
        started_at=NOW,
        now=NOW,
    )

    assert await repo.cleanup_attempt_count("msa_1") == 1


@pytest.mark.integration
async def test_cleaned_clears_the_provider_reference_and_sets_cleaned_at(
    managed_postgres_session_factory,
) -> None:
    """045의 CHECK 제약이 이것을 요구한다 -- 안 지우면 UPDATE 자체가 거부된다."""
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_allocation(
        managed_postgres_session_factory, "msa_1", state="cleanup_pending"
    )
    lease = await repo.claim_allocation(
        "msa_1", "cleanup_1", now=NOW, lease_seconds=60
    )

    allocation = await repo.commit_cleanup_outcome(
        lease,
        target=ManagedSandboxState.CLEANED,
        outcome=CleanupAttemptOutcome.CLEANED,
        error_code=None,
        retry_at=None,
        started_at=NOW,
        now=NOW,
    )

    assert allocation.state is ManagedSandboxState.CLEANED
    assert allocation.provider_ref is None
    assert allocation.ownership_digest is None
    assert allocation.lease_expires_at is None
    async with await managed_postgres_session_factory() as session:
        cleaned_at = (
            await session.execute(
                text(
                    "SELECT cleaned_at FROM coding_managed_sandboxes "
                    "WHERE allocation_id = 'msa_1'"
                )
            )
        ).scalar_one()
    assert cleaned_at is not None


@pytest.mark.integration
async def test_a_stale_fence_writes_neither_state_nor_attempt(
    managed_postgres_session_factory,
) -> None:
    """전이와 시도 기록이 한 트랜잭션이라는 것의 실제 증명.

    낡은 펜스로 커밋하면 UPDATE 가 0행이고 예외가 나는데, 그때 시도 행이
    남아 있으면 백오프 인덱스만 전진해 다음 정리가 엉뚱하게 오래 기다린다.
    """
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_allocation(
        managed_postgres_session_factory,
        "msa_1",
        state="cleanup_pending",
    )
    stale = await repo.claim_allocation(
        "msa_1", "cleanup_1", now=NOW, lease_seconds=1
    )
    later = NOW + timedelta(seconds=2)
    await repo.claim_allocation("msa_1", "cleanup_2", now=later, lease_seconds=60)

    with pytest.raises(StaleManagedSandboxLease):
        await repo.commit_cleanup_outcome(
            stale,
            target=ManagedSandboxState.CLEANED,
            outcome=CleanupAttemptOutcome.CLEANED,
            error_code=None,
            retry_at=None,
            started_at=later,
            now=later,
        )

    assert await repo.cleanup_attempt_count("msa_1") == 0
    assert (await repo.read_allocation("msa_1")).state is (
        ManagedSandboxState.CLEANUP_PENDING
    )


@pytest.mark.integration
async def test_reading_an_unknown_allocation_raises_not_found(
    managed_postgres_session_factory,
) -> None:
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)

    with pytest.raises(ManagedSandboxNotFound):
        await repo.read_allocation("msa_missing")

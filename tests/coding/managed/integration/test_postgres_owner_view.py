"""소유자 범위 조회와 정리 재시도 해제의 SQL 을 실제 Postgres 에서 확인한다.

특히 `read_owner_sandbox`는 **소유권 검사가 질의 안에 있다**는 것이 요점이라,
조인 조건이 실제로 걸리는지는 fake 로 증명할 수 없다.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from neos.coding.managed.allocation import (
    ManagedSandboxNotClaimable,
    ManagedSandboxNotFound,
)
from neos.coding.managed.domain import ManagedSandboxState
from neos.coding.managed.lifecycle import CleanupAttemptOutcome
from neos.coding.managed.repository import PostgresManagedSandboxRepository


NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)


async def _seed(
    session_factory,
    allocation_id: str,
    *,
    state: str = "active",
    owner_id: str | None = None,
    task_deleted: bool = False,
    generation: int = 1,
) -> tuple[str, str]:
    """할당 하나를 심고 (owner_id, task_id) 를 돌려준다."""
    task_id = f"ct_{uuid4().hex}"
    run_id = f"cr_{uuid4().hex}"
    admission_id = f"adm_{uuid4().hex}"
    async with await session_factory() as session:
        async with session.begin():
            if owner_id is None:
                owner = await session.execute(
                    text("SELECT user_id FROM users LIMIT 1")
                )
                owner_row = owner.first()
                if owner_row is None:
                    pytest.skip("prepared PostgreSQL schema has no test user")
                owner_id = str(owner_row[0])
            await session.execute(
                text(
                    """
                    INSERT INTO coding_tasks
                        (task_id, owner_id, prompt, status, version, last_seq,
                         created_at, updated_at, last_activity_at, deleted_at)
                    VALUES
                        (:task_id, :owner_id, 'Fix it', 'running', 1, 0,
                         :now, :now, :now, :deleted_at)
                    """
                ),
                {
                    "task_id": task_id,
                    "owner_id": owner_id,
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
                        :reservation_id, :expires_at, 'reserved', :now
                    )
                    """
                ),
                {
                    "admission_id": admission_id,
                    "idempotency_key": f"idem_{allocation_id}",
                    "task_id": task_id,
                    "reservation_id": f"rsv_{allocation_id}",
                    "expires_at": NOW + timedelta(hours=1),
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
                        'sha256:seed', :state, :generation, 1, NULL,
                        :expires_at, 1, :now, :now
                    )
                    """
                ),
                {
                    "allocation_id": allocation_id,
                    "admission_id": admission_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "provider_ref": b"sealed",
                    "state": state,
                    "generation": generation,
                    "expires_at": NOW + timedelta(hours=1),
                    "now": NOW,
                },
            )
    return owner_id, task_id


@pytest.mark.integration
async def test_the_owner_sees_their_sandbox(
    managed_postgres_session_factory,
) -> None:
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    owner_id, task_id = await _seed(managed_postgres_session_factory, "msa_1")

    found = await repo.read_owner_sandbox(task_id=task_id, owner_id=owner_id)

    assert found is not None
    allocation, updated_at = found
    assert allocation.allocation_id == "msa_1"
    assert allocation.state is ManagedSandboxState.ACTIVE
    assert updated_at == NOW


@pytest.mark.integration
async def test_a_non_owner_sees_nothing(
    managed_postgres_session_factory,
) -> None:
    """소유권 검사가 질의 안에 있다는 것의 실제 증명."""
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    _owner_id, task_id = await _seed(managed_postgres_session_factory, "msa_1")

    found = await repo.read_owner_sandbox(task_id=task_id, owner_id="intruder")

    assert found is None


@pytest.mark.integration
async def test_a_deleted_task_hides_its_sandbox(
    managed_postgres_session_factory,
) -> None:
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    owner_id, task_id = await _seed(
        managed_postgres_session_factory, "msa_1", task_deleted=True
    )

    assert await repo.read_owner_sandbox(task_id=task_id, owner_id=owner_id) is None


@pytest.mark.integration
async def test_the_latest_generation_wins(
    managed_postgres_session_factory,
) -> None:
    """복구를 거친 태스크는 **새 세대**를 보여야 한다.

    옛 세대를 보여주면 사용자는 이미 닫힌 샌드박스의 상태를 본다.
    """
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    owner_id, task_id = await _seed(
        managed_postgres_session_factory, "msa_1", state="failed"
    )
    # 같은 태스크에 세대 2를 붙인다 -- 부분 유니크 인덱스는 세대 1이 failed 라
    # 통과시킨다.
    admission_id = f"adm_{uuid4().hex}"
    async with await managed_postgres_session_factory() as session:
        async with session.begin():
            run_id = (
                await session.execute(
                    text(
                        "SELECT run_id FROM coding_managed_sandboxes "
                        "WHERE allocation_id = 'msa_1'"
                    )
                )
            ).scalar_one()
            await session.execute(
                text(
                    """
                    INSERT INTO coding_sandbox_admissions (
                        admission_id, idempotency_key, tenant_id, task_id,
                        provider, region, policy_version, decision, reason,
                        reservation_id, reservation_expires_at,
                        reservation_state, created_at
                    ) VALUES (
                        :admission_id, 'recovery:msa_1:g2', 'tenant_1',
                        :task_id, 'fake', 'local', 'managed-v1', 'admitted',
                        'allowed', :reservation_id, :expires_at, 'reserved',
                        :now
                    )
                    """
                ),
                {
                    "admission_id": admission_id,
                    "task_id": task_id,
                    "reservation_id": f"rsv_{uuid4().hex}",
                    "expires_at": NOW + timedelta(hours=1),
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
                        'msa_2', :admission_id, 'tenant_1', :task_id, :run_id,
                        'fake', 'local', NULL, NULL, 'admitted', 2, 1, NULL,
                        :expires_at, 1, :now, :now
                    )
                    """
                ),
                {
                    "admission_id": admission_id,
                    "task_id": task_id,
                    "run_id": run_id,
                    "expires_at": NOW + timedelta(hours=1),
                    "now": NOW,
                },
            )

    found = await repo.read_owner_sandbox(task_id=task_id, owner_id=owner_id)

    assert found is not None
    assert found[0].allocation_id == "msa_2"
    assert found[0].generation == 2


# --- 정리 재시도 해제 -------------------------------------------------------


@pytest.mark.integration
async def test_clearing_the_backoff_makes_the_allocation_discoverable_now(
    managed_postgres_session_factory,
) -> None:
    """관리자 조치가 실제로 다음 조정 주기를 앞당기는지 확인한다.

    상태는 바꾸지 않는다 -- 백오프만 걷어낸다.
    """
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed(managed_postgres_session_factory, "msa_1", state="cleanup_pending")
    lease = await repo.claim_allocation(
        "msa_1", "cleanup_1", now=NOW, lease_seconds=60
    )
    await repo.commit_cleanup_outcome(
        lease,
        target=ManagedSandboxState.CLEANUP_RETRY,
        outcome=CleanupAttemptOutcome.UNCONFIRMED,
        error_code=None,
        retry_at=NOW + timedelta(seconds=300),
        started_at=NOW,
        now=NOW,
    )
    assert (await repo.discover_lifecycle_candidates(now=NOW, limit=10)).cleanup == ()

    state = await repo.clear_cleanup_retry("msa_1", now=NOW)

    assert state is ManagedSandboxState.CLEANUP_RETRY
    candidates = await repo.discover_lifecycle_candidates(now=NOW, limit=10)
    assert [item.allocation_id for item in candidates.cleanup] == ["msa_1"]


@pytest.mark.integration
async def test_clearing_the_backoff_of_a_running_sandbox_is_refused(
    managed_postgres_session_factory,
) -> None:
    """정리 단계가 아닌 할당을 건드리면 원장이 '정리 중'이라 거짓말하게 된다."""
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed(managed_postgres_session_factory, "msa_1", state="active")

    with pytest.raises(ManagedSandboxNotClaimable):
        await repo.clear_cleanup_retry("msa_1", now=NOW)


@pytest.mark.integration
async def test_clearing_the_backoff_of_an_unknown_allocation_raises(
    managed_postgres_session_factory,
) -> None:
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)

    with pytest.raises(ManagedSandboxNotFound):
        await repo.clear_cleanup_retry("msa_absent", now=NOW)

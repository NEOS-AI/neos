import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from neos.coding.managed.adapters import AllocationResult
from neos.coding.managed.allocation import (
    AllocationPlan,
    ManagedSandboxNotFound,
    StaleManagedSandboxLease,
)
from neos.coding.managed.domain import ManagedSandboxState
from neos.coding.managed.repository import PostgresManagedSandboxRepository


NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)


async def _seed_admitted_allocation(session_factory, allocation_id: str) -> None:
    """`admitted` 상태의 할당 하나를 심는다.

    `coding_tasks` -> `coding_runs` -> `coding_sandbox_admissions` ->
    `coding_managed_sandboxes` 순으로 넣는다 (`test_postgres_admission.py`의
    `_seed_runs()`와 같은 스타일). `state='admitted'`, `generation=1`,
    `fencing_token=1`, `version=1`로 시작해 claim이 그 위에서 증가시킨다.
    """
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
                         created_at, updated_at, last_activity_at)
                    VALUES
                        (:task_id, :owner_id, 'Fix it', 'running', 1, 0,
                         :now, :now, :now)
                    """
                ),
                {"task_id": task_id, "owner_id": owner_row[0], "now": NOW},
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
                        reserved_active_seconds, reserved_archive_bytes,
                        reserved_cost_micros, reservation_state,
                        actual_active_seconds, actual_archive_bytes,
                        actual_cost_micros, reservation_settled_at,
                        reservation_released_at, reevaluate_at, created_at
                    ) VALUES (
                        :admission_id, :idempotency_key, :tenant_id, :task_id,
                        :provider, :region, :policy_version, 'admitted',
                        'allowed', :reservation_id, :reservation_expires_at,
                        60, 100, 10, 'reserved', 0, 0, 0, NULL, NULL, NULL,
                        :now
                    )
                    """
                ),
                {
                    "admission_id": admission_id,
                    "idempotency_key": f"idem_{allocation_id}",
                    "tenant_id": "tenant_1",
                    "task_id": task_id,
                    "provider": "fake",
                    "region": "local",
                    "policy_version": "managed-v1",
                    "reservation_id": f"rsv_{allocation_id}",
                    "reservation_expires_at": NOW + timedelta(hours=1),
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
                        error_code, snapshot_ref, archive_ref,
                        image_identity, toolchain_identity, created_at,
                        updated_at, cleaned_at
                    ) VALUES (
                        :allocation_id, :admission_id, :tenant_id, :task_id,
                        :run_id, :provider, :region, NULL, NULL, 'admitted',
                        1, 1, NULL, :absolute_expires_at, 1, NULL, NULL,
                        NULL, NULL, NULL, :now, :now, NULL
                    )
                    """
                ),
                {
                    "allocation_id": allocation_id,
                    "admission_id": admission_id,
                    "tenant_id": "tenant_1",
                    "task_id": task_id,
                    "run_id": run_id,
                    "provider": "fake",
                    "region": "local",
                    "absolute_expires_at": NOW + timedelta(hours=1),
                    "now": NOW,
                },
            )


@pytest.mark.integration
async def test_only_one_worker_wins_a_concurrent_claim(
    managed_postgres_session_factory,
) -> None:
    """두 워커가 동시에 클레임하면 정확히 하나만 이겨야 한다.

    이것이 fake 세션으로 증명할 수 없는 부분이다 -- UPDATE ... WHERE 의 원자성이
    실제 Postgres 에서 성립하는지가 요점이다.
    """
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_admitted_allocation(managed_postgres_session_factory, "msa_1")

    outcomes = await asyncio.gather(
        repo.claim_allocation("msa_1", "worker_1", now=NOW, lease_seconds=300),
        repo.claim_allocation("msa_1", "worker_2", now=NOW, lease_seconds=300),
        return_exceptions=True,
    )

    won = [o for o in outcomes if not isinstance(o, BaseException)]
    lost = [o for o in outcomes if isinstance(o, StaleManagedSandboxLease)]
    assert len(won) == 1
    assert len(lost) == 1


@pytest.mark.integration
async def test_a_stale_token_cannot_commit_after_lease_takeover(
    managed_postgres_session_factory,
) -> None:
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_admitted_allocation(managed_postgres_session_factory, "msa_2")
    later = NOW + timedelta(minutes=10)

    stale = await repo.claim_allocation("msa_2", "worker_1", now=NOW, lease_seconds=300)
    fresh = await repo.claim_allocation(
        "msa_2", "worker_2", now=later, lease_seconds=300
    )
    result = AllocationResult(
        provider_ref="ref_1",
        ownership_digest="digest_1",
        state=ManagedSandboxState.ACTIVE,
    )

    with pytest.raises(StaleManagedSandboxLease):
        await repo.commit_active(stale, result, encrypted_ref=b"cipher", now=later)

    committed = await repo.commit_active(
        fresh, result, encrypted_ref=b"cipher", now=later
    )
    assert committed.state is ManagedSandboxState.ACTIVE


@pytest.mark.integration
async def test_read_allocation_plan_joins_the_real_admission_row(
    managed_postgres_session_factory,
) -> None:
    """실제 Postgres에서 `coding_managed_sandboxes` <-> `coding_sandbox_admissions`
    조인이 두 테이블에 진짜로 존재하는 컬럼만으로 성립하는지 증명한다.

    fake 세션 단위 테스트는 SQL 텍스트만 검증하므로, 조인 대상 컬럼이 실제
    스키마에 있는지는 이 통합 테스트가 아니면 확인되지 않는다.
    """
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_admitted_allocation(managed_postgres_session_factory, "msa_3")

    plan = await repo.read_allocation_plan("msa_3")

    assert isinstance(plan, AllocationPlan)
    assert plan.allocation.allocation_id == "msa_3"
    assert plan.allocation.state is ManagedSandboxState.ADMITTED
    assert plan.idempotency_key == "idem_msa_3"


@pytest.mark.integration
async def test_read_allocation_plan_raises_for_an_unknown_allocation(
    managed_postgres_session_factory,
) -> None:
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)

    with pytest.raises(ManagedSandboxNotFound):
        await repo.read_allocation_plan("msa_does_not_exist")

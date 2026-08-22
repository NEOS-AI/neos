"""운영자 승인 복구의 **트랜잭션**을 실제 Postgres 에서 확인한다.

`test_recovery.py`가 보는 것은 "무엇을 검증한 뒤에야 repository 를 부르는가"
이고, 이 파일이 보는 것은 그 repository 호출이 실제로 원자적인가다.

여기서 확인해야만 하는 것 셋:
1. 045의 부분 유니크 인덱스(`idx_coding_managed_sandboxes_current_task`)가
   실제로 원본 종결을 강제하는가 -- fake 로는 인덱스가 없다.
2. `UNIQUE (tenant_id, idempotency_key)`가 두 번 누른 승인을 막는가.
3. 감사 이벤트의 seq 가 `coding_tasks.last_seq` 할당기를 거치는가 --
   우회하면 2026-08-19에 잡힌 `coding_checkpoints_task_id_seq_key` 위반과
   같은 계열의 사고가 난다.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from neos.coding.managed.archive import PortableRecoveryConflict
from neos.coding.managed.domain import ManagedSandboxState
from neos.coding.managed.repository import PostgresManagedSandboxRepository


NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
_IMAGE = "neos-sandbox@sha256:" + "b" * 64


async def _require_event_tables(session_factory) -> None:
    """`coding_events`는 이 스위트 소유가 아니다 (038이 만든다).

    conftest 는 045 테이블만 적용하므로, 감사 기록을 검증하려면 대상 DB 에
    기반 스키마가 이미 있어야 한다. 없으면 조용히 통과시키지 않고 skip 한다 --
    "감사 기록을 확인했다"는 거짓 신호가 더 나쁘다.
    """
    async with await session_factory() as session:
        exists = (
            await session.execute(
                text("SELECT to_regclass('public.coding_events')")
            )
        ).scalar_one()
    if exists is None:
        pytest.skip("base coding schema (migration 038) is not applied")


async def _seed_stuck_allocation(session_factory, allocation_id: str) -> str:
    """`manual_recovery_required` 상태의 할당 하나를 심고 task_id 를 돌려준다."""
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
                        reserved_cost_micros, reservation_state, created_at
                    ) VALUES (
                        :admission_id, :idempotency_key, 'tenant_1', :task_id,
                        'fake', 'local', 'managed-v1', 'admitted', 'allowed',
                        :reservation_id, :expires_at, 600, 4096, 5000,
                        'reserved', :now
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
                        error_code, archive_ref, image_identity,
                        toolchain_identity, created_at, updated_at
                    ) VALUES (
                        :allocation_id, :admission_id, 'tenant_1', :task_id,
                        :run_id, 'fake', 'local', :provider_ref,
                        'sha256:seed', 'manual_recovery_required', 1, 4, NULL,
                        :expires_at, 9, 'provider_not_found', 'pa_1', :image,
                        'python3.12', :now, :now
                    )
                    """
                ),
                {
                    "allocation_id": allocation_id,
                    "admission_id": admission_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "provider_ref": b"sealed",
                    "expires_at": NOW + timedelta(hours=1),
                    "image": _IMAGE,
                    "now": NOW,
                },
            )
    return task_id


def _approve(repo: PostgresManagedSandboxRepository, allocation_id: str, **overrides):
    kwargs = {
        "allocation_id": allocation_id,
        "operator_id": "admin_1",
        "archive_id": "pa_1",
        "checksum": "sha256:" + "d" * 64,
        "policy_version": "managed-v1",
        "lifetime_seconds": 3600,
        "reservation_lease_seconds": 60,
        "now": NOW,
    }
    kwargs.update(overrides)
    return repo.approve_recovery_generation(**kwargs)


@pytest.mark.integration
async def test_approval_closes_the_source_and_creates_the_next_generation(
    managed_postgres_session_factory,
) -> None:
    await _require_event_tables(managed_postgres_session_factory)
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_stuck_allocation(managed_postgres_session_factory, "msa_1")

    recovered = await _approve(repo, "msa_1")

    assert recovered.generation == 2
    assert recovered.state is ManagedSandboxState.ADMITTED
    assert recovered.provider_ref is None
    assert recovered.archive_ref == "pa_1"
    assert recovered.fencing_token == 1
    source = await repo.read_allocation("msa_1")
    assert source.state is ManagedSandboxState.FAILED
    assert source.generation == 1


@pytest.mark.integration
async def test_the_recovery_generation_gets_a_fresh_reservation(
    managed_postgres_session_factory,
) -> None:
    """새 admission 은 새 reservation_id 와 새 리스를 갖되 예약액은 그대로다.

    살아 있는 할당 수가 순증하지 않기 때문에(원본이 같은 트랜잭션에서 닫힌다)
    쿼터를 다시 계산하지 않는다.
    """
    await _require_event_tables(managed_postgres_session_factory)
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    await _seed_stuck_allocation(managed_postgres_session_factory, "msa_1")

    recovered = await _approve(repo, "msa_1")

    async with await managed_postgres_session_factory() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT admission.reservation_id,
                           admission.reservation_state,
                           admission.reserved_active_seconds,
                           admission.reserved_cost_micros,
                           admission.idempotency_key
                      FROM coding_sandbox_admissions AS admission
                      JOIN coding_managed_sandboxes AS sandbox
                        ON sandbox.admission_id = admission.admission_id
                     WHERE sandbox.allocation_id = :allocation_id
                    """
                ),
                {"allocation_id": recovered.allocation_id},
            )
        ).one()

    assert row.reservation_id != "rsv_msa_1"
    assert row.reservation_state == "reserved"
    assert row.reserved_active_seconds == 600
    assert row.reserved_cost_micros == 5000
    assert row.idempotency_key == "recovery:msa_1:g2"


@pytest.mark.integration
async def test_approving_twice_does_not_create_two_generations(
    managed_postgres_session_factory,
) -> None:
    """운영자가 버튼을 두 번 눌러도 세대가 둘 생기지 않는다.

    두 번째 호출은 원본이 이미 FAILED 라 `recovery_not_required`로 막힌다 --
    결정론적 idempotency_key 는 그 뒤의 두 번째 방어선이다.
    """
    await _require_event_tables(managed_postgres_session_factory)
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    task_id = await _seed_stuck_allocation(managed_postgres_session_factory, "msa_1")

    await _approve(repo, "msa_1")
    with pytest.raises(PortableRecoveryConflict, match="recovery_not_required"):
        await _approve(repo, "msa_1")

    async with await managed_postgres_session_factory() as session:
        count = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM coding_managed_sandboxes
                     WHERE task_id = :task_id AND generation = 2
                    """
                ),
                {"task_id": task_id},
            )
        ).scalar_one()

    assert count == 1


@pytest.mark.integration
async def test_a_stuck_allocation_cannot_coexist_with_a_live_generation(
    managed_postgres_session_factory,
) -> None:
    """`recovery_generation_exists` 가드가 **왜 발화하지 않는지**를 못 박는다.

    045의 부분 유니크 인덱스는 `manual_recovery_required` 를 '살아 있음'으로
    센다(`state NOT IN ('cleaned','failed')`). 따라서 "복구 대기 중인 원본 +
    같은 태스크의 살아 있는 다른 세대"라는 조합은 **DB 가 애초에 표현할 수
    없다** -- 승인 트랜잭션의 그 검사는 인덱스에 포섭된 심층 방어이지 지금
    도달 가능한 경로가 아니다.
    (이 테스트를 쓰기 전에는 그 조합을 만들어 가드를 확인하려 했고, 인덱스가
    거절했다. 가드의 계약 자체는 `test_recovery.py`의 fake 가 본다.)
    """
    await _require_event_tables(managed_postgres_session_factory)
    task_id = await _seed_stuck_allocation(managed_postgres_session_factory, "msa_1")
    await _seed_stuck_allocation(managed_postgres_session_factory, "msa_2")

    with pytest.raises(Exception) as failure:
        async with await managed_postgres_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        """
                        UPDATE coding_managed_sandboxes
                           SET task_id = :task_id
                         WHERE allocation_id = 'msa_2'
                        """
                    ),
                    {"task_id": task_id},
                )

    assert "idx_coding_managed_sandboxes_current_task" in str(failure.value)


@pytest.mark.integration
async def test_the_audit_event_is_bounded_and_uses_the_seq_allocator(
    managed_postgres_session_factory,
) -> None:
    """감사 기록은 `coding_events`에 남고 seq 는 할당기를 거친다.

    payload 에는 식별자·체크섬·정책 버전·결과만 들어간다 -- 아카이브 본문이나
    provider 참조가 실리면 브로커와 이벤트 원장이 그것을 영구 보존한다.
    """
    await _require_event_tables(managed_postgres_session_factory)
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    task_id = await _seed_stuck_allocation(managed_postgres_session_factory, "msa_1")

    recovered = await _approve(repo, "msa_1")

    async with await managed_postgres_session_factory() as session:
        event = (
            await session.execute(
                text(
                    """
                    SELECT seq, event_type, payload
                      FROM coding_events
                     WHERE task_id = :task_id
                       AND event_type = 'managed_sandbox_recovery_approved'
                    """
                ),
                {"task_id": task_id},
            )
        ).one()
        last_seq = (
            await session.execute(
                text("SELECT last_seq FROM coding_tasks WHERE task_id = :task_id"),
                {"task_id": task_id},
            )
        ).scalar_one()

    assert event.seq == last_seq
    assert event.payload == {
        "source_allocation_id": "msa_1",
        "recovery_allocation_id": recovered.allocation_id,
        "generation": 2,
        "operator_id": "admin_1",
        "archive_id": "pa_1",
        "archive_checksum": "sha256:" + "d" * 64,
        "policy_version": "managed-v1",
        "outcome": "approved",
    }


@pytest.mark.integration
async def test_a_refused_approval_writes_nothing_at_all(
    managed_postgres_session_factory,
) -> None:
    """상태가 맞지 않으면 admission 도 이벤트도 남지 않는다."""
    await _require_event_tables(managed_postgres_session_factory)
    repo = PostgresManagedSandboxRepository(managed_postgres_session_factory)
    task_id = await _seed_stuck_allocation(managed_postgres_session_factory, "msa_1")
    async with await managed_postgres_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "UPDATE coding_managed_sandboxes SET state = 'active' "
                    "WHERE allocation_id = 'msa_1'"
                )
            )

    with pytest.raises(PortableRecoveryConflict, match="recovery_not_required"):
        await _approve(repo, "msa_1")

    async with await managed_postgres_session_factory() as session:
        admissions = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM coding_sandbox_admissions "
                    "WHERE task_id = :task_id"
                ),
                {"task_id": task_id},
            )
        ).scalar_one()
        events = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM coding_events WHERE task_id = :task_id"
                ),
                {"task_id": task_id},
            )
        ).scalar_one()

    assert admissions == 1
    assert events == 0

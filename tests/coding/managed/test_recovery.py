"""운영자 승인 복구 -- `ManagedSandboxArchiveService.approve_recovery()`.

이 시스템은 **자동 크로스 프로바이더 failover 를 금지**한다. 그 금지를
실제로 지키는 곳이 여기다: 복구는 (1) 검증된 portable 아카이브와
(2) 그 아카이브의 체크섬에 묶인 운영자 결정이 **둘 다** 있어야만 일어난다.

새 세대는 **새 행 + 새 admission** 으로 만든다. 원본 행은 FAILED 로 종결돼
증거로 남는다 -- 같은 행을 제자리에서 올리면 generation 1이 어떤 provider
참조로 죽었는지가 덮어써져 사고 조사 근거가 사라진다.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.archive import (
    archive_checksum,
    InMemoryPortableArchiveStore,
    ManagedSandboxArchiveService,
    PortableRecoveryConflict,
)
from neos.coding.managed.domain import (
    _ALLOWED_ALLOCATION_TRANSITIONS,
    ManagedSandboxAllocation,
    ManagedSandboxState,
    ProviderErrorCode,
)
from tests.coding.managed.test_archive import manifest_for, workspace_body


NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
_IMAGE = "neos-sandbox@sha256:" + "b" * 64
_TOOLCHAIN = "python3.12+node22"


def _stuck_allocation(**overrides) -> ManagedSandboxAllocation:
    allocation = ManagedSandboxAllocation(
        allocation_id="msa_1",
        tenant_id="tenant_1",
        task_id="task_1",
        run_id="run_1",
        provider="fake",
        region="local",
        provider_ref=b"sealed",
        ownership_digest="sha256:seed",
        state=ManagedSandboxState.MANUAL_RECOVERY_REQUIRED,
        generation=1,
        fencing_token=4,
        lease_expires_at=None,
        absolute_expires_at=NOW + timedelta(hours=1),
        version=9,
        error_code=ProviderErrorCode.PROVIDER_NOT_FOUND,
        snapshot_ref=None,
        archive_ref="pa_1",
        image_identity=_IMAGE,
    )
    return replace(allocation, **overrides) if overrides else allocation


class FakeRecoveryRepository:
    """승인 트랜잭션의 **계약**만 흉내 낸다.

    잠금·유니크 인덱스 같은 SQL 성질은 `integration/test_postgres_recovery.py`
    가 본다. 여기서는 서비스가 무엇을 검증한 뒤에야 repository 를 부르는지만
    본다 -- 그래서 `generation`을 노출해 '건드리지 않았음'을 단언할 수 있게 한다.
    """

    def __init__(self, allocation: ManagedSandboxAllocation) -> None:
        self.allocation = allocation
        self.approvals: list[dict] = []
        self.live_generation_exists = False

    @property
    def generation(self) -> int:
        return self.allocation.generation

    async def read_allocation(self, allocation_id: str) -> ManagedSandboxAllocation:
        if allocation_id != self.allocation.allocation_id:
            raise LookupError(allocation_id)
        return self.allocation

    async def approve_recovery_generation(
        self,
        *,
        allocation_id: str,
        operator_id: str,
        archive_id: str,
        checksum: str,
        policy_version: str,
        lifetime_seconds: int,
        reservation_lease_seconds: int,
        now: datetime,
    ) -> ManagedSandboxAllocation:
        if self.live_generation_exists:
            raise PortableRecoveryConflict("recovery_generation_exists")
        self.approvals.append(
            {
                "allocation_id": allocation_id,
                "operator_id": operator_id,
                "archive_id": archive_id,
                "checksum": checksum,
                "policy_version": policy_version,
            }
        )
        source = self.allocation
        self.allocation = replace(source, state=ManagedSandboxState.FAILED)
        return ManagedSandboxAllocation(
            allocation_id=f"{allocation_id}_g{source.generation + 1}",
            tenant_id=source.tenant_id,
            task_id=source.task_id,
            run_id=source.run_id,
            provider=source.provider,
            region=source.region,
            provider_ref=None,
            ownership_digest=None,
            state=ManagedSandboxState.ADMITTED,
            generation=source.generation + 1,
            fencing_token=1,
            lease_expires_at=None,
            absolute_expires_at=now + timedelta(seconds=lifetime_seconds),
            version=1,
            error_code=None,
            snapshot_ref=None,
            archive_ref=archive_id,
            image_identity=source.image_identity,
        )


def recovery_service(
    *,
    allocation: ManagedSandboxAllocation | None = None,
    body: bytes | None = None,
    manifest=None,
) -> tuple[ManagedSandboxArchiveService, FakeRecoveryRepository]:
    body = workspace_body() if body is None else body
    manifest = manifest or manifest_for(body)
    store = InMemoryPortableArchiveStore()
    store.seed(manifest, body)
    repository = FakeRecoveryRepository(allocation or _stuck_allocation())
    service = ManagedSandboxArchiveService(
        repository=repository,
        store=store,
        image_identity=_IMAGE,
        toolchain_identity=_TOOLCHAIN,
        max_archive_bytes=1024 * 1024,
        max_archive_entries=100,
        policy_version="managed-v1",
        lifetime_seconds=3600,
        reservation_lease_seconds=60,
        clock=lambda: NOW,
    )
    return service, repository


def _checksum(body: bytes) -> str:
    return archive_checksum(body)


# --- 검증이 원장보다 먼저다 -----------------------------------------------


async def test_checksum_mismatch_never_creates_a_recovery_generation() -> None:
    """검증 실패는 원장을 **전혀** 건드리지 않아야 한다.

    새 세대를 먼저 만들고 나중에 검증하면, 검증에 실패한 순간 태스크는
    아무도 소유하지 않는 ADMITTED 행 하나를 얻는다.
    """
    service, repository = recovery_service()

    with pytest.raises(PortableRecoveryConflict, match="archive_invalid"):
        await service.approve_recovery(
            allocation_id="msa_1",
            archive_checksum="sha256:not-this-one",
            operator_id="admin_1",
        )

    assert repository.generation == 1
    assert repository.approvals == []
    assert repository.allocation.state is ManagedSandboxState.MANUAL_RECOVERY_REQUIRED


async def test_an_unidentified_operator_cannot_approve() -> None:
    """승인은 **누가 했는지**가 기록돼야 의미가 있다."""
    service, repository = recovery_service()
    body = workspace_body()

    with pytest.raises(PortableRecoveryConflict, match="operator_unidentified"):
        await service.approve_recovery(
            allocation_id="msa_1",
            archive_checksum=_checksum(body),
            operator_id="   ",
        )

    assert repository.approvals == []


async def test_only_a_stuck_allocation_can_be_recovered() -> None:
    """MANUAL_RECOVERY_REQUIRED 가 아닌 할당을 되살리면 살아 있는 provider
    리소스가 고아가 된다.
    """
    service, repository = recovery_service(
        allocation=_stuck_allocation(state=ManagedSandboxState.ACTIVE)
    )
    body = workspace_body()

    with pytest.raises(PortableRecoveryConflict, match="recovery_not_required"):
        await service.approve_recovery(
            allocation_id="msa_1",
            archive_checksum=_checksum(body),
            operator_id="admin_1",
        )

    assert repository.approvals == []


async def test_an_allocation_without_an_archive_cannot_be_recovered() -> None:
    service, repository = recovery_service(
        allocation=_stuck_allocation(archive_ref=None)
    )
    body = workspace_body()

    with pytest.raises(PortableRecoveryConflict, match="archive_missing"):
        await service.approve_recovery(
            allocation_id="msa_1",
            archive_checksum=_checksum(body),
            operator_id="admin_1",
        )

    assert repository.approvals == []


async def test_a_live_generation_blocks_a_second_recovery() -> None:
    """같은 태스크에 살아 있는 세대가 있으면 승인은 실패한다 -- 045의 부분
    유니크 인덱스와 같은 불변식을 서비스 층에서도 지킨다.
    """
    service, repository = recovery_service()
    repository.live_generation_exists = True
    body = workspace_body()

    with pytest.raises(PortableRecoveryConflict, match="recovery_generation_exists"):
        await service.approve_recovery(
            allocation_id="msa_1",
            archive_checksum=_checksum(body),
            operator_id="admin_1",
        )


# --- 승인이 만드는 것 ------------------------------------------------------


async def test_approved_recovery_creates_a_new_fenced_generation() -> None:
    service, _repository = recovery_service()
    body = workspace_body()

    recovered = await service.approve_recovery(
        allocation_id="msa_1",
        archive_checksum=_checksum(body),
        operator_id="admin_1",
    )

    assert recovered.generation == 2
    assert recovered.state is ManagedSandboxState.ADMITTED
    assert recovered.provider_ref is None
    assert recovered.ownership_digest is None
    assert recovered.fencing_token == 1


async def test_the_source_generation_is_closed_not_overwritten(
) -> None:
    """generation 1은 FAILED 로 남아 사고 조사 근거가 된다."""
    service, repository = recovery_service()
    body = workspace_body()

    await service.approve_recovery(
        allocation_id="msa_1",
        archive_checksum=_checksum(body),
        operator_id="admin_1",
    )

    assert repository.allocation.state is ManagedSandboxState.FAILED
    assert repository.allocation.generation == 1


async def test_the_recovery_generation_carries_the_archive_forward() -> None:
    """새 세대가 아카이브를 들고 가야 할당 시점에 워크스페이스를 되살릴 수 있다."""
    service, _repository = recovery_service()
    body = workspace_body()

    recovered = await service.approve_recovery(
        allocation_id="msa_1",
        archive_checksum=_checksum(body),
        operator_id="admin_1",
    )

    assert recovered.archive_ref == "pa_1"


async def test_the_audit_decision_is_bounded_and_checksum_bound() -> None:
    """감사 기록에는 식별자·체크섬·정책 버전만 들어간다 -- 본문은 절대 아니다."""
    service, repository = recovery_service()
    body = workspace_body()

    await service.approve_recovery(
        allocation_id="msa_1",
        archive_checksum=_checksum(body),
        operator_id="admin_1",
    )

    assert repository.approvals == [
        {
            "allocation_id": "msa_1",
            "operator_id": "admin_1",
            "archive_id": "pa_1",
            "checksum": _checksum(body),
            "policy_version": "managed-v1",
        }
    ]


# --- 도메인 전이표가 이 설계를 허용한다 ------------------------------------


def test_a_stuck_allocation_can_legally_be_closed() -> None:
    """승인 트랜잭션은 원본을 FAILED 로 옮긴다 -- 전이표가 그 간선을 줘야 한다.

    Task 6이 세운 규율과 같다: 일괄/직접 UPDATE 는
    `transition_allocation()`을 거치지 않으므로 전이표가 자동으로 지켜주지
    않는다. 두 곳이 갈라지면 DB 에만 불법 전이가 남는다.
    """
    allowed = _ALLOWED_ALLOCATION_TRANSITIONS[
        ManagedSandboxState.MANUAL_RECOVERY_REQUIRED
    ]

    assert ManagedSandboxState.FAILED in allowed


def test_a_stuck_allocation_still_cannot_go_straight_back_to_active() -> None:
    """복구는 **새 세대**로만 일어난다 -- 제자리 부활 간선을 열면 그 순간
    운영자 승인 없이 되살아나는 경로가 생긴다.
    """
    allowed = _ALLOWED_ALLOCATION_TRANSITIONS[
        ManagedSandboxState.MANUAL_RECOVERY_REQUIRED
    ]

    assert ManagedSandboxState.ACTIVE not in allowed
    assert ManagedSandboxState.ADMITTED not in allowed


# --- 할당 시점의 워크스페이스 복원 ------------------------------------------


class _RecordingImporter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    async def import_archive(self, *, allocation, provider_ref, archive_id) -> None:
        self.calls.append((provider_ref, archive_id))
        if self.fail:
            raise RuntimeError("import failed")


def _allocation_service(
    *, archive_ref: str | None, importer=None, state=ManagedSandboxState.ADMITTED
):
    from neos.coding.managed.adapters import (
        FakeManagedSandboxAdapter,
        ManagedNetworkPolicy,
    )
    from neos.coding.managed.allocation import ManagedSandboxAllocationService
    from neos.coding.sandbox.base import SandboxLimits
    from tests.coding.managed.test_allocation_service import (
        FakeAllocationRepository,
        _IdentityCipher,
        _admitted_allocation,
    )

    allocation = replace(
        _admitted_allocation(), archive_ref=archive_ref, state=state
    )
    repository = FakeAllocationRepository(allocation)
    adapter = FakeManagedSandboxAdapter()
    service = ManagedSandboxAllocationService(
        repository=repository,
        adapters={"docker": adapter},
        cipher=_IdentityCipher(),
        resource_limits=SandboxLimits.safe_defaults(),
        network_policy=ManagedNetworkPolicy.BLOCK_ALL,
        image_identity=_IMAGE,
        lease_seconds=300,
        archive_importer=importer,
        clock=lambda: NOW,
    )
    return service, repository, adapter


async def test_a_recovery_generation_restores_its_workspace_before_going_active() -> (
    None
):
    """복원은 ACTIVE 커밋 **앞**에 온다.

    뒤에 두면 빈 워크스페이스를 든 샌드박스가 잠깐이라도 ACTIVE 로 보이고,
    그 사이에 사용자가 그 위에서 일을 시작하면 되돌릴 수 없다.
    """
    importer = _RecordingImporter()
    service, repository, _adapter = _allocation_service(
        archive_ref="pa_1", importer=importer
    )

    result = await service.advance("msa_1", worker_id="worker_1")

    assert importer.calls == [("fake_msa_1", "pa_1")]
    assert result.state is ManagedSandboxState.ACTIVE
    # 복원이 ACTIVE 보다 먼저 -- 커밋 순서로 확인한다.
    assert repository.committed[-1] is ManagedSandboxState.ACTIVE


async def test_an_ordinary_allocation_never_touches_the_importer() -> None:
    """아카이브가 없는 보통 할당은 복원 경로를 지나가지 않는다."""
    importer = _RecordingImporter()
    service, _repository, _adapter = _allocation_service(
        archive_ref=None, importer=importer
    )

    await service.advance("msa_1", worker_id="worker_1")

    assert importer.calls == []


async def test_a_failed_restore_does_not_report_active() -> None:
    importer = _RecordingImporter(fail=True)
    service, _repository, _adapter = _allocation_service(
        archive_ref="pa_1", importer=importer
    )

    result = await service.advance("msa_1", worker_id="worker_1")

    assert result.state is ManagedSandboxState.RECOVERY_PENDING
    assert result.error_code is ProviderErrorCode.ARCHIVE_INVALID


async def test_a_second_failed_restore_escalates_to_an_operator() -> None:
    """아카이브는 승인 시점에 이미 검증됐다 -- 두 번 연속 실패는 재시도로 풀
    문제가 아니다. 그리고 RECOVERY_PENDING 은 자기 자신으로 가는 간선이 없다.
    """
    importer = _RecordingImporter(fail=True)
    service, _repository, adapter = _allocation_service(
        archive_ref="pa_1",
        importer=importer,
        state=ManagedSandboxState.RECOVERY_PENDING,
    )
    # 첫 시도에서 provider 리소스는 실제로 만들어졌고 복원만 실패한 상황이다 --
    # 재발견이 그것을 찾아야 복원 재시도까지 간다.
    adapter.seed(
        provider_ref="fake_msa_1",
        allocation_id="msa_1",
        idempotency_key="idem_1",
        ownership_digest="sha256:seed",
    )

    result = await service.advance("msa_1", worker_id="worker_2")

    assert result.state is ManagedSandboxState.MANUAL_RECOVERY_REQUIRED
    assert result.error_code is ProviderErrorCode.ARCHIVE_INVALID


async def test_a_recovery_generation_without_an_importer_never_reports_active() -> None:
    """복원기가 배선되지 않았으면 **조용히 건너뛰지 않는다.**

    "복원할 것이 없다"(archive_ref 없음)와 "복원할 수단이 없다"(복원기 없음)는
    다르다. 후자를 ACTIVE 로 적으면 사용자는 워크스페이스가 돌아온 줄 알지만
    실제로는 빈 샌드박스다.
    """
    service, _repository, _adapter = _allocation_service(
        archive_ref="pa_1", importer=None
    )

    result = await service.advance("msa_1", worker_id="worker_1")

    assert result.state is ManagedSandboxState.RECOVERY_PENDING
    assert result.error_code is ProviderErrorCode.ARCHIVE_INVALID


def test_the_importer_port_restores_the_workspace_and_nothing_else() -> None:
    """PTY·백그라운드 프로세스를 되살릴 **표면 자체가 없어야** 한다.

    죽은 세대의 실행 중 상태를 흉내 내면 사용자는 이어졌다고 믿지만 실제로는
    아무것도 돌고 있지 않다. 계약에 그 문이 없으면 실수로 열 수 없다.
    """
    from neos.coding.managed.allocation import PortableArchiveImporter

    methods = {
        name
        for name in dir(PortableArchiveImporter)
        if not name.startswith("_")
    }

    assert methods == {"import_archive"}

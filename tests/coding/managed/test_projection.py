"""소유자에게 보이는 샌드박스 상태의 **경계** 테스트.

투영이 하는 일은 요약이 아니라 **차단**이다. 내부 상태 11개를 바깥 어휘
7개로 접으면서 provider·region·provider 참조·할당 식별자·서킷 상세·raw 에러를
전부 떨어뜨린다. 그래서 이 파일의 대부분은 "무엇이 보이는가"가 아니라
"무엇이 **보이지 않는가**"를 단언한다.

내부 상태를 그대로 노출하면 두 가지가 샌다. (1) provider 이름과 지역은
사용자에게 필요 없는 **인프라 사실**이고, (2) `manual_recovery_required` 같은
이름은 운영자용 어휘라 사용자가 스스로 고칠 수 있다고 오해하게 만든다.
"""

from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.domain import (
    ManagedSandboxAllocation,
    ManagedSandboxState,
    ProviderErrorCode,
)
from neos.coding.managed.projection import (
    OwnerSandboxState,
    project_owner_sandbox_status,
)


NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)


def _allocation(state: ManagedSandboxState, **overrides) -> ManagedSandboxAllocation:
    # CLEANED 행은 provider 참조를 들 수 없다(`__post_init__`이 거부한다) --
    # 045의 CHECK 제약과 같은 불변식이다. 투영 테스트가 그 규칙을 어기면
    # 실제로는 만들어질 수 없는 행을 검사하게 된다.
    cleaned = state is ManagedSandboxState.CLEANED
    allocation = ManagedSandboxAllocation(
        allocation_id="msa_secret_1",
        tenant_id="tenant_1",
        task_id="task_1",
        run_id="run_1",
        provider="e2b",
        region="us-east-1",
        provider_ref=None if cleaned else b"sealed-provider-reference",
        ownership_digest=None if cleaned else "sha256:seed",
        state=state,
        generation=1,
        fencing_token=3,
        lease_expires_at=None,
        absolute_expires_at=NOW + timedelta(hours=1),
        version=5,
        error_code=ProviderErrorCode.PROVIDER_AUTH_ERROR,
        snapshot_ref=None,
        archive_ref=None,
        image_identity="neos-sandbox@sha256:" + "b" * 64,
    )
    for name, value in overrides.items():
        object.__setattr__(allocation, name, value)
    return allocation


# --- 상태 사상 -------------------------------------------------------------


@pytest.mark.parametrize(
    ("internal", "external"),
    [
        (ManagedSandboxState.REQUESTED, OwnerSandboxState.PREPARING),
        (ManagedSandboxState.ADMITTED, OwnerSandboxState.PREPARING),
        (ManagedSandboxState.ALLOCATING, OwnerSandboxState.PREPARING),
        (ManagedSandboxState.ACTIVE, OwnerSandboxState.READY),
        (ManagedSandboxState.SUSPENDED, OwnerSandboxState.SUSPENDED),
        (
            ManagedSandboxState.RECOVERY_PENDING,
            OwnerSandboxState.PROVIDER_RECOVERY_PENDING,
        ),
        (
            ManagedSandboxState.MANUAL_RECOVERY_REQUIRED,
            OwnerSandboxState.OPERATOR_RECOVERY_REQUIRED,
        ),
        (ManagedSandboxState.CLEANUP_PENDING, OwnerSandboxState.CLEANING_UP),
        (ManagedSandboxState.CLEANUP_RETRY, OwnerSandboxState.CLEANING_UP),
        (ManagedSandboxState.CLEANED, OwnerSandboxState.CLEANED),
    ],
)
def test_every_internal_state_maps_to_a_bounded_owner_state(
    internal: ManagedSandboxState, external: OwnerSandboxState
) -> None:
    status = project_owner_sandbox_status(_allocation(internal), updated_at=NOW)

    assert status.state is external


def test_a_failed_allocation_reads_as_operator_recovery_required() -> None:
    """`failed`를 'cleaned' 로 접으면 사용자는 정리가 끝났다고 읽는다.

    실제로는 아무도 손대지 않은 상태라 운영자가 필요하다.
    """
    status = project_owner_sandbox_status(
        _allocation(ManagedSandboxState.FAILED), updated_at=NOW
    )

    assert status.state is OwnerSandboxState.OPERATOR_RECOVERY_REQUIRED


def test_the_projection_covers_every_internal_state() -> None:
    """새 내부 상태가 생기면 이 테스트가 먼저 깨진다.

    사상 표에 빠진 상태를 기본값으로 흘려보내면, 그 상태가 무엇이든
    사용자는 그럴듯한 거짓말을 보게 된다 -- 이 저장소가 반복해서 다친
    '조용한 degrade' 의 UI 판이다.
    """
    for state in ManagedSandboxState:
        status = project_owner_sandbox_status(_allocation(state), updated_at=NOW)
        assert isinstance(status.state, OwnerSandboxState)


# --- 능력 플래그 -----------------------------------------------------------


def test_only_a_ready_sandbox_can_run_or_open_a_terminal() -> None:
    ready = project_owner_sandbox_status(
        _allocation(ManagedSandboxState.ACTIVE), updated_at=NOW
    )

    assert ready.can_run is True
    assert ready.can_open_terminal is True


@pytest.mark.parametrize(
    "state",
    [
        ManagedSandboxState.REQUESTED,
        ManagedSandboxState.ADMITTED,
        ManagedSandboxState.ALLOCATING,
        ManagedSandboxState.SUSPENDED,
        ManagedSandboxState.RECOVERY_PENDING,
        ManagedSandboxState.MANUAL_RECOVERY_REQUIRED,
        ManagedSandboxState.CLEANUP_PENDING,
        ManagedSandboxState.CLEANUP_RETRY,
        ManagedSandboxState.CLEANED,
        ManagedSandboxState.FAILED,
    ],
)
def test_nothing_but_ready_permits_execution(state: ManagedSandboxState) -> None:
    """실행 게이팅은 화이트리스트다.

    블랙리스트로 쓰면 새 상태가 추가될 때마다 **기본이 '실행 허용'** 이 되고,
    정리 중인 샌드박스에서 명령이 도는 사고가 조용히 열린다.
    """
    status = project_owner_sandbox_status(_allocation(state), updated_at=NOW)

    assert status.can_run is False
    assert status.can_open_terminal is False


def test_a_recovered_generation_says_so() -> None:
    """복구된 세대는 마지막 체크포인트에서 이어졌다는 사실만 알린다."""
    status = project_owner_sandbox_status(
        _allocation(ManagedSandboxState.ACTIVE, generation=2), updated_at=NOW
    )

    assert status.recovered_from_checkpoint is True


def test_a_first_generation_is_not_marked_as_recovered() -> None:
    status = project_owner_sandbox_status(
        _allocation(ManagedSandboxState.ACTIVE), updated_at=NOW
    )

    assert status.recovered_from_checkpoint is False


# --- 새지 않는다 -----------------------------------------------------------


def test_the_payload_has_exactly_five_keys() -> None:
    """키 집합을 고정한다 -- 필드가 하나 늘어나는 것이 곧 유출이다."""
    payload = project_owner_sandbox_status(
        _allocation(ManagedSandboxState.ACTIVE), updated_at=NOW
    ).to_payload()

    assert set(payload) == {
        "state",
        "can_run",
        "can_open_terminal",
        "recovered_from_checkpoint",
        "updated_at",
    }


def test_no_infrastructure_fact_survives_the_projection() -> None:
    """provider·region·참조·할당 id·에러 코드 중 어느 것도 남지 않는다."""
    payload = project_owner_sandbox_status(
        _allocation(ManagedSandboxState.MANUAL_RECOVERY_REQUIRED), updated_at=NOW
    ).to_payload()
    rendered = repr(payload)

    for secret in (
        "e2b",
        "us-east-1",
        "msa_secret_1",
        "sealed-provider-reference",
        "provider_auth_error",
        "neos-sandbox@sha256:",
        "tenant_1",
    ):
        assert secret not in rendered


def test_the_owner_vocabulary_never_reuses_internal_state_names() -> None:
    """두 어휘가 겹치면 어느 쪽을 보고 있는지 코드에서 구별되지 않는다.

    `suspended`/`cleaned` 는 의도적으로 같다 -- 사용자에게도 정확히 같은
    뜻이기 때문이다. 나머지는 겹치면 안 된다.
    """
    internal = {state.value for state in ManagedSandboxState}
    external = {state.value for state in OwnerSandboxState}

    assert external & internal == {"suspended", "cleaned"}

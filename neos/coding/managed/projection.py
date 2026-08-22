"""소유자에게 보이는 샌드박스 상태.

**이 모듈이 하는 일은 요약이 아니라 차단이다.** 내부 상태 11개를 바깥 어휘
7개로 접으면서 provider·region·provider 참조·할당 식별자·서킷 상세·raw 에러를
전부 떨어뜨린다. 남는 것은 사용자가 **행동을 결정하는 데 필요한 것**뿐이다:
지금 돌릴 수 있는가, 터미널을 열 수 있는가, 기다리면 되는가, 사람이 필요한가.

내부 어휘를 그대로 내보내지 않는 이유가 둘 있다.
1. provider 이름과 지역은 사용자에게 필요 없는 **인프라 사실**이다. 한 번
   내보내면 계약이 되어 provider 를 바꿀 때 사용자에게 보이는 문자열이 바뀐다.
2. `manual_recovery_required` 같은 이름은 **운영자용 어휘**다. 사용자가 스스로
   고칠 수 있다고 오해하게 만든다.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from neos.coding.managed.domain import ManagedSandboxAllocation, ManagedSandboxState


class OwnerSandboxState(StrEnum):
    PREPARING = "preparing"
    READY = "ready"
    SUSPENDED = "suspended"
    PROVIDER_RECOVERY_PENDING = "provider_recovery_pending"
    OPERATOR_RECOVERY_REQUIRED = "operator_recovery_required"
    CLEANING_UP = "cleaning_up"
    CLEANED = "cleaned"


# 내부 -> 바깥 사상. **전수 표다**: `project_owner_sandbox_status()`가 빠진
# 상태를 기본값으로 흘려보내지 않고 KeyError 로 죽는다. 사상 표에 없는 상태를
# 조용히 'preparing' 같은 것으로 접으면, 그 상태가 무엇이든 사용자는 그럴듯한
# 거짓말을 보게 된다 -- 이 저장소가 반복해서 다친 '조용한 degrade' 의 UI 판이다.
#
# `FAILED`가 `OPERATOR_RECOVERY_REQUIRED`로 가는 것에 주의. 'cleaned' 로 접으면
# 사용자는 정리가 끝났다고 읽지만 실제로는 아무도 손대지 않은 상태다.
_OWNER_STATES: dict[ManagedSandboxState, OwnerSandboxState] = {
    ManagedSandboxState.REQUESTED: OwnerSandboxState.PREPARING,
    ManagedSandboxState.ADMITTED: OwnerSandboxState.PREPARING,
    ManagedSandboxState.ALLOCATING: OwnerSandboxState.PREPARING,
    ManagedSandboxState.ACTIVE: OwnerSandboxState.READY,
    ManagedSandboxState.SUSPENDED: OwnerSandboxState.SUSPENDED,
    ManagedSandboxState.RECOVERY_PENDING: (
        OwnerSandboxState.PROVIDER_RECOVERY_PENDING
    ),
    ManagedSandboxState.MANUAL_RECOVERY_REQUIRED: (
        OwnerSandboxState.OPERATOR_RECOVERY_REQUIRED
    ),
    ManagedSandboxState.CLEANUP_PENDING: OwnerSandboxState.CLEANING_UP,
    ManagedSandboxState.CLEANUP_RETRY: OwnerSandboxState.CLEANING_UP,
    ManagedSandboxState.CLEANED: OwnerSandboxState.CLEANED,
    ManagedSandboxState.FAILED: OwnerSandboxState.OPERATOR_RECOVERY_REQUIRED,
}


@dataclass(frozen=True, slots=True)
class OwnerSandboxStatus:
    state: OwnerSandboxState
    can_run: bool
    can_open_terminal: bool
    recovered_from_checkpoint: bool
    updated_at: datetime

    def to_payload(self) -> dict:
        """응답 본문. **키 집합이 계약이다** -- 필드가 하나 늘어나는 것이 곧 유출이다."""
        return {
            "state": self.state.value,
            "can_run": self.can_run,
            "can_open_terminal": self.can_open_terminal,
            "recovered_from_checkpoint": self.recovered_from_checkpoint,
            "updated_at": self.updated_at,
        }


def project_owner_sandbox_status(
    allocation: ManagedSandboxAllocation, *, updated_at: datetime
) -> OwnerSandboxStatus:
    """할당 한 행을 소유자에게 보일 수 있는 형태로 접는다.

    `updated_at`을 밖에서 받는 이유: 045의 `updated_at`은 도메인 객체에 실려
    있지 않다(`ManagedSandboxAllocation`에 그 필드가 없다). 호출자가 행에서
    읽어 넘긴다 -- 여기서 `now()`를 부르면 아무 일도 없었는데 갱신된 것처럼
    보인다.
    """
    state = _OWNER_STATES[allocation.state]
    # 실행 게이팅은 **화이트리스트**다. 블랙리스트로 쓰면 새 내부 상태가
    # 추가될 때마다 기본이 '실행 허용'이 되고, 정리 중인 샌드박스에서 명령이
    # 도는 사고가 조용히 열린다.
    runnable = state is OwnerSandboxState.READY
    return OwnerSandboxStatus(
        state=state,
        can_run=runnable,
        can_open_terminal=runnable,
        # 세대가 1보다 크면 운영자 승인 복구를 거쳐 온 것이고, 그 경우 런은
        # 마지막 내구 체크포인트에서만 이어진다(PTY·백그라운드 프로세스는
        # 되살리지 않는다). 사용자에게 알려야 할 것은 그 사실 하나뿐이다 --
        # 어느 아카이브에서 왔는지도, 누가 승인했는지도 아니다.
        recovered_from_checkpoint=allocation.generation > 1,
        updated_at=updated_at,
    )

"""펜스된 할당(lease) 계약.

`coding_managed_sandboxes`(마이그레이션 045)에는 `fencing_token`과
`lease_expires_at`만 있고 리스 소유자 컬럼이 없다. 그래서 소유권 증명은
`fencing_token` 단독으로 한다 -- claim이 토큰을 증가시키고, commit은 그 토큰을
WHERE 절에 넣어 낡은 워커가 갱신하는 행 수를 0으로 만든다.
`worker_id`는 이 lease 객체와 로그·메트릭에만 남는 진단용이며 DB에는
저장하지 않는다.
"""

from dataclasses import dataclass
from datetime import datetime

from neos.coding.managed.domain import ManagedSandboxAllocation


class StaleManagedSandboxLease(RuntimeError):
    """펜싱 토큰이 낡거나 리스가 살아 있어 이 워커는 더 이상 이 할당을
    진행시킬 수 없다 -- "누군가 지금 쥐고 있다"는 뜻이다.
    """


class ManagedSandboxNotFound(LookupError):
    """`allocation_id`에 해당하는 할당 행이 없다."""


class ManagedSandboxNotClaimable(RuntimeError):
    """할당이 claim 가능한 상태가 아니다 -- "이미 끝났거나 다른 단계에
    있다"는 뜻이다. 리스가 살아 있어서 지는 것(`StaleManagedSandboxLease`)과
    구별해야 호출자가 재시도할지 포기할지 판단할 수 있다.
    """


@dataclass(frozen=True, slots=True)
class ManagedAllocationLease:
    """claim이 발급한 리스. `fencing_token`이 소유권 증명이다."""

    allocation_id: str
    worker_id: str
    fencing_token: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AllocationPlan:
    """할당 행 + admission 행에서 **DB 에 실제로 있는 것만** 모은 읽기 뷰.

    resource_limits 와 network_policy 는 여기 없다 -- 정책이지 상태가 아니며,
    서비스가 config 에서 받아 요청을 만들 때 채운다. (045에는 애초에 이 두
    컬럼이 admissions/managed_sandboxes 어느 쪽에도 없다 -- 마이그레이션 없이는
    영속화할 수 없고, 정책을 어차피 config에서 읽는 편이 진행 중인 할당에도
    정책 변경이 즉시 반영되지 않는 문제를 피한다.)
    """

    allocation: ManagedSandboxAllocation
    idempotency_key: str

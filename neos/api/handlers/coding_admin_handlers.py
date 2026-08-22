"""관리형 샌드박스의 운영자 제어 API.

**관리자 의존성은 라우터에 건다.** 개별 핸들러에만 걸면 다음 라우트를
추가하는 사람이 빠뜨리고, 그 실수는 테스트가 아니라 사고로 드러난다.

응답은 전부 경계값이다 -- provider 참조도, 예외 텍스트도, 아카이브 본문도
나가지 않는다. 복구 충돌은 `PortableRecoveryConflict`가 들고 있는 **안정적인
사유 코드**만 409로 낸다.
"""

from fastapi import APIRouter, Depends, HTTPException

from neos.api.dependencies.auth import get_current_admin_user
from neos.api.models.coding_models import (
    CodingSandboxCleanupRetryResponse,
    CodingSandboxDrainRequest,
    CodingSandboxDrainResponse,
    CodingSandboxRecoveryRequest,
    CodingSandboxRecoveryResponse,
)
from neos.coding.managed.admin import ManagedSandboxAdminService
from neos.coding.managed.allocation import (
    ManagedSandboxNotClaimable,
    ManagedSandboxNotFound,
)
from neos.coding.managed.archive import PortableRecoveryConflict
from neos.coding.runtime import managed_sandbox_admin_service
from neos.database.models import User


router = APIRouter(
    prefix="/admin/coding",
    tags=["Coding Agent Admin"],
    dependencies=[Depends(get_current_admin_user)],
)


def get_managed_admin_service() -> ManagedSandboxAdminService:
    return managed_sandbox_admin_service()


@router.post(
    "/providers/{provider}/drain", response_model=CodingSandboxDrainResponse
)
async def drain_managed_provider(
    provider: str,
    request: CodingSandboxDrainRequest,
    admin: ManagedSandboxAdminService = Depends(get_managed_admin_service),
):
    return await admin.drain_provider(
        provider=provider, region=request.region, drained=request.drained
    )


@router.post(
    "/allocations/{allocation_id}/retry-cleanup",
    response_model=CodingSandboxCleanupRetryResponse,
)
async def retry_managed_cleanup(
    allocation_id: str,
    admin: ManagedSandboxAdminService = Depends(get_managed_admin_service),
):
    try:
        return await admin.retry_cleanup(allocation_id=allocation_id)
    except ManagedSandboxNotFound as error:
        raise HTTPException(status_code=404, detail="allocation_not_found") from error
    except ManagedSandboxNotClaimable as error:
        # 정리 단계가 아닌 할당이다. 사유는 안정적인 코드로만 낸다.
        raise HTTPException(status_code=409, detail="not_in_cleanup") from error


@router.post(
    "/allocations/{allocation_id}/approve-recovery",
    response_model=CodingSandboxRecoveryResponse,
)
async def approve_managed_recovery(
    allocation_id: str,
    request: CodingSandboxRecoveryRequest,
    current_admin: User = Depends(get_current_admin_user),
    admin: ManagedSandboxAdminService = Depends(get_managed_admin_service),
):
    """승인은 **누가 했는지**와 **어떤 아카이브인지**에 함께 묶인다.

    `operator_id`를 요청 본문이 아니라 인증된 신원에서 가져온다 -- 본문에서
    받으면 관리자가 남의 이름으로 승인할 수 있고, 감사 기록의 의미가 사라진다.
    """
    try:
        return await admin.approve_recovery(
            allocation_id=allocation_id,
            archive_checksum=request.archive_checksum,
            operator_id=current_admin.user_id,
        )
    except ManagedSandboxNotFound as error:
        raise HTTPException(status_code=404, detail="allocation_not_found") from error
    except PortableRecoveryConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

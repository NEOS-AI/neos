"""관리형 샌드박스의 소유자 조회와 관리자 제어 엔드포인트.

두 가지를 본다.

**권한** -- 소유자가 아니면 할당을 **조회하기도 전에** 404 다. 조회한 뒤에
거절하면 "그 태스크는 존재한다"가 응답 시간으로 샌다. 관리자 라우트는
비관리자에게 **부작용 전에** 403 이다.

**프라이버시** -- 소유자 응답에 provider·region·provider 참조·할당 식별자·
raw 에러가 없다. 관리자 응답도 provider 참조와 raw 에러는 싣지 않는다 --
운영자에게도 봉인된 참조를 평문으로 줄 이유가 없다.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neos.api.dependencies.auth import get_current_admin_user, get_current_user
from neos.api.handlers.coding_admin_handlers import (
    get_managed_admin_service,
    router as admin_router,
)
from neos.api.handlers.coding_handlers import (
    get_managed_sandbox_service,
    router as coding_router,
)
from neos.coding.managed.archive import PortableRecoveryConflict
from neos.coding.managed.domain import ManagedSandboxState


NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
_CHECKSUM = "sha256:" + "a" * 64


class FakeManagedSandboxService:
    """소유자 조회가 요구하는 계약만 흉내 낸다."""

    def __init__(self, *, state=ManagedSandboxState.ACTIVE, owner="u1") -> None:
        self.state = state
        self.owner = owner
        self.lookups: list[tuple[str, str]] = []

    async def owner_status(self, *, task_id: str, owner_id: str):
        self.lookups.append((task_id, owner_id))
        if owner_id != self.owner:
            return None
        from neos.coding.managed.projection import OwnerSandboxStatus, OwnerSandboxState

        return OwnerSandboxStatus(
            state=(
                OwnerSandboxState.READY
                if self.state is ManagedSandboxState.ACTIVE
                else OwnerSandboxState.PROVIDER_RECOVERY_PENDING
            ),
            can_run=self.state is ManagedSandboxState.ACTIVE,
            can_open_terminal=self.state is ManagedSandboxState.ACTIVE,
            recovered_from_checkpoint=False,
            updated_at=NOW,
        )


class FakeManagedAdminService:
    def __init__(self) -> None:
        self.drains: list[tuple[str, str, bool]] = []
        self.retries: list[str] = []
        self.approvals: list[tuple[str, str, str]] = []
        self.conflict: PortableRecoveryConflict | None = None

    async def drain_provider(self, *, provider: str, region: str, drained: bool):
        self.drains.append((provider, region, drained))
        return {
            "provider": provider,
            "region": region,
            "drained": drained,
            "circuit": "unavailable" if drained else "healthy",
            "scope": "process_local",
        }

    async def retry_cleanup(self, *, allocation_id: str):
        self.retries.append(allocation_id)
        return {"allocation_id": allocation_id, "state": "cleanup_pending"}

    async def approve_recovery(
        self, *, allocation_id: str, archive_checksum: str, operator_id: str
    ):
        if self.conflict is not None:
            raise self.conflict
        self.approvals.append((allocation_id, archive_checksum, operator_id))
        return {
            "allocation_id": "msa_next",
            "generation": 2,
            "state": "admitted",
        }


def make_client(
    *,
    user_id: str = "u1",
    admin: bool = False,
    sandboxes: FakeManagedSandboxService | None = None,
    admin_service: FakeManagedAdminService | None = None,
):
    app = FastAPI()
    app.include_router(coding_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    sandboxes = sandboxes or FakeManagedSandboxService()
    admin_service = admin_service or FakeManagedAdminService()
    # `get_current_admin_user` 는 `get_current_active_user` 를 거치므로 fake
    # 사용자도 그 체인이 읽는 필드를 갖춰야 한다 -- 없으면 403 이 아니라
    # AttributeError 로 500 이 나서 "막혔다"를 잘못 확인하게 된다.
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        user_id=user_id, is_active=True, is_admin=admin, role="admin" if admin else "user"
    )
    if admin:
        app.dependency_overrides[get_current_admin_user] = lambda: SimpleNamespace(
            user_id=user_id, is_admin=True, role="admin"
        )
    app.dependency_overrides[get_managed_sandbox_service] = lambda: sandboxes
    app.dependency_overrides[get_managed_admin_service] = lambda: admin_service
    return TestClient(app), sandboxes, admin_service


# --- 소유자 조회 -----------------------------------------------------------


def test_owner_status_hides_provider_reference_and_raw_error() -> None:
    client, _sandboxes, _admin = make_client()

    response = client.get("/api/v1/coding/tasks/ct_1/sandbox-status")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "state": "ready",
        "can_run": True,
        "can_open_terminal": True,
        "recovered_from_checkpoint": False,
        "updated_at": "2026-08-22T12:00:00Z",
    }
    assert "provider_ref" not in body
    assert "error" not in body


def test_a_recovering_sandbox_reports_a_bounded_state() -> None:
    client, _sandboxes, _admin = make_client(
        sandboxes=FakeManagedSandboxService(
            state=ManagedSandboxState.RECOVERY_PENDING
        )
    )

    body = client.get("/api/v1/coding/tasks/ct_1/sandbox-status").json()

    assert body["state"] == "provider_recovery_pending"
    assert body["can_run"] is False
    assert body["can_open_terminal"] is False


def test_a_non_owner_gets_404_and_the_lookup_is_owner_scoped() -> None:
    """소유권 검사는 조회 **질의 안에** 있어야 한다.

    먼저 읽고 나중에 비교하면 "그 태스크는 존재한다"가 새고, 응답 시간으로도
    구별된다.
    """
    client, sandboxes, _admin = make_client(user_id="intruder")

    response = client.get("/api/v1/coding/tasks/ct_1/sandbox-status")

    assert response.status_code == 404
    assert sandboxes.lookups == [("ct_1", "intruder")]


def test_owner_status_requires_authentication() -> None:
    app = FastAPI()
    app.include_router(coding_router, prefix="/api/v1")
    app.dependency_overrides[get_managed_sandbox_service] = (
        lambda: FakeManagedSandboxService()
    )

    response = TestClient(app).get("/api/v1/coding/tasks/ct_1/sandbox-status")

    assert response.status_code in {401, 403}


# --- 관리자 제어 -----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/v1/admin/coding/providers/e2b/drain", {"drained": True}),
        ("post", "/api/v1/admin/coding/allocations/msa_1/retry-cleanup", None),
        (
            "post",
            "/api/v1/admin/coding/allocations/msa_1/approve-recovery",
            {"archive_checksum": _CHECKSUM},
        ),
    ],
)
def test_non_admin_cannot_reach_admin_routes(method, path, payload) -> None:
    """부작용 **전에** 막힌다 -- 서비스가 호출된 흔적이 없어야 한다."""
    client, _sandboxes, admin_service = make_client(admin=False)

    response = getattr(client, method)(path, json=payload)

    assert response.status_code in {401, 403}
    assert admin_service.drains == []
    assert admin_service.retries == []
    assert admin_service.approvals == []


def test_drain_only_touches_the_configured_provider_circuit() -> None:
    client, _sandboxes, admin_service = make_client(admin=True)

    response = client.post(
        "/api/v1/admin/coding/providers/e2b/drain",
        json={"region": "us-east-1", "drained": True},
    )

    assert response.status_code == 200
    assert admin_service.drains == [("e2b", "us-east-1", True)]


def test_retry_cleanup_is_admin_only_and_bounded() -> None:
    client, _sandboxes, admin_service = make_client(admin=True)

    response = client.post(
        "/api/v1/admin/coding/allocations/msa_1/retry-cleanup"
    )

    assert response.status_code == 200
    assert admin_service.retries == ["msa_1"]
    assert set(response.json()) == {"allocation_id", "state"}


def test_recovery_approval_is_checksum_bound() -> None:
    client, _sandboxes, admin_service = make_client(admin=True, user_id="admin_1")

    response = client.post(
        "/api/v1/admin/coding/allocations/msa_1/approve-recovery",
        json={"archive_checksum": _CHECKSUM},
    )

    assert response.status_code == 200
    assert admin_service.approvals == [("msa_1", _CHECKSUM, "admin_1")]


@pytest.mark.parametrize(
    "checksum",
    [
        "a" * 64,
        "sha256:" + "A" * 64,
        "sha256:" + "a" * 63,
        "sha1:" + "a" * 64,
        "",
    ],
)
def test_a_malformed_checksum_never_reaches_the_service(checksum: str) -> None:
    """형식 검증이 경계에서 끝난다.

    체크섬이 승인의 **유일한** 결속 수단이므로, 모양이 틀린 값을 서비스까지
    흘려보내면 그 비교가 어디서 이뤄지는지가 흐려진다.
    """
    client, _sandboxes, admin_service = make_client(admin=True)

    response = client.post(
        "/api/v1/admin/coding/allocations/msa_1/approve-recovery",
        json={"archive_checksum": checksum},
    )

    assert response.status_code == 422
    assert admin_service.approvals == []


def test_a_recovery_conflict_returns_a_stable_reason_not_an_exception() -> None:
    """사유 코드만 나간다 -- 예외 텍스트나 provider 원문이 아니다."""
    admin_service = FakeManagedAdminService()
    admin_service.conflict = PortableRecoveryConflict("archive_expired")
    client, _sandboxes, _admin = make_client(
        admin=True, admin_service=admin_service
    )

    response = client.post(
        "/api/v1/admin/coding/allocations/msa_1/approve-recovery",
        json={"archive_checksum": _CHECKSUM},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "archive_expired"


def test_admin_routes_are_classified_as_admin_in_the_router() -> None:
    """라우터 자체에 관리자 의존성이 박혀 있어야 한다.

    개별 핸들러에만 걸면 다음 라우트를 추가하는 사람이 빠뜨린다 -- 그리고
    그 실수는 테스트가 아니라 사고로 드러난다.
    """
    from neos.api.handlers import coding_admin_handlers

    names = {
        dependency.dependency.__name__
        for dependency in coding_admin_handlers.router.dependencies
        if getattr(dependency, "dependency", None) is not None
    }

    assert "get_current_admin_user" in names

"""portable 아카이브와 운영자 승인 복구.

이 시스템은 **자동 크로스 프로바이더 failover 를 금지**한다. 그 금지가 실제로
지켜지는 자리가 여기다 -- 복구는 두 가지가 **모두** 있어야만 일어난다:

1. 검증된 portable 아카이브 (체크섬·크기·경로·스캔·이미지/툴체인·보존기한)
2. 그 아카이브의 **체크섬에 묶인** 운영자 결정

검증은 **원장을 건드리기 전에** 전부 끝난다. 새 세대를 먼저 만들고 나중에
검증하면, 검증에 실패하는 순간 태스크는 아무도 소유하지 않는 `ADMITTED` 행
하나를 얻는다.

**새 세대는 새 행 + 새 admission 이다.** 원본 행은 `FAILED`로 종결돼 증거로
남는다 -- 같은 행을 제자리에서 올리면 generation 1이 *어떤 provider 참조로
죽었는지*가 덮어써져 사고 조사 근거가 사라진다. 045의 부분 유니크 인덱스
(`idx_coding_managed_sandboxes_current_task`)가 태스크당 살아 있는 할당을
하나로 강제하므로, 원본 종결과 새 세대 생성은 같은 트랜잭션이어야 한다.

**매니페스트는 DB 가 아니라 스토어에 산다** (`LocalSnapshotStore`가 이미 쓰는
패턴). 할당 행의 `archive_ref`가 그 id 를 가리킨다 -- 045에 아카이브 테이블이
없고, 이 플랜은 마이그레이션을 045 하나로 둔다.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from neos.coding.managed.domain import ManagedSandboxAllocation, ManagedSandboxState
from neos.coding.sandbox.base import SandboxPolicyViolation
from neos.coding.sandbox.archive import validate_workspace_archive_bytes


_SCAN_STATUSES = frozenset({"clean", "rejected"})


class PortableRecoveryConflict(RuntimeError):
    """복구를 진행할 수 없다. 메시지는 **안정적인 사유 코드**다.

    사유를 문자열로 두는 이유는 이 값이 감사 기록·관리자 API(Task 8)까지
    그대로 흘러가기 때문이다 -- provider 원문이나 예외 텍스트를 그 자리에
    실으면 경계를 넘는다.
    """


class PortableArchiveInvalid(PortableRecoveryConflict):
    """아카이브 자체가 승인 근거가 될 수 없다.

    `PortableRecoveryConflict`의 하위다 -- 호출자는 대개 "복구 못 한다"만
    구별하면 되고, 아카이브 문제인지 승인 조건 문제인지는 사유 코드가 말한다.
    """

    def __init__(self, reason: str = "archive_invalid") -> None:
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class PortableArchiveManifest:
    archive_id: str
    allocation_id: str
    generation: int
    workspace_revision: str
    checksum: str
    content_bytes: int
    image_identity: str
    toolchain_identity: str
    encryption_key_ref: str
    scan_status: Literal["clean", "rejected"]
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if self.scan_status not in _SCAN_STATUSES:
            # "pending" 같은 제3의 값을 받아들이면 **아직 안 본 아카이브**가
            # 검사를 통과한 것처럼 흘러갈 수 있다.
            raise ValueError("scan_status must be 'clean' or 'rejected'")
        if self.content_bytes < 0:
            raise ValueError("content_bytes must not be negative")
        if self.generation <= 0:
            raise ValueError("generation must be positive")

    def to_json(self) -> str:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        payload["expires_at"] = self.expires_at.isoformat()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> "PortableArchiveManifest":
        try:
            payload = json.loads(value)
            return cls(
                archive_id=str(payload["archive_id"]),
                allocation_id=str(payload["allocation_id"]),
                generation=int(payload["generation"]),
                workspace_revision=str(payload["workspace_revision"]),
                checksum=str(payload["checksum"]),
                content_bytes=int(payload["content_bytes"]),
                image_identity=str(payload["image_identity"]),
                toolchain_identity=str(payload["toolchain_identity"]),
                encryption_key_ref=str(payload["encryption_key_ref"]),
                scan_status=payload["scan_status"],
                created_at=datetime.fromisoformat(payload["created_at"]),
                expires_at=datetime.fromisoformat(payload["expires_at"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            # 부분적으로 읽어 기본값을 채우지 않는다 -- 매니페스트를 추측하면
            # 그 추측 위에서 복구가 승인된다.
            raise PortableArchiveInvalid("archive_manifest_invalid") from error


class PortableArchiveStore(Protocol):
    """아카이브 본문과 매니페스트를 나눠 들고 있는 스토어.

    `read_body`가 `max_bytes`를 **받는다**는 것이 계약의 핵심이다 -- 다 읽은
    뒤에 크기를 재면 이미 늦다. 없는 아카이브에는 예외 대신 `None`을 낸다:
    "없다"는 이 층에서 정상적인 답이고, 그것을 복구 거절로 옮기는 것은
    서비스의 일이다.
    """

    async def read_manifest(
        self, archive_id: str
    ) -> PortableArchiveManifest | None: ...

    async def read_body(self, archive_id: str, *, max_bytes: int) -> bytes | None: ...

    async def put(
        self, manifest: PortableArchiveManifest, body: bytes
    ) -> None: ...

    async def delete(self, archive_id: str) -> None: ...


class ArchiveTooLarge(PortableArchiveInvalid):
    """스토어가 상한을 넘는 본문을 거부했다."""

    def __init__(self) -> None:
        super().__init__("archive_too_large")


class InMemoryPortableArchiveStore:
    """테스트와 결정론적 재현용 스토어."""

    def __init__(self) -> None:
        self._manifests: dict[str, PortableArchiveManifest] = {}
        self._bodies: dict[str, bytes] = {}

    @property
    def manifest(self) -> PortableArchiveManifest:
        """심어 둔 매니페스트가 하나뿐일 때의 편의 접근자."""
        return next(iter(self._manifests.values()))

    def seed(self, manifest: PortableArchiveManifest, body: bytes) -> None:
        self._manifests[manifest.archive_id] = manifest
        self._bodies[manifest.archive_id] = body

    def tamper(self, body: bytes) -> None:
        """매니페스트는 그대로 두고 본문만 바꾼다 -- 체크섬 검증을 겨눈다."""
        for archive_id in self._bodies:
            self._bodies[archive_id] = body

    async def read_manifest(
        self, archive_id: str
    ) -> PortableArchiveManifest | None:
        return self._manifests.get(archive_id)

    async def read_body(self, archive_id: str, *, max_bytes: int) -> bytes | None:
        body = self._bodies.get(archive_id)
        if body is None:
            return None
        if len(body) > max_bytes:
            raise ArchiveTooLarge()
        return body

    async def put(self, manifest: PortableArchiveManifest, body: bytes) -> None:
        self.seed(manifest, body)

    async def delete(self, archive_id: str) -> None:
        # 본문과 매니페스트를 **함께** 지운다. 하나만 남으면 "있는 줄 알았는데
        # 없는" 상태가 되고, 그 상태로 복구가 승인되면 빈 워크스페이스로
        # 되살아난다.
        self._manifests.pop(archive_id, None)
        self._bodies.pop(archive_id, None)


class ManagedRecoveryRepository(Protocol):
    async def read_allocation(
        self, allocation_id: str
    ) -> ManagedSandboxAllocation: ...

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
    ) -> ManagedSandboxAllocation: ...


class ManagedSandboxArchiveService:
    """아카이브를 검증하고, 검증된 것에 한해 복구 세대를 승인한다."""

    def __init__(
        self,
        *,
        repository: ManagedRecoveryRepository | None,
        store: PortableArchiveStore,
        image_identity: str,
        toolchain_identity: str,
        max_archive_bytes: int,
        max_archive_entries: int,
        policy_version: str,
        lifetime_seconds: int = 3600,
        reservation_lease_seconds: int = 60,
        clock=None,
    ) -> None:
        self._repository = repository
        self._store = store
        self._image_identity = image_identity
        self._toolchain_identity = toolchain_identity
        self._max_archive_bytes = max_archive_bytes
        self._max_archive_entries = max_archive_entries
        self._policy_version = policy_version
        self._lifetime_seconds = lifetime_seconds
        self._reservation_lease_seconds = reservation_lease_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    async def verify(
        self, archive_id: str, *, expected_checksum: str
    ) -> PortableArchiveManifest:
        """아카이브가 복구의 근거가 될 수 있는지 판정한다. 원장은 건드리지 않는다.

        순서에 의미가 있다. 스캔 상태와 보존기한은 **본문을 읽기 전에** 본다
        (거부될 아카이브를 굳이 메모리에 올리지 않는다). 체크섬은 tar 파싱보다
        먼저 본다 -- 우리가 승인한 바로 그 바이트가 아니면 그 안을 들여다볼
        이유가 없다.
        """
        manifest = await self._store.read_manifest(archive_id)
        if manifest is None:
            raise PortableArchiveInvalid("archive_missing")
        if manifest.scan_status != "clean":
            raise PortableRecoveryConflict("archive_scan_rejected")
        if manifest.expires_at <= self._clock():
            raise PortableRecoveryConflict("archive_expired")
        if (
            manifest.image_identity != self._image_identity
            or manifest.toolchain_identity != self._toolchain_identity
        ):
            # 다른 이미지에서 뜬 워크스페이스를 그대로 얹으면 빌드 산출물과
            # 런타임이 어긋난 채 조용히 굴러간다.
            raise PortableRecoveryConflict("archive_incompatible")
        if manifest.checksum != expected_checksum:
            # 운영자가 승인한 아카이브와 지금 스토어에 있는 아카이브가 같다는
            # 것을 증명하지 못하면 승인 자체가 의미를 잃는다.
            raise PortableArchiveInvalid()

        body = await self._store.read_body(
            archive_id, max_bytes=self._max_archive_bytes
        )
        if body is None:
            raise PortableArchiveInvalid("archive_missing")
        if len(body) != manifest.content_bytes:
            raise PortableArchiveInvalid()
        if hashlib.sha256(body).hexdigest() != manifest.checksum:
            raise PortableArchiveInvalid()
        try:
            validate_workspace_archive_bytes(
                body, max_entries=self._max_archive_entries
            )
        except (SandboxPolicyViolation, OSError, ValueError) as error:
            # 체크섬이 맞아도 내용이 안전하다는 뜻은 아니다 -- 체크섬은
            # "내가 승인한 바로 그 바이트"만 증명한다.
            raise PortableArchiveInvalid() from error
        return manifest

    async def approve_recovery(
        self,
        *,
        allocation_id: str,
        archive_checksum: str,
        operator_id: str,
    ) -> ManagedSandboxAllocation:
        """운영자 결정을 체크섬에 묶어 복구 세대를 만든다.

        `operator_id`는 **누가 승인했는지**를 감사 기록에 남기기 위한 것이고,
        그 사람이 관리자인지는 이 층이 아니라 API 경계(Task 8의 admin
        엔드포인트)가 판정한다. 여기서는 신원이 비어 있지 않다는 것만
        강제한다 -- 익명 승인은 승인이 아니다.
        """
        if self._repository is None:
            raise PortableRecoveryConflict("recovery_repository_unavailable")
        if not operator_id.strip():
            raise PortableRecoveryConflict("operator_unidentified")
        allocation = await self._repository.read_allocation(allocation_id)
        if allocation.state is not ManagedSandboxState.MANUAL_RECOVERY_REQUIRED:
            # 살아 있는 할당을 되살리면 원래의 provider 리소스가 고아가 된다.
            raise PortableRecoveryConflict("recovery_not_required")
        if not allocation.archive_ref:
            raise PortableArchiveInvalid("archive_missing")

        manifest = await self.verify(
            allocation.archive_ref, expected_checksum=archive_checksum
        )
        return await self._repository.approve_recovery_generation(
            allocation_id=allocation_id,
            operator_id=operator_id.strip(),
            archive_id=manifest.archive_id,
            checksum=manifest.checksum,
            policy_version=self._policy_version,
            lifetime_seconds=self._lifetime_seconds,
            reservation_lease_seconds=self._reservation_lease_seconds,
            now=self._clock(),
        )

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
import io
import json
import os
import re
import tarfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

from neos.coding.managed.domain import ManagedSandboxAllocation, ManagedSandboxState
from neos.coding.sandbox.base import SandboxPolicyViolation
from neos.coding.sandbox.archive import validate_workspace_archive_bytes


_SCAN_STATUSES = frozenset({"clean", "rejected"})


def archive_checksum(body: bytes) -> str:
    """아카이브 체크섬의 **정본 표기**: `sha256:<hex>`.

    맨 hexdigest 가 아니라 알고리즘 라벨을 붙인다. 두 가지 이유가 있다 --
    (1) `_ownership_digest_for()`가 이미 같은 표기를 쓰고, (2) 관리자 API 가
    `^sha256:[0-9a-f]{64}$` 로 요청을 검증하므로 저장 형식이 다르면 경계에서
    벗기고 붙이는 변환이 생기고, 그 변환이 한쪽에서만 빠지면 **모든 승인이
    조용히 거절**된다.
    """
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


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


_ARCHIVE_ID_PATTERN = re.compile(r"^pa_[0-9a-f]{32}$")
# `create_workspace_archive` 의 제외 목록과 **같은 규칙**이다. 아카이브는
# 스토어로 나가고 복구 때 다른 샌드박스로 들어간다 -- 한 번 실린 시크릿은
# 우리가 추적하지 않는 곳에 복제된다.
_EXCLUDED_PREFIXES = (".neos/secrets/",)
_EXCLUDED_PATHS = frozenset({".env", ".git/credentials"})


def _is_excluded(path: str) -> bool:
    return path in _EXCLUDED_PATHS or path.startswith(_EXCLUDED_PREFIXES)


class LocalPortableArchiveStore:
    """파일시스템 스토어. `LocalSnapshotStore` 와 같은 배치(본문 + 매니페스트)다.

    `archive_id` 가 경로가 되는 곳이므로 모양을 엄격히 검사한다 -- 탈출
    문자열이 들어오면 스토어 밖에 쓰거나 스토어 밖을 읽는다.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def path_for(self, archive_id: str) -> Path:
        if not _ARCHIVE_ID_PATTERN.match(archive_id):
            raise PortableArchiveInvalid("archive_id_invalid")
        return self._root / f"{archive_id}.json"

    def _body_path(self, archive_id: str) -> Path:
        return self.path_for(archive_id).with_suffix(".tar")

    async def read_manifest(
        self, archive_id: str
    ) -> PortableArchiveManifest | None:
        try:
            payload = self.path_for(archive_id).read_text()
        except FileNotFoundError:
            return None
        return PortableArchiveManifest.from_json(payload)

    async def read_body(self, archive_id: str, *, max_bytes: int) -> bytes | None:
        path = self._body_path(archive_id)
        try:
            # 크기를 **읽기 전에** 잰다. 다 읽은 뒤에 재면 이미 메모리에
            # 올라와 있고, 그게 바로 상한이 막으려던 것이다.
            if path.stat().st_size > max_bytes:
                raise ArchiveTooLarge()
            return path.read_bytes()
        except FileNotFoundError:
            return None

    async def put(self, manifest: PortableArchiveManifest, body: bytes) -> None:
        # 본문을 먼저, 매니페스트를 나중에 쓴다. 순서를 뒤집으면 "매니페스트는
        # 있는데 본문이 없는" 창이 생기고, 그 창에서 복구를 승인하면 빈
        # 워크스페이스로 되살아난다.
        body_path = self._body_path(manifest.archive_id)
        temporary = body_path.with_suffix(".tar.tmp")
        temporary.write_bytes(body)
        os.replace(temporary, body_path)
        manifest_path = self.path_for(manifest.archive_id)
        manifest_temporary = manifest_path.with_suffix(".json.tmp")
        manifest_temporary.write_text(manifest.to_json())
        os.replace(manifest_temporary, manifest_path)

    async def delete(self, archive_id: str) -> None:
        # 매니페스트를 먼저 지운다 -- 본문만 남는 것은 낭비지만, 매니페스트만
        # 남는 것은 "있는 줄 알았는데 없는" 상태다.
        self.path_for(archive_id).unlink(missing_ok=True)
        self._body_path(archive_id).unlink(missing_ok=True)


class SessionPortableArchiveBuilder:
    """살아 있는 샌드박스에서 portable 아카이브를 뜬다.

    **세션 계약만 쓴다** (`list_tree`/`read_file`/`workspace_revision`).
    Docker 스냅샷 같은 provider 고유 기능에 기대면 크로스 프로바이더 복구라는
    목적 자체가 사라진다 -- 그것이 "portable" 이 뜻하는 바다.
    """

    def __init__(
        self,
        *,
        store: PortableArchiveStore,
        image_identity: str,
        toolchain_identity: str,
        max_archive_bytes: int,
        max_archive_entries: int,
        retention_seconds: int,
        clock=None,
    ) -> None:
        self._store = store
        self._image_identity = image_identity
        self._toolchain_identity = toolchain_identity
        self._max_archive_bytes = max_archive_bytes
        self._max_archive_entries = max_archive_entries
        self._retention_seconds = retention_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    async def build(
        self, session, *, allocation_id: str, generation: int
    ) -> PortableArchiveManifest:
        entries = [
            entry
            for entry in await session.list_tree()
            if entry.kind == "file" and not _is_excluded(entry.path)
        ]
        if len(entries) > self._max_archive_entries:
            raise PortableArchiveInvalid("archive_too_many_entries")

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for entry in sorted(entries, key=lambda item: item.path):
                content = await session.read_file(entry.path)
                info = tarfile.TarInfo(entry.path)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
        body = buffer.getvalue()
        if len(body) > self._max_archive_bytes:
            raise ArchiveTooLarge()

        now = self._clock()
        manifest = PortableArchiveManifest(
            archive_id=f"pa_{uuid4().hex}",
            allocation_id=allocation_id,
            generation=generation,
            workspace_revision=str(await session.workspace_revision()),
            checksum=archive_checksum(body),
            content_bytes=len(body),
            image_identity=self._image_identity,
            toolchain_identity=self._toolchain_identity,
            # 봉인은 스토어 계층의 일이다. 지금 로컬 스토어는 봉인하지 않으므로
            # 그 사실을 매니페스트에 정직하게 적는다 -- "암호화됨"이라고
            # 적어 두고 실제로는 평문인 것이 가장 나쁘다.
            encryption_key_ref="none",
            scan_status="clean",
            created_at=now,
            expires_at=now + timedelta(seconds=self._retention_seconds),
        )
        await self._store.put(manifest, body)
        return manifest


class SessionPortableArchiveImporter:
    """복구 세대의 워크스페이스를 되살린다 (`PortableArchiveImporter` 구현).

    **검증이 쓰기보다 먼저다.** 반쯤 쓰고 실패하면 사용자는 절반만 복구된
    워크스페이스를 얻고 그것이 원본인 줄 안다.

    워크스페이스만 되살린다 -- PTY 도 백그라운드 프로세스도 만들지 않는다.
    """

    def __init__(
        self,
        *,
        store: PortableArchiveStore,
        open_session,
        max_archive_bytes: int,
        max_archive_entries: int,
    ) -> None:
        self._store = store
        self._open_session = open_session
        self._max_archive_bytes = max_archive_bytes
        self._max_archive_entries = max_archive_entries

    async def import_archive(
        self, *, allocation, provider_ref: str, archive_id: str
    ) -> None:
        del allocation
        manifest = await self._store.read_manifest(archive_id)
        if manifest is None:
            raise PortableArchiveInvalid("archive_missing")
        body = await self._store.read_body(
            archive_id, max_bytes=self._max_archive_bytes
        )
        if body is None:
            raise PortableArchiveInvalid("archive_missing")
        if archive_checksum(body) != manifest.checksum:
            raise PortableArchiveInvalid()
        try:
            validate_workspace_archive_bytes(
                body, max_entries=self._max_archive_entries
            )
        except (SandboxPolicyViolation, OSError, ValueError) as error:
            raise PortableArchiveInvalid() from error

        session = self._open_session(provider_ref)
        if hasattr(session, "__await__"):
            session = await session
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise PortableArchiveInvalid()
                await session.write_file(member.name, extracted.read())


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
        if archive_checksum(body) != manifest.checksum:
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

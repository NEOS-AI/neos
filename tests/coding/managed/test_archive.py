"""portable 아카이브의 매니페스트·스토어·검증 테스트.

여기서 보는 것은 **원장을 건드리기 전에 무엇을 거절하는가**다. 승인 트랜잭션
자체는 `test_recovery.py`가 본다.

검증이 이 순서로 서는 이유: 아카이브 본문은 신뢰할 수 없는 입력이고
(운영 사고·공격 둘 다), 검증을 통과한 뒤에야 새 세대를 만들기 때문에
여기서 새는 것은 곧바로 "복구했더니 남의 워크스페이스" 가 된다.
"""

import hashlib
import io
import tarfile
from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.archive import (
    InMemoryPortableArchiveStore,
    ManagedSandboxArchiveService,
    PortableArchiveInvalid,
    PortableArchiveManifest,
    PortableRecoveryConflict,
)
from neos.coding.managed.domain import ManagedSandboxState


NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
_IMAGE = "neos-sandbox@sha256:" + "b" * 64
_TOOLCHAIN = "python3.12+node22"


def workspace_body(*, name: str = "main.py", data: bytes = b"print(1)\n") -> bytes:
    """정상적인 워크스페이스 tar 하나."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def escaping_body() -> bytes:
    """워크스페이스 밖을 가리키는 멤버가 든 tar."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo("../../etc/passwd")
        info.size = 0
        archive.addfile(info, io.BytesIO(b""))
    return buffer.getvalue()


def manifest_for(
    body: bytes,
    *,
    checksum: str | None = None,
    content_bytes: int | None = None,
    scan_status: str = "clean",
    image_identity: str = _IMAGE,
    toolchain_identity: str = _TOOLCHAIN,
    expires_at: datetime = NOW + timedelta(days=1),
) -> PortableArchiveManifest:
    return PortableArchiveManifest(
        archive_id="pa_1",
        allocation_id="msa_1",
        generation=1,
        workspace_revision="rev_7",
        checksum=checksum or hashlib.sha256(body).hexdigest(),
        content_bytes=len(body) if content_bytes is None else content_bytes,
        image_identity=image_identity,
        toolchain_identity=toolchain_identity,
        encryption_key_ref="managed-archive-key/1",
        scan_status=scan_status,
        created_at=NOW - timedelta(hours=1),
        expires_at=expires_at,
    )


def archive_service(
    *, body: bytes | None = None, manifest: PortableArchiveManifest | None = None
) -> tuple[ManagedSandboxArchiveService, InMemoryPortableArchiveStore]:
    body = workspace_body() if body is None else body
    manifest = manifest or manifest_for(body)
    store = InMemoryPortableArchiveStore()
    store.seed(manifest, body)
    service = ManagedSandboxArchiveService(
        repository=None,
        store=store,
        image_identity=_IMAGE,
        toolchain_identity=_TOOLCHAIN,
        max_archive_bytes=1024 * 1024,
        max_archive_entries=100,
        policy_version="managed-v1",
        clock=lambda: NOW,
    )
    return service, store


# --- 매니페스트 왕복 -------------------------------------------------------


def test_manifest_round_trips_through_json() -> None:
    """스토어가 매니페스트를 JSON 으로 들고 있으므로 왕복이 무손실이어야 한다."""
    manifest = manifest_for(workspace_body())

    assert PortableArchiveManifest.from_json(manifest.to_json()) == manifest


def test_a_corrupt_manifest_is_rejected_not_guessed() -> None:
    with pytest.raises(PortableArchiveInvalid):
        PortableArchiveManifest.from_json('{"archive_id": "pa_1"}')


def test_manifest_rejects_an_unknown_scan_status() -> None:
    """`clean`/`rejected` 밖의 값은 '아직 안 봤다'와 구별되지 않는다."""
    with pytest.raises(ValueError):
        manifest_for(workspace_body(), scan_status="pending")


# --- 검증 -----------------------------------------------------------------


async def test_a_tampered_body_fails_the_checksum() -> None:
    service, store = archive_service()
    store.tamper(b"tampered")

    with pytest.raises(PortableRecoveryConflict, match="archive_invalid"):
        await service.verify("pa_1", expected_checksum=store.manifest.checksum)


async def test_a_checksum_the_caller_did_not_expect_is_rejected() -> None:
    """호출자가 든 체크섬과 매니페스트가 다르면 **둘 중 무엇이 맞든** 거절한다.

    운영자가 승인한 아카이브와 지금 스토어에 있는 아카이브가 같다는 것을
    증명하지 못하면 승인의 의미가 없다.
    """
    service, _store = archive_service()

    with pytest.raises(PortableRecoveryConflict, match="archive_invalid"):
        await service.verify("pa_1", expected_checksum="sha256:not-this-one")


async def test_a_size_that_disagrees_with_the_manifest_is_rejected() -> None:
    body = workspace_body()
    service, _store = archive_service(
        body=body, manifest=manifest_for(body, content_bytes=len(body) + 1)
    )

    with pytest.raises(PortableRecoveryConflict, match="archive_invalid"):
        await service.verify("pa_1", expected_checksum=_checksum(body))


async def test_a_rejected_scan_never_becomes_a_recovery_source() -> None:
    body = workspace_body()
    service, _store = archive_service(
        body=body, manifest=manifest_for(body, scan_status="rejected")
    )

    with pytest.raises(PortableRecoveryConflict, match="archive_scan_rejected"):
        await service.verify("pa_1", expected_checksum=_checksum(body))


async def test_an_expired_archive_is_not_revived() -> None:
    """보존기한이 지난 워크스페이스로 되살리면 사용자가 잃은 줄도 모르는 작업이 생긴다."""
    body = workspace_body()
    service, _store = archive_service(
        body=body,
        manifest=manifest_for(body, expires_at=NOW - timedelta(seconds=1)),
    )

    with pytest.raises(PortableRecoveryConflict, match="archive_expired"):
        await service.verify("pa_1", expected_checksum=_checksum(body))


async def test_a_different_image_identity_is_incompatible() -> None:
    body = workspace_body()
    service, _store = archive_service(
        body=body, manifest=manifest_for(body, image_identity="other@sha256:" + "0" * 64)
    )

    with pytest.raises(PortableRecoveryConflict, match="archive_incompatible"):
        await service.verify("pa_1", expected_checksum=_checksum(body))


async def test_a_different_toolchain_is_incompatible() -> None:
    body = workspace_body()
    service, _store = archive_service(
        body=body, manifest=manifest_for(body, toolchain_identity="python3.11")
    )

    with pytest.raises(PortableRecoveryConflict, match="archive_incompatible"):
        await service.verify("pa_1", expected_checksum=_checksum(body))


async def test_a_path_escaping_member_is_rejected() -> None:
    """체크섬이 맞아도 내용이 안전하다는 뜻은 아니다.

    체크섬은 '내가 승인한 바로 그 바이트'를 증명할 뿐이고, 그 바이트가
    워크스페이스 밖을 가리키지 않는다는 것은 별도 검증이다.
    """
    body = escaping_body()
    service, _store = archive_service(body=body, manifest=manifest_for(body))

    with pytest.raises(PortableRecoveryConflict, match="archive_invalid"):
        await service.verify("pa_1", expected_checksum=_checksum(body))


async def test_too_many_entries_is_rejected_before_expansion() -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for index in range(5):
            info = tarfile.TarInfo(f"f{index}.txt")
            info.size = 0
            archive.addfile(info, io.BytesIO(b""))
    body = buffer.getvalue()
    service, _store = archive_service(body=body, manifest=manifest_for(body))
    service._max_archive_entries = 4

    with pytest.raises(PortableRecoveryConflict, match="archive_invalid"):
        await service.verify("pa_1", expected_checksum=_checksum(body))


async def test_an_oversized_archive_is_refused_by_the_store() -> None:
    """상한은 스토어가 든다 -- 서비스가 다 읽은 뒤에 재면 이미 늦다."""
    body = workspace_body(data=b"x" * 4096)
    service, _store = archive_service(body=body, manifest=manifest_for(body))
    service._max_archive_bytes = 16

    with pytest.raises(PortableRecoveryConflict, match="archive_too_large"):
        await service.verify("pa_1", expected_checksum=_checksum(body))


async def test_a_missing_archive_is_not_silently_treated_as_empty() -> None:
    service, _store = archive_service()

    with pytest.raises(PortableRecoveryConflict, match="archive_missing"):
        await service.verify("pa_absent", expected_checksum="sha256:whatever")


async def test_a_valid_archive_returns_its_manifest() -> None:
    body = workspace_body()
    service, store = archive_service(body=body)

    manifest = await service.verify("pa_1", expected_checksum=_checksum(body))

    assert manifest == store.manifest


# --- 스토어 계약 -----------------------------------------------------------


async def test_delete_removes_both_manifest_and_body() -> None:
    """본문만 지우고 매니페스트가 남으면 '있는 줄 알았는데 없는' 상태가 된다."""
    _service, store = archive_service()

    await store.delete("pa_1")

    assert await store.read_manifest("pa_1") is None
    assert await store.read_body("pa_1", max_bytes=1024) is None


def test_archive_state_is_not_a_sandbox_state() -> None:
    """`scan_status`는 할당 상태가 아니다 -- 두 어휘를 섞지 않는다."""
    assert "clean" not in {state.value for state in ManagedSandboxState}


def _checksum(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()

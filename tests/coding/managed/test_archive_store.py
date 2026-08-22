"""아카이브를 **뜨고 되살리는** 경로 (CA10).

Task 7은 검증과 승인을 지었지만 아카이브를 실제로 만드는 경로가 없었다 --
복구가 구조상 가능하지만 운영상 재료가 없는 상태였다. 여기가 그 재료를
만든다.

**세션 계약만 쓴다.** `SandboxSession` 의 `list_tree`/`read_file`/`write_file`
넷으로 뜨고 되살리므로 Docker·memory·E2B·Modal 어디서든 같은 코드가 돈다 --
그것이 "portable" 이 뜻하는 바다. Docker 스냅샷 같은 provider 고유 기능에
기대면 크로스 프로바이더 복구라는 목적 자체가 사라진다.

이 스위트는 **실제 메모리 샌드박스**를 쓴다. fake 세션을 쓰면 세션 계약을
내가 기억하는 대로 흉내 내게 되고, 그 기억이 틀린 곳은 테스트가 못 잡는다.
"""

from datetime import UTC, datetime, timedelta

import pytest

from neos.coding.managed.archive import (
    LocalPortableArchiveStore,
    ManagedSandboxArchiveService,
    PortableArchiveInvalid,
    PortableRecoveryConflict,
    SessionPortableArchiveBuilder,
    SessionPortableArchiveImporter,
    archive_checksum,
)
from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.memory import MemorySandboxProvider


pytestmark = pytest.mark.no_db

NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)
_IMAGE = "neos-sandbox@sha256:" + "b" * 64
_ABSENT_ID = "pa_" + "0" * 32
_TOOLCHAIN = "python3.12"


async def _session(tmp_path, files: dict[str, bytes]):
    provider = MemorySandboxProvider(root=tmp_path / "sandboxes")
    sandbox = await provider.create(
        owner_id="u1", limits=SandboxLimits.safe_defaults()
    )
    session = await provider.open_session(sandbox.sandbox_id)
    for path, content in files.items():
        await session.write_file(path, content)
    return provider, session


def _builder(store, **overrides) -> SessionPortableArchiveBuilder:
    options = {
        "store": store,
        "image_identity": _IMAGE,
        "toolchain_identity": _TOOLCHAIN,
        "max_archive_bytes": 1024 * 1024,
        "max_archive_entries": 100,
        "retention_seconds": 7 * 24 * 3600,
        "clock": lambda: NOW,
    }
    options.update(overrides)
    return SessionPortableArchiveBuilder(**options)


# --- 로컬 스토어 -----------------------------------------------------------


async def test_the_local_store_round_trips_a_manifest_and_body(tmp_path) -> None:
    store = LocalPortableArchiveStore(tmp_path / "archives")
    provider, session = await _session(tmp_path, {"main.py": b"print(1)\n"})
    try:
        manifest = await _builder(store).build(
            session, allocation_id="msa_1", generation=1
        )
    finally:
        await provider.close()

    assert await store.read_manifest(manifest.archive_id) == manifest
    body = await store.read_body(manifest.archive_id, max_bytes=1024 * 1024)
    assert body is not None
    assert archive_checksum(body) == manifest.checksum


async def test_the_local_store_refuses_to_read_beyond_the_bound(tmp_path) -> None:
    """상한은 **읽기 전에** 걸린다 -- 다 읽은 뒤에 재면 이미 메모리에 올라와 있다."""
    store = LocalPortableArchiveStore(tmp_path / "archives")
    provider, session = await _session(tmp_path, {"main.py": b"x" * 4096})
    try:
        manifest = await _builder(store).build(
            session, allocation_id="msa_1", generation=1
        )
    finally:
        await provider.close()

    with pytest.raises(PortableArchiveInvalid, match="archive_too_large"):
        await store.read_body(manifest.archive_id, max_bytes=16)


async def test_a_missing_archive_reads_as_none_not_an_error(tmp_path) -> None:
    """모양은 맞는데 없는 것은 정상적인 `None` 이다."""
    store = LocalPortableArchiveStore(tmp_path / "archives")

    assert await store.read_manifest(_ABSENT_ID) is None
    assert await store.read_body(_ABSENT_ID, max_bytes=1024) is None


async def test_a_malformed_archive_id_is_an_error_not_a_miss(tmp_path) -> None:
    """"모양이 틀렸다"와 "없다"는 다른 조건이다.

    합치면 손상된 `archive_ref` 를 든 할당이 조용히 "아카이브 없음"으로
    읽히고, 그 원인이 원장 어디에도 남지 않는다.
    """
    store = LocalPortableArchiveStore(tmp_path / "archives")

    with pytest.raises(PortableArchiveInvalid, match="archive_id"):
        await store.read_manifest("pa_absent")


async def test_delete_removes_both_sides(tmp_path) -> None:
    store = LocalPortableArchiveStore(tmp_path / "archives")
    provider, session = await _session(tmp_path, {"main.py": b"print(1)\n"})
    try:
        manifest = await _builder(store).build(
            session, allocation_id="msa_1", generation=1
        )
    finally:
        await provider.close()

    await store.delete(manifest.archive_id)

    assert await store.read_manifest(manifest.archive_id) is None
    assert await store.read_body(manifest.archive_id, max_bytes=1024) is None


def test_the_store_rejects_a_traversing_archive_id(tmp_path) -> None:
    """archive_id 가 경로가 되는 곳이므로 탈출을 막는다."""
    store = LocalPortableArchiveStore(tmp_path / "archives")

    for hostile in ("../secret", "a/b", "", "pa_1/../.."):
        with pytest.raises(PortableArchiveInvalid, match="archive_id"):
            store.path_for(hostile)


# --- 아카이브를 뜬다 -------------------------------------------------------


async def test_the_builder_captures_the_workspace(tmp_path) -> None:
    store = LocalPortableArchiveStore(tmp_path / "archives")
    provider, session = await _session(
        tmp_path, {"main.py": b"print(1)\n", "pkg/util.py": b"X = 1\n"}
    )
    try:
        manifest = await _builder(store).build(
            session, allocation_id="msa_1", generation=2
        )
    finally:
        await provider.close()

    assert manifest.allocation_id == "msa_1"
    assert manifest.generation == 2
    assert manifest.image_identity == _IMAGE
    assert manifest.toolchain_identity == _TOOLCHAIN
    assert manifest.scan_status == "clean"
    assert manifest.expires_at == NOW + timedelta(days=7)
    assert manifest.content_bytes > 0


async def test_the_builder_never_captures_secrets(tmp_path) -> None:
    """`.env` 와 `.neos/secrets/` 는 아카이브에 들어가면 안 된다.

    아카이브는 스토어로 나가고 복구 때 다른 샌드박스로 들어간다 -- 한 번
    실리면 그 시크릿은 우리가 추적하지 않는 곳에 복제된다.
    `create_workspace_archive` 가 이미 쓰는 제외 목록과 같은 규칙이다.
    """
    store = LocalPortableArchiveStore(tmp_path / "archives")
    provider, session = await _session(
        tmp_path,
        {
            "main.py": b"print(1)\n",
            ".env": b"SECRET=1\n",
            ".neos/secrets/token": b"tok\n",
        },
    )
    try:
        manifest = await _builder(store).build(
            session, allocation_id="msa_1", generation=1
        )
    finally:
        await provider.close()

    body = await store.read_body(manifest.archive_id, max_bytes=1024 * 1024)
    assert body is not None
    assert b"SECRET=1" not in body
    assert b"tok" not in body
    assert b"print(1)" in body


async def test_the_builder_refuses_a_workspace_over_the_size_bound(tmp_path) -> None:
    store = LocalPortableArchiveStore(tmp_path / "archives")
    provider, session = await _session(tmp_path, {"big.bin": b"x" * 8192})
    try:
        with pytest.raises(PortableArchiveInvalid, match="archive_too_large"):
            await _builder(store, max_archive_bytes=256).build(
                session, allocation_id="msa_1", generation=1
            )
    finally:
        await provider.close()


async def test_the_builder_refuses_too_many_entries(tmp_path) -> None:
    store = LocalPortableArchiveStore(tmp_path / "archives")
    provider, session = await _session(
        tmp_path, {f"f{index}.txt": b"x" for index in range(5)}
    )
    try:
        with pytest.raises(PortableArchiveInvalid, match="archive_too_many_entries"):
            await _builder(store, max_archive_entries=3).build(
                session, allocation_id="msa_1", generation=1
            )
    finally:
        await provider.close()


async def test_a_built_archive_passes_the_verification_it_will_face(
    tmp_path,
) -> None:
    """뜬 것이 곧바로 승인 검증을 통과해야 한다.

    빌더와 검증기가 같은 규칙 위에 있지 않으면, 만들어 둔 아카이브가 정작
    복구가 필요한 순간에 거절된다 -- 그때는 이미 늦다.
    """
    store = LocalPortableArchiveStore(tmp_path / "archives")
    provider, session = await _session(tmp_path, {"main.py": b"print(1)\n"})
    try:
        manifest = await _builder(store).build(
            session, allocation_id="msa_1", generation=1
        )
    finally:
        await provider.close()
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

    verified = await service.verify(
        manifest.archive_id, expected_checksum=manifest.checksum
    )

    assert verified == manifest


# --- 아카이브를 되살린다 ---------------------------------------------------


async def test_the_importer_restores_the_workspace_into_a_new_sandbox(
    tmp_path,
) -> None:
    store = LocalPortableArchiveStore(tmp_path / "archives")
    source_provider, source = await _session(
        tmp_path, {"main.py": b"print(1)\n", "pkg/util.py": b"X = 1\n"}
    )
    try:
        manifest = await _builder(store).build(
            source, allocation_id="msa_1", generation=1
        )
    finally:
        await source_provider.close()

    target_provider, target = await _session(tmp_path, {})
    try:
        await SessionPortableArchiveImporter(
            store=store,
            open_session=lambda _ref: target,
            max_archive_bytes=1024 * 1024,
            max_archive_entries=100,
        ).import_archive(
            allocation=None, provider_ref="ignored", archive_id=manifest.archive_id
        )

        assert await target.read_file("main.py") == b"print(1)\n"
        assert await target.read_file("pkg/util.py") == b"X = 1\n"
    finally:
        await target_provider.close()


async def test_the_importer_refuses_a_tampered_body(tmp_path) -> None:
    """체크섬이 안 맞으면 **아무것도 쓰지 않는다.**

    반쯤 쓰고 실패하면 사용자는 절반만 복구된 워크스페이스를 얻고, 그것이
    원본인 줄 안다.
    """
    store = LocalPortableArchiveStore(tmp_path / "archives")
    source_provider, source = await _session(tmp_path, {"main.py": b"print(1)\n"})
    try:
        manifest = await _builder(store).build(
            source, allocation_id="msa_1", generation=1
        )
    finally:
        await source_provider.close()
    store.path_for(manifest.archive_id).with_suffix(".tar").write_bytes(b"tampered")

    target_provider, target = await _session(tmp_path, {})
    try:
        with pytest.raises(PortableRecoveryConflict, match="archive_invalid"):
            await SessionPortableArchiveImporter(
                store=store,
                open_session=lambda _ref: target,
                max_archive_bytes=1024 * 1024,
                max_archive_entries=100,
            ).import_archive(
                allocation=None,
                provider_ref="ignored",
                archive_id=manifest.archive_id,
            )

        assert await target.list_tree() == ()
    finally:
        await target_provider.close()


async def test_the_importer_refuses_a_missing_archive(tmp_path) -> None:
    store = LocalPortableArchiveStore(tmp_path / "archives")
    target_provider, target = await _session(tmp_path, {})
    try:
        with pytest.raises(PortableRecoveryConflict, match="archive_missing"):
            await SessionPortableArchiveImporter(
                store=store,
                open_session=lambda _ref: target,
                max_archive_bytes=1024 * 1024,
                max_archive_entries=100,
            ).import_archive(
                allocation=None, provider_ref="ignored", archive_id=_ABSENT_ID
            )
    finally:
        await target_provider.close()

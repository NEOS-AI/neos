"""Fake E2B / Modal SDKs over a real local `neos-sandboxd`.

Each fake vendor object is a `LocalSandboxd` in its own directory, so the
guest daemon and host client run unmodified. The fakes encode the vendor
semantics the review names (docs/MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md):

* E2B: `allow_internet_access`, pause/connect keep the same object (processes
  survive), a snapshot drops live connections while the sandbox keeps running.
* Modal: `block_network`, unique running names (409), filesystem snapshots
  that expire after a TTL, no suspend -- terminate plus create-from-image.

Faults are queued per operation. Vendor errors carry a fake token in their
message so tests can prove sanitization drops it.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.managed.clients.base import SANDBOXD_CONNECT_ARGV
from neos.coding.sandbox.managed.clients.e2b import E2BProviderClient, E2BSandboxInfo
from neos.coding.sandbox.managed.clients.modal import ModalProviderClient, ModalSandboxInfo
from neos.coding.sandbox.managed.identity import (
    METADATA_OWNERSHIP_DIGEST,
    SandboxIdentity,
)
from neos.coding.sandbox.managed.ledger import InMemorySandboxLedger
from neos.coding.sandbox.managed.profiles import OFFLINE_V1, SandboxProfile
from neos.coding.sandbox.managed.provider import ManagedSandboxProvider
from neos.coding.sandboxd.client import SandboxdExpectation
from neos.coding.sandboxd.local import LocalSandboxd

IMAGE = "registry.example/neos-sandbox@sha256:" + "0" * 64
KEY = b"k" * 32
LEAKED_TOKEN = "sk-live-VENDOR-SECRET"
ALLOWED_ENV = frozenset({"HOME", "LANG", "LC_ALL", "PATH", "TERM", "TMPDIR"})

# Fault markers for `create`.
THEN_TIMEOUT = "create_then_timeout"
THEN_LOST = "create_then_lost_response"
DUPLICATE = "create_duplicate"
# Fault marker for kill/terminate: the object is killed but the call times out.
KILLED_THEN_TIMEOUT = "killed_then_timeout"


class VendorHTTPError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status} request_id=req_42 token={LEAKED_TOKEN}")
        self.status_code = status


class NotFoundError(VendorHTTPError):
    def __init__(self) -> None:
        super().__init__(404)


class AlreadyExistsError(VendorHTTPError):
    def __init__(self) -> None:
        super().__init__(409)


class ServiceBusy(VendorHTTPError):
    def __init__(self) -> None:
        super().__init__(503)


@dataclass
class FakeObject:
    object_id: str
    name: str
    metadata: dict[str, str]
    region: str
    network_open: bool
    daemon: LocalSandboxd
    state: str = "running"  # running | paused | terminated


@dataclass
class FakeVendor:
    root: Path
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    objects: dict[str, FakeObject] = field(default_factory=dict)
    snapshots: dict[str, tuple[Path, datetime | None]] = field(default_factory=dict)
    faults: dict[str, list[object]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    # Misbehaving-vendor knobs.
    report_region: str | None = None
    open_network: bool = False
    tamper_digest: bool = False
    _sequence: int = 0

    def fault(self, operation: str, *faults: object) -> None:
        self.faults.setdefault(operation, []).extend(faults)

    def take(self, operation: str) -> object | None:
        self.calls.append(operation)
        queue = self.faults.get(operation)
        return queue.pop(0) if queue else None

    def count(self, operation: str) -> int:
        return self.calls.count(operation)

    def live(self) -> list[FakeObject]:
        return [obj for obj in self.objects.values() if obj.state != "terminated"]

    async def spawn(
        self, *, name: str, metadata: Mapping[str, str], region: str, network_open: bool,
        source: str | None,
    ) -> FakeObject:
        self._sequence += 1
        object_id = f"obj-{self._sequence}"
        root = self.root / object_id
        if source is not None:
            shutil.copytree(self.snapshots[source][0], root, symlinks=True)
        daemon = LocalSandboxd(root)
        await daemon.start()
        obj = FakeObject(
            object_id=object_id,
            name=name,
            metadata=dict(metadata),
            region=self.report_region or region,
            network_open=network_open or self.open_network,
            daemon=daemon,
        )
        self.objects[object_id] = obj
        return obj

    async def create_with_faults(self, operation: str, spawn: Callable) -> FakeObject:
        fault = self.take(operation)
        if isinstance(fault, BaseException):
            raise fault
        obj = await spawn()
        if fault == DUPLICATE:
            await spawn()
        elif fault == THEN_TIMEOUT:
            raise TimeoutError("create accepted, response timed out")
        elif fault == THEN_LOST:
            raise ConnectionResetError("connection reset by peer")
        return obj

    def get(self, object_id: str) -> FakeObject:
        obj = self.objects.get(object_id)
        if obj is None or obj.state == "terminated":
            raise NotFoundError()
        return obj

    async def kill(self, operation: str, object_id: str) -> bool:
        fault = self.take(operation)
        if isinstance(fault, BaseException):
            raise fault
        obj = self.objects.get(object_id)
        if obj is None or obj.state == "terminated":
            return False
        await obj.daemon.stop()
        obj.state = "terminated"
        if fault == KILLED_THEN_TIMEOUT:
            raise TimeoutError("kill response lost")
        return True

    def snapshot(self, object_id: str, ttl: timedelta | None) -> tuple[str, datetime | None]:
        obj = self.get(object_id)
        snapshot_id = f"snap-{len(self.snapshots) + 1}"
        destination = self.root / snapshot_id
        obj.daemon.copy_to(destination)
        expires_at = None if ttl is None else self.clock() + ttl
        self.snapshots[snapshot_id] = (destination, expires_at)
        return snapshot_id, expires_at

    def snapshot_exists(self, snapshot_id: str) -> bool:
        entry = self.snapshots.get(snapshot_id)
        if entry is None:
            return False
        expires_at = entry[1]
        return expires_at is None or self.clock() < expires_at

    def metadata(self, obj: FakeObject) -> dict[str, str]:
        metadata = dict(obj.metadata)
        if self.tamper_digest:
            metadata[METADATA_OWNERSHIP_DIGEST] = "hmac-sha256:" + "f" * 64
        return metadata

    async def close(self) -> None:
        for obj in self.objects.values():
            await obj.daemon.stop()


class FakeE2BSdk:
    reports_network_policy = True

    def __init__(self, vendor: FakeVendor) -> None:
        self.vendor = vendor

    def _info(self, obj: FakeObject) -> E2BSandboxInfo:
        return E2BSandboxInfo(
            sandbox_id=obj.object_id,
            state=obj.state,
            metadata=self.vendor.metadata(obj),
            allow_internet_access=obj.network_open,
            region=obj.region,
        )

    async def create(self, *, template, metadata, allow_internet_access, timeout_seconds, region, snapshot_id):
        assert template == IMAGE or snapshot_id is not None
        obj = await self.vendor.create_with_faults(
            "create",
            lambda: self.vendor.spawn(
                name=metadata.get("neos_allocation_id", ""),
                metadata=metadata,
                region=region,
                network_open=allow_internet_access,
                source=snapshot_id,
            ),
        )
        return self._info(obj)

    async def list(self, *, metadata: Mapping[str, str]) -> Sequence[E2BSandboxInfo]:
        fault = self.vendor.take("list")
        if isinstance(fault, BaseException):
            raise fault
        return [
            self._info(obj)
            for obj in self.vendor.live()
            if all(obj.metadata.get(key) == value for key, value in metadata.items())
        ]

    async def get_info(self, sandbox_id: str) -> E2BSandboxInfo:
        fault = self.vendor.take("get_info")
        if isinstance(fault, BaseException):
            raise fault
        return self._info(self.vendor.get(sandbox_id))

    async def pause(self, sandbox_id: str) -> None:
        fault = self.vendor.take("pause")
        if isinstance(fault, BaseException):
            raise fault
        obj = self.vendor.get(sandbox_id)
        await obj.daemon.drop_connections()
        obj.state = "paused"

    async def connect(self, sandbox_id: str) -> E2BSandboxInfo:
        fault = self.vendor.take("connect")
        if isinstance(fault, BaseException):
            raise fault
        obj = self.vendor.get(sandbox_id)
        obj.state = "running"
        return self._info(obj)

    async def create_snapshot(self, sandbox_id: str):
        fault = self.vendor.take("create_snapshot")
        if isinstance(fault, BaseException):
            raise fault
        snapshot = self.vendor.snapshot(sandbox_id, ttl=None)
        # Running again after a brief pause, but every live connection drops.
        await self.vendor.get(sandbox_id).daemon.drop_connections()
        return snapshot

    async def snapshot_exists(self, snapshot_id: str) -> bool:
        return self.vendor.snapshot_exists(snapshot_id)

    async def kill(self, sandbox_id: str) -> bool:
        return await self.vendor.kill("kill", sandbox_id)

    async def open_stdio(self, sandbox_id: str, argv: Sequence[str]):
        assert tuple(argv) == SANDBOXD_CONNECT_ARGV
        fault = self.vendor.take("open_stdio")
        if isinstance(fault, BaseException):
            raise fault
        obj = self.vendor.get(sandbox_id)
        if obj.state != "running":
            raise VendorHTTPError(409)
        return await obj.daemon.open_channel()


class FakeModalSdk:
    reports_network_policy = True

    def __init__(self, vendor: FakeVendor, *, snapshot_ttl: timedelta = timedelta(days=30)) -> None:
        self.vendor = vendor
        self.snapshot_ttl = snapshot_ttl

    def _info(self, obj: FakeObject) -> ModalSandboxInfo:
        return ModalSandboxInfo(
            object_id=obj.object_id,
            name=obj.name,
            status="running" if obj.state == "running" else "terminated",
            tags=self.vendor.metadata(obj),
            block_network=not obj.network_open,
            region=obj.region,
        )

    async def create(self, *, image, name, tags, block_network, timeout_seconds, region):
        assert timeout_seconds <= 24 * 3600
        if any(obj.name == name for obj in self.vendor.live()):
            self.vendor.calls.append("create")
            raise AlreadyExistsError()
        source = image if image in self.vendor.snapshots else None
        assert source is not None or image == IMAGE
        obj = await self.vendor.create_with_faults(
            "create",
            lambda: self.vendor.spawn(
                name=name, metadata=tags, region=region, network_open=not block_network,
                source=source,
            ),
        )
        return self._info(obj)

    async def list(self, *, tags: Mapping[str, str]) -> Sequence[ModalSandboxInfo]:
        fault = self.vendor.take("list")
        if isinstance(fault, BaseException):
            raise fault
        return [
            self._info(obj)
            for obj in self.vendor.live()
            if all(obj.metadata.get(key) == value for key, value in tags.items())
        ]

    async def from_id(self, object_id: str) -> ModalSandboxInfo:
        fault = self.vendor.take("from_id")
        if isinstance(fault, BaseException):
            raise fault
        return self._info(self.vendor.get(object_id))

    async def snapshot_filesystem(self, object_id: str):
        fault = self.vendor.take("snapshot_filesystem")
        if isinstance(fault, BaseException):
            raise fault
        return self.vendor.snapshot(object_id, ttl=self.snapshot_ttl)

    async def image_exists(self, image_id: str) -> bool:
        return self.vendor.snapshot_exists(image_id)

    async def terminate(self, object_id: str) -> bool:
        obj = self.vendor.objects.get(object_id)
        if obj is None or obj.state == "terminated":
            self.vendor.calls.append("terminate")
            raise NotFoundError()
        return await self.vendor.kill("terminate", object_id)

    async def open_stdio(self, object_id: str, argv: Sequence[str]):
        assert tuple(argv) == SANDBOXD_CONNECT_ARGV
        fault = self.vendor.take("open_stdio")
        if isinstance(fault, BaseException):
            raise fault
        return await self.vendor.get(object_id).daemon.open_channel()


class ManualClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@dataclass
class ManagedStack:
    provider: ManagedSandboxProvider
    vendor: FakeVendor
    ledger: InMemorySandboxLedger
    kind: str
    clock: ManualClock
    identity: SandboxIdentity

    def restart(self, **overrides) -> ManagedSandboxProvider:
        """A new provider process: same ledger, same vendor, no in-memory state."""
        return build_provider(
            self.kind, self.vendor, self.ledger, clock=self.clock, **overrides
        )


def build_client(kind: str, vendor: FakeVendor, **sdk_options):
    if kind == "e2b":
        return E2BProviderClient(sdk=FakeE2BSdk(vendor), sleep=_no_sleep)
    return ModalProviderClient(sdk=FakeModalSdk(vendor, **sdk_options))


async def _no_sleep(_seconds: float) -> None:
    return None


def build_provider(
    kind: str,
    vendor: FakeVendor,
    ledger: InMemorySandboxLedger,
    *,
    clock: ManualClock,
    profile: SandboxProfile = OFFLINE_V1,
    region: str = "local",
    kill_switch: bool = False,
    expectation: SandboxdExpectation | None = None,
    client=None,
    max_lifetime_sec: float = 3600.0,
) -> ManagedSandboxProvider:
    return ManagedSandboxProvider(
        client=client or build_client(kind, vendor),
        ledger=ledger,
        identity=SandboxIdentity(KEY),
        profile=profile,
        image_digest=IMAGE,
        region=region,
        expectation=expectation or SandboxdExpectation.bundled(),
        max_lifetime_sec=max_lifetime_sec,
        allowed_env_names=ALLOWED_ENV,
        operation_timeout_sec=30.0,
        max_pty_sessions=4,
        kill_switch=lambda: kill_switch,
        clock=clock,
    )


@asynccontextmanager
async def managed_stack(root: Path, kind: str, **options):
    clock = ManualClock()
    vendor = FakeVendor(root=root / "vendor", clock=clock)
    ledger = InMemorySandboxLedger()
    client_factory = options.pop("client_factory", None)
    if client_factory is not None:
        options["client"] = client_factory(vendor)
    provider = build_provider(kind, vendor, ledger, clock=clock, **options)
    stack = ManagedStack(
        provider=provider, vendor=vendor, ledger=ledger, kind=kind, clock=clock,
        identity=SandboxIdentity(KEY),
    )
    try:
        yield stack
    finally:
        await provider.close()
        await vendor.close()


async def create(provider: ManagedSandboxProvider, owner: str = "ct_1"):
    return await provider.create(owner_id=owner, limits=SandboxLimits.safe_defaults())

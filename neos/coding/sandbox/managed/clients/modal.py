"""Modal coding provider client (no SDK import).

Modal 의미 (docs/MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md §2, §3, §6):

* 기본 public outbound가 열려 있다. `block_network=True`를 **항상** 명시하고
  읽어서 확인한다. CIDR/domain allowlist(domain은 Beta)는 주장하지 않는다.
* `exec`은 argv를 직접 받는다. guest daemon relay도 argv로 연다.
* 공개 lifecycle에 suspend/resume이 없다. suspend = filesystem snapshot(Image)
  + terminate, resume = 그 Image에서 새 sandbox 생성. 같은 logical NEOS
  sandbox 아래 provider ref와 **generation이 바뀐다**. process/memory 연속성은
  주장하지 않는다(`suspend_preserves_processes=False`).
* filesystem snapshot은 기본 TTL 뒤 `NotFound`가 될 수 있고 list API가 없다.
  expires_at을 원장에 보관하고 restore 전에 존재를 확인한다.
* 수명 상한은 24시간이다. 넘으면 요청 단계에서 거절한다.
* deployed App 안의 unique running name 충돌(409)은 create idempotency 보조일
  뿐이다 -- tag로 재발견해 판단한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from neos.coding.sandbox.managed.clients.base import (
    SANDBOXD_CONNECT_ARGV,
    DestroyOutcome,
    ProviderClientError,
    ProviderCreateSpec,
    ProviderErrorKind,
    ProviderSandboxInfo,
    ProviderSandboxStatus,
    ProviderSnapshot,
    StdioRelayEvidence,
    SuspendOutcome,
    declared_relay_evidence,
    sanitize,
)
from neos.coding.sandbox.managed.identity import METADATA_IDEMPOTENCY_KEY
from neos.coding.sandbox.managed.profiles import (
    DENY_ALL,
    NetworkPolicy,
    ProviderCapabilities,
)
from neos.coding.sandboxd.client import SandboxdChannel

PROVIDER = "modal"
MAX_LIFETIME_SECONDS = 24 * 3600


@dataclass(frozen=True, slots=True)
class ModalSandboxInfo:
    object_id: str
    name: str
    status: str  # "running" | "terminated"
    tags: Mapping[str, str] = field(default_factory=dict)
    block_network: bool | None = None
    region: str | None = None


class ModalSdk(Protocol):
    """The Modal surface NEOS **requires**. Not the vendor API.

    선택 속성 ``stdio_relay_evidence: StdioRelayEvidence`` (트랙 Q6c MS2) -- 바인딩이
    Q6b §4 증거를 갖췄을 때만 단다. 없으면 이 provider 는 비밀을 싣지 않는다.
    """

    @property
    def reports_network_policy(self) -> bool: ...

    async def create(
        self,
        *,
        image: str,
        name: str,
        tags: Mapping[str, str],
        block_network: bool,
        timeout_seconds: int,
        region: str,
    ) -> ModalSandboxInfo: ...

    async def list(self, *, tags: Mapping[str, str]) -> Sequence[ModalSandboxInfo]: ...

    async def from_id(self, object_id: str) -> ModalSandboxInfo: ...

    async def snapshot_filesystem(self, object_id: str) -> tuple[str, datetime | None]: ...

    async def image_exists(self, image_id: str) -> bool: ...

    async def terminate(self, object_id: str) -> bool: ...

    async def open_stdio(self, object_id: str, argv: Sequence[str]) -> SandboxdChannel: ...


def _info(record: ModalSandboxInfo) -> ProviderSandboxInfo:
    network = None
    if record.block_network is True:
        # Modal sandbox는 tunnel/connect token을 명시 opt-in하지 않으면 inbound를
        # 받지 않는다.
        network = DENY_ALL
    elif record.block_network is False:
        network = NetworkPolicy(outbound="allowlist", inbound="deny", allow=("*",))
    status = (
        ProviderSandboxStatus.RUNNING
        if record.status == "running"
        else ProviderSandboxStatus.TERMINATED
    )
    return ProviderSandboxInfo(
        provider_ref=record.object_id,
        status=status,
        metadata=dict(record.tags),
        network=network,
        region=record.region,
    )


class ModalProviderClient:
    def __init__(self, *, sdk: ModalSdk) -> None:
        self._sdk = sdk

    @property
    def name(self) -> str:
        return PROVIDER

    @property
    def secret_relay_evidence(self) -> StdioRelayEvidence | None:
        """트랙 Q6c MS2: 바인딩이 선언한 stdio 중계 증거. 바인딩이 없는 오늘은 ``None``."""
        return declared_relay_evidence(self._sdk, PROVIDER)

    async def probe(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=PROVIDER,
            outbound_block_all=True,
            outbound_allowlist=False,
            inbound_closed_by_default=True,
            network_policy_readback=bool(self._sdk.reports_network_policy),
            hard_pids_limit=False,
            hard_workspace_quota=False,
            suspend_preserves_processes=False,
            filesystem_snapshot=True,
            sandboxd_stdio_exec=True,
        )

    async def create(self, spec: ProviderCreateSpec) -> ProviderSandboxInfo:
        if spec.network.outbound != "deny":
            raise ProviderClientError(PROVIDER, "create", ProviderErrorKind.INVALID)
        if spec.lifetime_sec > MAX_LIFETIME_SECONDS:
            raise ProviderClientError(PROVIDER, "create", ProviderErrorKind.INVALID)
        record = await sanitize(
            PROVIDER,
            "create",
            self._sdk.create(
                image=spec.source_snapshot_ref or spec.image,
                name=spec.provider_name,
                tags=dict(spec.metadata),
                block_network=True,
                timeout_seconds=spec.lifetime_sec,
                region=spec.region,
            ),
        )
        return _info(record)

    async def find(self, idempotency_key: str) -> tuple[ProviderSandboxInfo, ...]:
        records = await sanitize(
            PROVIDER, "list", self._sdk.list(tags={METADATA_IDEMPOTENCY_KEY: idempotency_key})
        )
        return tuple(
            _info(record)
            for record in records
            if record.status == "running"
            and record.tags.get(METADATA_IDEMPOTENCY_KEY) == idempotency_key
        )

    async def describe(self, provider_ref: str) -> ProviderSandboxInfo:
        return _info(await sanitize(PROVIDER, "from_id", self._sdk.from_id(provider_ref)))

    async def suspend(self, provider_ref: str) -> SuspendOutcome:
        snapshot = await self.snapshot(provider_ref)
        try:
            terminated = await sanitize(PROVIDER, "terminate", self._sdk.terminate(provider_ref))
        except ProviderClientError as error:
            if error.kind is ProviderErrorKind.NOT_FOUND:
                return SuspendOutcome(snapshot=snapshot, terminated=True)
            if not error.ambiguous:
                raise
            # snapshot은 확보했다. 원 object 종료만 불명확하다 -- 호출자가
            # 원장에 남겨 리퍼가 재확인한다.
            return SuspendOutcome(snapshot=snapshot, terminated=True, terminate_confirmed=False)
        return SuspendOutcome(
            snapshot=snapshot, terminated=True, terminate_confirmed=bool(terminated)
        )

    async def resume(
        self, provider_ref: str, *, spec: ProviderCreateSpec
    ) -> ProviderSandboxInfo:
        if spec.source_snapshot_ref is None:
            raise ProviderClientError(PROVIDER, "resume", ProviderErrorKind.INVALID)
        return await self.create(spec)

    async def snapshot(self, provider_ref: str) -> ProviderSnapshot:
        image_id, expires_at = await sanitize(
            PROVIDER, "snapshot_filesystem", self._sdk.snapshot_filesystem(provider_ref)
        )
        return ProviderSnapshot(
            snapshot_ref=image_id, expires_at=expires_at, connections_dropped=False
        )

    async def snapshot_exists(self, snapshot_ref: str) -> bool:
        try:
            return await sanitize(PROVIDER, "image_lookup", self._sdk.image_exists(snapshot_ref))
        except ProviderClientError as error:
            if error.kind is ProviderErrorKind.NOT_FOUND:
                return False
            raise

    async def destroy(self, provider_ref: str) -> DestroyOutcome:
        try:
            terminated = await sanitize(PROVIDER, "terminate", self._sdk.terminate(provider_ref))
        except ProviderClientError as error:
            if error.kind is ProviderErrorKind.NOT_FOUND:
                return DestroyOutcome(confirmed=True, not_found=True)
            raise
        return DestroyOutcome(confirmed=bool(terminated))

    async def open_channel(self, provider_ref: str) -> SandboxdChannel:
        return await sanitize(
            PROVIDER, "exec", self._sdk.open_stdio(provider_ref, SANDBOXD_CONNECT_ARGV)
        )

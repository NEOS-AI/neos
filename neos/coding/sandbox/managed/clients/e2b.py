"""E2B coding provider client (no SDK import).

E2B 의미 (docs/MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md §2, §3, §6):

* create 공개 기본은 internet 허용이다. `allow_internet_access=False`를 **항상**
  명시하고, create 뒤 `get_info`로 읽어 확인한다. per-domain allowlist는
  주장하지 않는다.
* suspend = pause (filesystem + memory 보존), resume = connect. 같은 provider
  ref, 같은 generation이다.
* pause가 503/`ServiceBusy`로 거절되면 sandbox는 계속 RUNNING이다. bounded
  retry 뒤에도 거절되면 그대로 올린다 -- 호출자는 running으로 기록한다.
* snapshot 뒤 원 sandbox는 짧게 멈췄다가 다시 RUNNING이지만 PTY/command/
  WebSocket 연결은 끊긴다(`connections_dropped=True`). 호출자가 channel을 버리고
  journal cursor부터 재접속한다.
* metadata는 ACL이 아니다. 재발견 인덱스일 뿐이다.
* E2B의 문서화된 command 표면은 문자열 중심이다. 그래서 vendor exec을 건너는
  것은 고정 argv `SANDBOXD_CONNECT_ARGV` 하나이고, 모든 요청은 그 프로세스의
  stdin 프레임으로 간다. SDK binding은 이 argv를 안전하게 인용할 책임을 진다.
"""

from __future__ import annotations

import asyncio
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
    Sleep,
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

PROVIDER = "e2b"
PAUSE_BUSY_RETRIES = 3
PAUSE_BUSY_BACKOFF_SEC = 1.0


@dataclass(frozen=True, slots=True)
class E2BSandboxInfo:
    sandbox_id: str
    state: str  # "running" | "paused"
    metadata: Mapping[str, str] = field(default_factory=dict)
    allow_internet_access: bool | None = None
    region: str | None = None


class E2BSdk(Protocol):
    """The E2B surface NEOS **requires**. Not the vendor API.

    선택 속성 ``stdio_relay_evidence: StdioRelayEvidence`` (트랙 Q6c MS2) -- 바인딩이
    Q6b §4 증거를 갖췄을 때만 단다. 없으면 이 provider 는 비밀을 싣지 않는다.
    """

    @property
    def reports_network_policy(self) -> bool: ...

    async def create(
        self,
        *,
        template: str,
        metadata: Mapping[str, str],
        allow_internet_access: bool,
        timeout_seconds: int,
        region: str,
        snapshot_id: str | None,
    ) -> E2BSandboxInfo: ...

    async def list(self, *, metadata: Mapping[str, str]) -> Sequence[E2BSandboxInfo]: ...

    async def get_info(self, sandbox_id: str) -> E2BSandboxInfo: ...

    async def pause(self, sandbox_id: str) -> None: ...

    async def connect(self, sandbox_id: str) -> E2BSandboxInfo: ...

    async def create_snapshot(self, sandbox_id: str) -> tuple[str, datetime | None]: ...

    async def snapshot_exists(self, snapshot_id: str) -> bool: ...

    async def kill(self, sandbox_id: str) -> bool: ...

    async def open_stdio(self, sandbox_id: str, argv: Sequence[str]) -> SandboxdChannel: ...


def _status(state: str) -> ProviderSandboxStatus:
    return {
        "running": ProviderSandboxStatus.RUNNING,
        "paused": ProviderSandboxStatus.PAUSED,
    }.get(state, ProviderSandboxStatus.TERMINATED)


def _info(record: E2BSandboxInfo) -> ProviderSandboxInfo:
    network = None
    if record.allow_internet_access is False:
        # E2B는 공개 inbound URL을 요청하지 않으면 만들지 않는다; outbound 차단만
        # 읽어서 확인할 수 있는 값이다.
        network = DENY_ALL
    elif record.allow_internet_access is True:
        network = NetworkPolicy(outbound="allowlist", inbound="deny", allow=("*",))
    return ProviderSandboxInfo(
        provider_ref=record.sandbox_id,
        status=_status(record.state),
        metadata=dict(record.metadata),
        network=network,
        region=record.region,
    )


class E2BProviderClient:
    def __init__(
        self,
        *,
        sdk: E2BSdk,
        sleep: Sleep = asyncio.sleep,
        pause_busy_retries: int = PAUSE_BUSY_RETRIES,
    ) -> None:
        self._sdk = sdk
        self._sleep = sleep
        self._pause_busy_retries = pause_busy_retries

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
            suspend_preserves_processes=True,
            filesystem_snapshot=True,
            sandboxd_stdio_exec=True,
        )

    async def create(self, spec: ProviderCreateSpec) -> ProviderSandboxInfo:
        if spec.network.outbound != "deny":
            raise ProviderClientError(PROVIDER, "create", ProviderErrorKind.INVALID)
        record = await sanitize(
            PROVIDER,
            "create",
            self._sdk.create(
                template=spec.image,
                metadata=dict(spec.metadata),
                allow_internet_access=False,
                timeout_seconds=spec.lifetime_sec,
                region=spec.region,
                snapshot_id=spec.source_snapshot_ref,
            ),
        )
        return _info(record)

    async def find(self, idempotency_key: str) -> tuple[ProviderSandboxInfo, ...]:
        records = await sanitize(
            PROVIDER,
            "list",
            self._sdk.list(metadata={METADATA_IDEMPOTENCY_KEY: idempotency_key}),
        )
        return tuple(
            _info(record)
            for record in records
            if record.metadata.get(METADATA_IDEMPOTENCY_KEY) == idempotency_key
        )

    async def describe(self, provider_ref: str) -> ProviderSandboxInfo:
        return _info(await sanitize(PROVIDER, "get_info", self._sdk.get_info(provider_ref)))

    async def suspend(self, provider_ref: str) -> SuspendOutcome:
        for attempt in range(self._pause_busy_retries + 1):
            try:
                await sanitize(PROVIDER, "pause", self._sdk.pause(provider_ref))
            except ProviderClientError as error:
                if error.kind is not ProviderErrorKind.BUSY or attempt == self._pause_busy_retries:
                    raise
                await self._sleep(PAUSE_BUSY_BACKOFF_SEC * (attempt + 1))
                continue
            return SuspendOutcome(snapshot=None, terminated=False)
        raise ProviderClientError(PROVIDER, "pause", ProviderErrorKind.BUSY)

    async def resume(
        self, provider_ref: str, *, spec: ProviderCreateSpec
    ) -> ProviderSandboxInfo:
        return _info(await sanitize(PROVIDER, "connect", self._sdk.connect(provider_ref)))

    async def snapshot(self, provider_ref: str) -> ProviderSnapshot:
        snapshot_id, expires_at = await sanitize(
            PROVIDER, "create_snapshot", self._sdk.create_snapshot(provider_ref)
        )
        return ProviderSnapshot(
            snapshot_ref=snapshot_id, expires_at=expires_at, connections_dropped=True
        )

    async def snapshot_exists(self, snapshot_ref: str) -> bool:
        return await sanitize(PROVIDER, "get_snapshot", self._sdk.snapshot_exists(snapshot_ref))

    async def destroy(self, provider_ref: str) -> DestroyOutcome:
        try:
            killed = await sanitize(PROVIDER, "kill", self._sdk.kill(provider_ref))
        except ProviderClientError as error:
            if error.kind is ProviderErrorKind.NOT_FOUND:
                return DestroyOutcome(confirmed=True, not_found=True)
            raise
        # `kill`이 False면 "없었다"는 뜻이다. 그래도 get_info로 부재를 확인하지
        # 않고 성공이라 적지 않는다 -- 확인은 호출자(provider)가 describe로 한다.
        return DestroyOutcome(confirmed=bool(killed), not_found=not killed)

    async def open_channel(self, provider_ref: str) -> SandboxdChannel:
        return await sanitize(
            PROVIDER, "open_stdio", self._sdk.open_stdio(provider_ref, SANDBOXD_CONNECT_ARGV)
        )

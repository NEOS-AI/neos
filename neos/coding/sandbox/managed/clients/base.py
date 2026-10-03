"""Narrow provider-client contract for managed coding sandboxes.

Provider client는 lifecycle과 transport만 안다: create / find / describe /
suspend / resume / snapshot / destroy, 그리고 guest `neos-sandboxd`로 가는
stdio channel 하나. 파일·명령·PTY 의미는 전부 sandboxd가 맡는다
(docs/MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md §8.1).

**vendor SDK를 import하지 않는다.** 각 client는 vendor 모양의 좁은 SDK
protocol(`E2BSdk`, `ModalSdk`)을 주입받는다. SDK binding은 실계정 opt-in smoke와
함께만 들어온다 -- 아무도 실계정에서 실행해 보지 않은 SDK 호출은 구현된 것처럼
보일 뿐이다. 주입이 없으면 factory가 `managed_<provider>_client_not_bound`로
거절한다.

vendor 예외는 이 모듈 밖으로 새지 않는다. `sanitize()`가 종류(kind)만 남긴
`ProviderClientError`로 바꾸고 원 메시지·체인을 버린다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, TypeVar

from neos.coding.sandbox.base import SandboxError, SandboxLimits
from neos.coding.sandbox.managed.profiles import NetworkPolicy, ProviderCapabilities
from neos.coding.sandboxd.client import SandboxdChannel

T = TypeVar("T")

# 이미지에 bake된 guest daemon의 relay 명령. 고정 argv 하나만 vendor exec 표면을
# 건넌다 -- 요청 내용은 전부 이 프로세스의 stdin 프레임으로 간다.
SANDBOXD_CONNECT_ARGV = ("/opt/neos/neos-sandboxd", "connect", "--socket", "/run/neos/sandboxd.sock")


class ProviderErrorKind(StrEnum):
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    AUTH = "auth"
    BUSY = "busy"
    INVALID = "invalid"
    OTHER = "other"


# 결과를 알 수 없는 실패. create 뒤에 이것이 오면 "만들어졌는가"를 모른다 --
# 재발견으로만 해소하고 두 번째 create를 보내지 않는다 (§6).
AMBIGUOUS_KINDS = frozenset(
    {ProviderErrorKind.TIMEOUT, ProviderErrorKind.TRANSPORT, ProviderErrorKind.SERVER_ERROR}
)


class ProviderClientError(SandboxError):
    """Sanitized provider failure: provider, operation, and kind only."""

    def __init__(self, provider: str, operation: str, kind: ProviderErrorKind) -> None:
        super().__init__(f"{provider}_{operation}_{kind.value}")
        self.provider = provider
        self.operation = operation
        self.kind = kind

    @property
    def ambiguous(self) -> bool:
        return self.kind in AMBIGUOUS_KINDS


def classify_vendor_error(error: BaseException) -> ProviderErrorKind:
    if isinstance(error, ProviderClientError):
        return error.kind
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return ProviderErrorKind.TIMEOUT
    status = None
    for attribute in ("status_code", "status", "http_status"):
        value = getattr(error, attribute, None)
        if isinstance(value, int):
            status = value
            break
    name = type(error).__name__.casefold()
    if status == 404 or "notfound" in name:
        return ProviderErrorKind.NOT_FOUND
    if status == 409 or "alreadyexists" in name or "conflict" in name:
        return ProviderErrorKind.CONFLICT
    if status == 429 or "ratelimit" in name:
        return ProviderErrorKind.RATE_LIMITED
    if status in {401, 403} or "auth" in name or "forbidden" in name:
        return ProviderErrorKind.AUTH
    if "servicebusy" in name:
        return ProviderErrorKind.BUSY
    if "timeout" in name:
        return ProviderErrorKind.TIMEOUT
    if isinstance(error, ConnectionError) or "connection" in name:
        return ProviderErrorKind.TRANSPORT
    if status is not None and 500 <= status <= 599:
        return ProviderErrorKind.BUSY if status == 503 else ProviderErrorKind.SERVER_ERROR
    if status is not None and 400 <= status <= 499:
        return ProviderErrorKind.INVALID
    return ProviderErrorKind.OTHER


async def sanitize(provider: str, operation: str, call: Awaitable[T]) -> T:
    try:
        return await call
    except ProviderClientError:
        raise
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - vendor errors are opaque by contract
        kind = classify_vendor_error(error)
        # `from None`: vendor 메시지(요청 id, 토큰 조각, 내부 URL)가 체인으로
        # 로그에 흘러가지 않게 원 예외를 버린다.
        raise ProviderClientError(provider, operation, kind) from None


@dataclass(frozen=True, slots=True)
class StdioRelayEvidence:
    """트랙 Q6c MS2: 벤더 stdio 중계에 비밀을 실어도 된다는 **증거**.

    이 값은 설정이 아니라 **SDK 바인딩 코드**가 싣는다(`sdk.stdio_relay_evidence`).
    Q6b §4 의 네 항목 중 셋을 필드로 받는다 -- 넷째(provider 이름으로 판정)는
    `secret_relay_proven` 과 `sandbox.managed.secret_env_providers` 가 맡는다.
    오늘 저장소에는 바인딩이 없으므로 운영에서 이 값을 내는 코드는 없다.
    """

    vendor: str
    #: 바인딩의 테스트가 `open_stdio` 전송이 TLS 이고 인증서 검증을 끄는 경로가 없음을 고정했다.
    tls_verified: bool
    #: 벤더 문서·계약 중 exec stdin 을 보존·로깅하지 않는다는 근거(https 링크 + 확인 날짜).
    stdin_retention_source: str
    #: 실계정 smoke(docs/Q6C_..._261002.md §5 체크리스트)를 사람이 돌린 기록 id·날짜.
    smoke_record: str

    def proves(self, vendor: str) -> bool:
        return (
            self.vendor == vendor
            and self.tls_verified is True
            and self.stdin_retention_source.startswith("https://")
            and bool(self.smoke_record.strip())
        )


def declared_relay_evidence(sdk: object, vendor: str) -> StdioRelayEvidence | None:
    """SDK 가 선언한 증거. 선언하지 않았거나 모자라면 ``None`` -- fail closed."""
    evidence = getattr(sdk, "stdio_relay_evidence", None)
    if isinstance(evidence, StdioRelayEvidence) and evidence.proves(vendor):
        return evidence
    return None


def secret_relay_proven(client: object) -> bool:
    """이 provider client 의 stdio 중계가 비밀을 실어도 되는가 (Q6c MS2).

    client 가 `secret_relay_evidence` 를 선언하지 않으면 거짓이다 -- 테스트 대역과
    옛 client 는 아무것도 하지 않아도 닫혀 있다.
    """
    name = getattr(client, "name", None)
    evidence = getattr(client, "secret_relay_evidence", None)
    return (
        isinstance(name, str)
        and isinstance(evidence, StdioRelayEvidence)
        and evidence.proves(name)
    )


class ProviderSandboxStatus(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    TERMINATED = "terminated"


@dataclass(frozen=True, slots=True)
class ProviderCreateSpec:
    allocation_id: str
    idempotency_key: str
    provider_name: str
    metadata: Mapping[str, str]
    image: str
    region: str
    network: NetworkPolicy
    limits: SandboxLimits
    lifetime_sec: int
    source_snapshot_ref: str | None = None

    def __post_init__(self) -> None:
        if self.lifetime_sec <= 0:
            raise ValueError("lifetime must be positive")


@dataclass(frozen=True, slots=True)
class ProviderSandboxInfo:
    provider_ref: str
    status: ProviderSandboxStatus
    metadata: Mapping[str, str] = field(default_factory=dict)
    network: NetworkPolicy | None = None
    region: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    snapshot_ref: str
    expires_at: datetime | None
    connections_dropped: bool


@dataclass(frozen=True, slots=True)
class SuspendOutcome:
    """E2B: paused in place. Modal: filesystem snapshot, then terminate."""

    snapshot: ProviderSnapshot | None
    terminated: bool
    terminate_confirmed: bool = True


@dataclass(frozen=True, slots=True)
class DestroyOutcome:
    confirmed: bool
    not_found: bool = False


class SandboxProviderClient(Protocol):
    @property
    def name(self) -> str: ...

    async def probe(self) -> ProviderCapabilities: ...

    async def create(self, spec: ProviderCreateSpec) -> ProviderSandboxInfo: ...

    async def find(self, idempotency_key: str) -> tuple[ProviderSandboxInfo, ...]: ...

    async def describe(self, provider_ref: str) -> ProviderSandboxInfo: ...

    async def suspend(self, provider_ref: str) -> SuspendOutcome: ...

    async def resume(
        self, provider_ref: str, *, spec: ProviderCreateSpec
    ) -> ProviderSandboxInfo:
        """Same ref for a warm resume; a new object from ``spec`` for a cold one."""
        ...

    async def snapshot(self, provider_ref: str) -> ProviderSnapshot: ...

    async def snapshot_exists(self, snapshot_ref: str) -> bool: ...

    async def destroy(self, provider_ref: str) -> DestroyOutcome: ...

    async def open_channel(self, provider_ref: str) -> SandboxdChannel: ...


Sleep = Callable[[float], Awaitable[None]]

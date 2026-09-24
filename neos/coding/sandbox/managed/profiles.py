"""Named sandbox profiles and exact capability negotiation.

코드에 등록된 immutable profile만 받는다. provider client의 capability probe가
profile의 모든 요구를 정확히 만족하고, 적용된 네트워크 정책을 create 뒤에
읽어서 확인할 수 있을 때만 accept한다. 그렇지 않으면 **create 전에**
`profile_unsupported`로 거절한다 -- 넓은 인터넷이나 약한 profile로의 fallback은
없다 (docs/MANAGED_SANDBOX_PROVIDER_REVIEW_260914.md §3, §5, §8.1).

"provider 기본값"은 NEOS 기본값이 아니다. 네트워크 기본은 deny다.

이 capability는 할당 어댑터의 `ManagedSandboxCapabilities` 상수와 **별개로**
협상한다. 그 상수는 allocation benchmark용 보수적 underclaim이라 코딩 계약에
복사하거나 고치지 않는다 (§8).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from neos.coding.sandbox.base import SandboxUnavailable


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    outbound: Literal["deny", "allowlist"]
    inbound: Literal["deny"]
    allow: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.outbound == "deny" and self.allow:
            raise ValueError("deny policy cannot carry an allowlist")
        if self.outbound == "allowlist" and not self.allow:
            raise ValueError("allowlist policy needs at least one destination")

    def as_record(self) -> dict[str, object]:
        return {"outbound": self.outbound, "inbound": self.inbound, "allow": list(self.allow)}

    @classmethod
    def from_record(cls, value: object) -> NetworkPolicy:
        if not isinstance(value, dict):
            raise ValueError("network policy record must be an object")
        return cls(
            outbound=value["outbound"],
            inbound=value["inbound"],
            allow=tuple(value.get("allow") or ()),
        )


DENY_ALL = NetworkPolicy(outbound="deny", inbound="deny")


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """What a coding provider client can *enforce and prove*, per its probe."""

    provider: str
    outbound_block_all: bool
    outbound_allowlist: bool
    inbound_closed_by_default: bool
    network_policy_readback: bool
    hard_pids_limit: bool
    hard_workspace_quota: bool
    suspend_preserves_processes: bool
    filesystem_snapshot: bool
    sandboxd_stdio_exec: bool


@dataclass(frozen=True, slots=True)
class SandboxProfile:
    name: str
    network: NetworkPolicy
    requires_hard_pids: bool = False
    requires_hard_workspace_quota: bool = False
    requires_process_continuity: bool = False

    # credential, host PATH/HOME 을 guest 로 넘기는 profile 은 존재할 수 없다.
    # 필드 자체를 두지 않는다 -- 켤 수 있는 스위치는 언젠가 켜진다.


OFFLINE_V1 = SandboxProfile(name="offline-v1", network=DENY_ALL)
# E2B/Modal 공개 API에서 hard PID / workspace quota 계약이 확인되지 않았다
# (§5). 이 둘은 두 provider에서 fail closed 해야 하는 profile이다.
STRICT_PIDS_V1 = SandboxProfile(
    name="strict-pids-v1", network=DENY_ALL, requires_hard_pids=True
)
STRICT_WORKSPACE_QUOTA_V1 = SandboxProfile(
    name="strict-workspace-quota-v1",
    network=DENY_ALL,
    requires_hard_workspace_quota=True,
)

# 트랙 J 의 조사 워커가 도는 프로파일. 요구는 "네트워크 없음" 하나뿐이다 --
# retrieval 은 `fetch.py` 한 곳만 하고, 샌드박스 안의 바이트는 오케스트레이터가
# 원장에 기록한 blob 뿐이다(계약 I3·I4). 이름을 따로 두는 이유는 프로파일이
# 매니페스트 구성 지문에 들어가서, 조사 실행과 코딩 실행을 원장에서 구별할 수
# 있어야 하기 때문이다. DA 전용 레지스트리를 만들지 않는다(계약 §3.2).
RESEARCH_OFFLINE_V1 = SandboxProfile(name="research-offline-v1", network=DENY_ALL)

PROFILES = MappingProxyType(
    {
        profile.name: profile
        for profile in (
            OFFLINE_V1,
            STRICT_PIDS_V1,
            STRICT_WORKSPACE_QUOTA_V1,
            RESEARCH_OFFLINE_V1,
        )
    }
)


def _unsupported(profile: str, reason: str) -> SandboxUnavailable:
    return SandboxUnavailable(f"profile_unsupported:{profile}:{reason}")


def get_profile(name: str) -> SandboxProfile:
    profile = PROFILES.get(name)
    if profile is None:
        raise _unsupported(name, "unknown_profile")
    return profile


def negotiate_profile(profile: SandboxProfile, capabilities: ProviderCapabilities) -> None:
    """Raise `profile_unsupported` unless every requirement is provable."""
    negotiate_profile_requirements(profile, capabilities)
    if not capabilities.sandboxd_stdio_exec:
        raise _unsupported(profile.name, "sandboxd_channel_unavailable")


def negotiate_profile_requirements(
    profile: SandboxProfile, capabilities: ProviderCapabilities
) -> None:
    """profile 자체의 요구만 따진다 -- 관리형 평면의 sandboxd 채널은 빼고.

    Docker provider 가 이 함수를 부른다. sandboxd 는 관리형 평면의 운반
    채널이지 profile 의 요구가 아니다 -- Docker 는 `docker exec` 로 같은
    자리를 채운다. 사유 문자열을 둘로 나누지 않으려고 한 함수를 공유한다.
    """
    network = profile.network
    if network.outbound == "deny" and not capabilities.outbound_block_all:
        raise _unsupported(profile.name, "outbound_deny_unenforceable")
    if network.outbound == "allowlist" and not capabilities.outbound_allowlist:
        raise _unsupported(profile.name, "outbound_allowlist_unenforceable")
    if network.inbound == "deny" and not capabilities.inbound_closed_by_default:
        raise _unsupported(profile.name, "inbound_deny_unenforceable")
    if not capabilities.network_policy_readback:
        # 적용 여부를 읽어 확인할 수 없으면 "deny 로 만들었다"는 주장일 뿐이다.
        raise _unsupported(profile.name, "network_policy_unverifiable")
    if profile.requires_hard_pids and not capabilities.hard_pids_limit:
        raise _unsupported(profile.name, "hard_pids_limit_unavailable")
    if profile.requires_hard_workspace_quota and not capabilities.hard_workspace_quota:
        raise _unsupported(profile.name, "hard_workspace_quota_unavailable")
    if profile.requires_process_continuity and not capabilities.suspend_preserves_processes:
        raise _unsupported(profile.name, "process_continuity_unavailable")


def verify_applied_network(profile: SandboxProfile, applied: NetworkPolicy | None) -> None:
    """The provider's read-back must equal the profile exactly."""
    if applied is None:
        raise _unsupported(profile.name, "network_policy_unverifiable")
    if applied != profile.network:
        raise _unsupported(profile.name, "network_readback_mismatch")

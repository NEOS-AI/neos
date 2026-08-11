from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
from typing import Any
import uuid

from neos.coding.managed.adapters.base import (
    AllocationResult,
    DestroyResult,
    LifecycleResult,
    ManagedAdapterError,
    ManagedAdapterNotFoundError,
    ManagedAdapterOwnershipError,
    ManagedAdapterTimeoutError,
    ManagedAdapterValidationError,
    ManagedAllocationRequest,
    ProviderHealthProbe,
    ProviderSandboxState,
    SnapshotResult,
    require_capability,
    validate_network_policy,
)
from neos.coding.managed.domain import (
    ManagedSandboxCapabilities,
    ManagedSandboxState,
    ProviderCircuitState,
)
from neos.coding.sandbox.base import SandboxError, SandboxNotFound, SandboxState
from neos.coding.sandbox.command import DockerCommandRunner
from neos.coding.sandbox.docker import DockerSandboxProvider
from neos.config.schema import ManagedSandboxConfig


ALLOCATION_ID_LABEL = "com.neos.coding.managed-allocation-id"
IDEMPOTENCY_KEY_LABEL = "com.neos.coding.managed-idempotency-key"
OWNERSHIP_DIGEST_LABEL = "com.neos.coding.managed-ownership-digest"
SANDBOX_ID_LABEL = "com.neos.coding.sandbox-id"
OWNER_ID_LABEL = "com.neos.coding.owner-id"
CLAIM_TOKEN_LABEL = "com.neos.coding.managed-claim-token"
CLAIMED_AT_LABEL = "com.neos.coding.managed-claimed-at"

_MANAGED_LABELS = (
    ALLOCATION_ID_LABEL,
    IDEMPOTENCY_KEY_LABEL,
    OWNERSHIP_DIGEST_LABEL,
)

# claim_lease_seconds 의 기본값은 ManagedSandboxConfig 가 단일 원천이다 -- 여기서
# 매직넘버로 다시 적지 않는다.
_DEFAULT_CLAIM_LEASE_SECONDS: int = ManagedSandboxConfig.model_fields[
    "claim_lease_seconds"
].default

# 죽은 소유자의 클레임을 회수한 뒤 재획득은 딱 한 번만 허용한다 -- 무한 재시도로
# 인한 라이브락을 막는다 (CA5-b 이월 결함 수정).
_MAX_CLAIM_ACQUIRE_ATTEMPTS = 2

# 이중 생성 수렴(_reconcile_duplicate_creation) 판정을 몇 번까지 다시
# 확인할지. 거의 동시에 경쟁하는 대기자는 각자 자신의 컨테이너를 만든 직후
# 곧바로 확인하므로, 상대가 아직 생성을 끝내지 못한 그 찰나에는 "나 혼자다"
# 로 보일 수 있다(직접 재현해 확인함). 짧게 양보하며 몇 번 더 확인하면 그
# 찰나를 메운다 -- 무한정 기다리지 않도록 횟수를 못박는다.
_RECONCILE_SETTLE_ATTEMPTS = 5


class DockerShadowManagedAdapter:
    __slots__ = (
        "_allocation_lock",
        "_capabilities",
        "_claim_lease_seconds",
        "_provider",
        "_runner",
    )

    def __init__(
        self,
        *,
        provider: DockerSandboxProvider,
        runner: DockerCommandRunner | None = None,
        claim_lease_seconds: int = _DEFAULT_CLAIM_LEASE_SECONDS,
    ) -> None:
        self._provider = provider
        self._allocation_lock = asyncio.Lock()
        # provider 의 러너를 **교체**하지 않고 공개 표면으로 빌려 쓴다.
        self._runner = runner or provider.command_runner
        self._claim_lease_seconds = claim_lease_seconds
        self._capabilities = ManagedSandboxCapabilities(
            pause_resume=True,
            filesystem_snapshot=True,
            memory_snapshot=False,
            portable_archive=True,
            network_block_all=provider.network_mode == "none",
            network_allowlist=False,
            region_pin=False,
            idempotent_allocate=True,
            metadata_rediscovery=True,
        )

    @property
    def provider(self) -> str:
        return "docker"

    @property
    def capabilities(self) -> ManagedSandboxCapabilities:
        return self._capabilities

    async def allocate(
        self,
        request: ManagedAllocationRequest,
    ) -> AllocationResult:
        require_capability(self.capabilities, "idempotent_allocate")
        validate_network_policy(self.capabilities, request.network_policy)
        if request.region != "local":
            raise ManagedAdapterValidationError(
                "docker shadow supports only the local region"
            )
        if request.image_identity != self._provider.image_identity:
            raise ManagedAdapterValidationError("image_identity_mismatch")
        async with self._allocation_lock:
            existing = await self.find_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                return self._replayed_allocation(existing, request)
            labels = {
                ALLOCATION_ID_LABEL: request.allocation_id,
                IDEMPOTENCY_KEY_LABEL: request.idempotency_key,
                OWNERSHIP_DIGEST_LABEL: request.ownership_digest,
            }
            claim_name = self._claim_volume_name(request.idempotency_key)
            claim_token = ""
            won = False
            # 죽은 소유자의 클레임을 회수한 적이 있는지 기록해 둔다 --
            # _reconcile_duplicate_creation 에게 재확인이 필요한지 알려주는
            # 신호다. 클레임이 살아있는(죽지 않은) 채로 경합했을 뿐이면
            # 지는 쪽은 애초에 컨테이너를 만들지 않고 이긴 쪽을 기다리기만
            # 하므로 이중 생성 자체가 없다 -- 재확인이 필요한 유일한 경우는
            # "확인 후 삭제" 창(finding 1) 이 열리는 죽은 클레임 회수뿐이다.
            reclaimed_stale_claim = False
            # 죽은 소유자의 클레임을 회수했다면(_wait_for_claim_owner 가 None 을
            # 돌려줌) 딱 한 번만 재획득을 시도한다 -- 무한 재시도로 인한
            # 라이브락을 막는다.
            for _attempt in range(_MAX_CLAIM_ACQUIRE_ATTEMPTS):
                claim_token = uuid.uuid4().hex
                await self._runner.run(
                    "volume",
                    "create",
                    *self._label_args(
                        {
                            **labels,
                            CLAIM_TOKEN_LABEL: claim_token,
                            CLAIMED_AT_LABEL: datetime.now(UTC).isoformat(),
                        }
                    ),
                    claim_name,
                    timeout_sec=self._provider.create_timeout_sec,
                )
                claim = await self._inspect_volume(claim_name)
                self._verify_resource_metadata(claim, labels, volume=True)
                if claim["Labels"].get(CLAIM_TOKEN_LABEL) == claim_token:
                    won = True
                    break
                replay = await self._wait_for_claim_owner(request)
                if replay is not None:
                    return replay
                # replay 가 None 이면 죽은 소유자의 클레임을 방금 회수했다는
                # 뜻이다 -- 다음 attempt 에서 깨끗하게 재획득을 시도한다.
                reclaimed_stale_claim = True
            if not won:
                raise ManagedAdapterTimeoutError("idempotent_allocation_claim_pending")
            try:
                with self._provider.resource_labels(labels):
                    sandbox = await self._provider.create(
                        owner_id=request.ownership_digest,
                        limits=request.resource_limits,
                    )
                winner = await self._reconcile_duplicate_creation(
                    request,
                    sandbox.sandbox_id,
                    settle=reclaimed_stale_claim,
                )
                if winner is not None:
                    # 클레임의 CAS 해제(_release_claim)로도 이 창은 완전히 못
                    # 닫는다: docker volume rm 에는 compare-and-swap 이 없어서,
                    # inspect 로 죽은 토큰을 확인한 뒤 rm 하기까지 사이에 다른
                    # 대기자가 그 자리를 회수해 이길 수 있다 -- 검사를 더
                    # 촘촘히 해도 같은 결함을 다른 자리로 옮길 뿐이다. 그래서
                    # 클레임은 "대부분의 이중 생성을 피하는 최선형 최적화"로
                    # 남겨두고, 여기서 사후 수렴으로 보완한다. 우리가 졌다:
                    # 방금 우리가 만들어 소유를 증명할 수 있는 자원(우리
                    # 컨테이너)만 정리한다. 승자의 자원은 절대 건드리지
                    # 않는다.
                    await self._provider.destroy(sandbox.sandbox_id)
                    await self._release_claim(claim_name, claim_token)
                    return self._replayed_allocation(winner, request)
                ownership_name = self._ownership_volume_name(sandbox.sandbox_id)
                ownership_labels = {
                    **labels,
                    SANDBOX_ID_LABEL: sandbox.sandbox_id,
                    CLAIM_TOKEN_LABEL: claim_token,
                }
                await self._runner.run(
                    "volume",
                    "create",
                    *self._label_args(ownership_labels),
                    ownership_name,
                    timeout_sec=self._provider.create_timeout_sec,
                )
                ownership = await self._inspect_volume(ownership_name)
                self._verify_resource_metadata(
                    ownership,
                    ownership_labels,
                    volume=True,
                )
            except BaseException:
                # 획득의 원자성만으로는 부족하다 -- 해제를 보장하지 않으면
                # fail-closed 가 fail-forever 가 된다. 소유권 볼륨 발행까지
                # try 를 넓힌다 -- 그 단계가 실패해도 클레임이 새야 한다.
                await self._best_effort_release_claim(claim_name, claim_token)
                raise
            await self._release_claim(claim_name, claim_token)
            return AllocationResult(
                provider_ref=sandbox.sandbox_id,
                ownership_digest=request.ownership_digest,
                state=self._managed_state(sandbox.state),
            )

    async def inspect(self, provider_ref: str) -> ProviderSandboxState:
        document = await self._inspect_document(provider_ref)
        return self._state_from_document(document)

    async def suspend(self, provider_ref: str) -> LifecycleResult:
        require_capability(self.capabilities, "pause_resume")
        await self.inspect(provider_ref)
        await self._ensure_provider_record(provider_ref)
        sandbox = await self._provider.suspend(provider_ref)
        return LifecycleResult(
            provider_ref=provider_ref,
            state=self._managed_state(sandbox.state),
        )

    async def resume(self, provider_ref: str) -> LifecycleResult:
        require_capability(self.capabilities, "pause_resume")
        await self.inspect(provider_ref)
        await self._ensure_provider_record(provider_ref)
        sandbox = await self._provider.resume(provider_ref)
        return LifecycleResult(
            provider_ref=provider_ref,
            state=self._managed_state(sandbox.state),
        )

    async def snapshot(self, provider_ref: str) -> SnapshotResult:
        require_capability(self.capabilities, "filesystem_snapshot")
        state = await self.inspect(provider_ref)
        await self._ensure_provider_record(provider_ref)
        snapshot = await self._provider.snapshot(provider_ref)
        return SnapshotResult(
            provider_ref=provider_ref,
            snapshot_ref=snapshot.snapshot_id,
            state=state.state,
        )

    async def destroy(
        self,
        provider_ref: str,
        *,
        ownership_digest: str,
    ) -> DestroyResult:
        container_name = f"neos-{provider_ref}"
        workspace_name = f"neos-sandbox-{provider_ref}"
        ownership_name = self._ownership_volume_name(provider_ref)
        container = await self._inspect_container_optional(container_name)
        workspace = await self._inspect_volume_optional(workspace_name)
        ownership = await self._inspect_volume_optional(ownership_name)
        resources = (
            (container, False, True),
            (workspace, True, True),
            (ownership, True, True),
        )
        expected = self._expected_destroy_metadata(
            resources,
            provider_ref=provider_ref,
            ownership_digest=ownership_digest,
        )
        claim_name = self._claim_volume_name(expected[IDEMPOTENCY_KEY_LABEL])
        claim = await self._inspect_volume_optional(claim_name)
        if claim is not None:
            self._verify_resource_metadata(claim, expected, volume=True)
        if container is not None:
            await self._ensure_provider_record(provider_ref)
            await self._provider.destroy(provider_ref)
        await self._remove_container_if_present(container_name)
        await self._remove_volume_if_present(workspace_name)
        primary_remaining = (
            await self._inspect_container_optional(container_name),
            await self._inspect_volume_optional(workspace_name),
        )
        if all(resource is None for resource in primary_remaining):
            await self._remove_volume_if_present(ownership_name)
            await self._remove_volume_if_present(claim_name)
        remaining = (
            *primary_remaining,
            await self._inspect_volume_optional(ownership_name),
            await self._inspect_volume_optional(claim_name),
        )
        confirmed = all(resource is None for resource in remaining)
        return DestroyResult(
            confirmed=confirmed,
            ownership_verified=True,
        )

    async def find_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> ProviderSandboxState | None:
        matches = await self._list_by_idempotency_key(idempotency_key)
        if not matches:
            return None
        if len(matches) != 1:
            raise ManagedAdapterOwnershipError("idempotency_metadata_not_unique")
        return matches[0]

    async def _list_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> tuple[ProviderSandboxState, ...]:
        """`idempotency_key` 라벨이 같은 컨테이너를 개수 제한 없이 전부 돌려준다.

        `find_by_idempotency_key`는 정확히 하나가 아니면 예외를 올려 다른
        호출자들에게 유일성을 보장한다 -- 그 보장은 그대로 둔다(약화하지
        않는다). 이 메서드는 경합 수렴(`_reconcile_duplicate_creation`) 전용
        조회 경로다: "여러 개 있을 수 있다"는 전제 자체가 그 로직의 목적이라
        따로 둔다.
        """
        require_capability(self.capabilities, "metadata_rediscovery")
        listed = await self._runner.run(
            "ps",
            "--all",
            "--filter",
            f"label={IDEMPOTENCY_KEY_LABEL}={idempotency_key}",
            "--format",
            "{{.ID}}",
            timeout_sec=self._provider.operation_timeout_sec,
        )
        container_ids = tuple(
            value for value in listed.stdout.decode().splitlines() if value
        )
        if not container_ids:
            return ()
        inspected = await self._runner.run(
            "inspect",
            *container_ids,
            timeout_sec=self._provider.operation_timeout_sec,
        )
        documents = self._decode_inspection(inspected.stdout)
        return tuple(
            self._state_from_document(document)
            for document in documents
            if (document.get("Config", {}).get("Labels") or {}).get(
                IDEMPOTENCY_KEY_LABEL
            )
            == idempotency_key
        )

    async def _reconcile_duplicate_creation(
        self,
        request: ManagedAllocationRequest,
        sandbox_id: str,
        *,
        settle: bool,
    ) -> ProviderSandboxState | None:
        """`provider.create()` 직후, 같은 idempotency_key 로 컨테이너가 두 개
        이상 생겼는지 확인하고 조율 없이 수렴시킨다.

        클레임 볼륨의 CAS 해제(`_release_claim`)는 대부분의 이중 생성을
        피하는 최선형 최적화일 뿐, 보장은 아니다: "확인 후 삭제"인 이상
        inspect 와 rm 사이에 다른 대기자가 끼어들 수 있는 창이 항상 남는다
        (`docker volume rm`에는 compare-and-swap 이 없다 -- 검사를 더
        촘촘히 해도 같은 결함을 다른 자리로 옮길 뿐이다). 그래서 여기서
        사후에 수렴시킨다: 모든 경쟁자가 조율 없이 컨테이너 메타데이터만
        보고 동일한 승자를 계산할 수 있어야 한다 -- `provider_ref`(무작위
        UUID 기반이라 편향이 없다)의 사전식 최솟값을 승자로 정한다.

        우리가 이겼거나 유일하면 `None`을 돌려준다(호출자는 평소처럼 계속
        진행한다). 우리가 졌으면 승자의 상태를 돌려준다 -- 호출자는 **자신의**
        컨테이너만 정리하고 그 상태를 대신 반환해야 한다. 이 메서드는 정리를
        직접 하지 않는다: 아직 증명하지 못한 자원(=승자의 컨테이너)은 절대
        건드리지 않는다는 원칙을 호출자가 지키게 하기 위해서다.

        거의 동시에 경쟁하는 대기자는 각자 자신의 컨테이너를 만든 직후 곧바로
        이 메서드를 부르므로, 상대가 아직 컨테이너를 다 만들지 못한 찰나에는
        아무도 안 보여 "나 혼자다"로 판정될 수 있다 -- 둘 다 그렇게 판정하면
        둘 다 살아남아 이 메서드가 막으려는 사고가 그대로 재현된다(직접
        재현해 확인함). `settle`이 참이면 한 번만 보고 끝내지 않고
        `_RECONCILE_SETTLE_ATTEMPTS` 번까지 짧게 양보하며(`asyncio.sleep`)
        다시 확인한다 -- 도중에 중복이 보이면 그 순간의 결과로 승자를
        계산한다.

        `settle`은 호출자가 이번 allocate() 안에서 죽은 클레임을 실제로
        회수했는지(finding 1 의 "확인 후 삭제" 창이 열렸는지)를 나타낸다.
        클레임이 살아있는 채로 경합했을 뿐이면(가장 흔한 경우) 지는 쪽은
        애초에 컨테이너를 만들지 않고 이긴 쪽을 기다리기만 하므로 이중 생성
        자체가 없다 -- 그런 보통 경로에까지 재확인 지연을 물리면 매
        allocate() 호출마다 불필요한 지연만 쌓인다.
        """
        attempts = _RECONCILE_SETTLE_ATTEMPTS if settle else 1
        matches: tuple[ProviderSandboxState, ...] = ()
        for attempt in range(attempts):
            matches = await self._list_by_idempotency_key(request.idempotency_key)
            if len(matches) > 1:
                break
            if attempt + 1 < attempts:
                await asyncio.sleep(0.01)
        if len(matches) <= 1:
            return None
        winner = min(matches, key=lambda match: match.provider_ref)
        if winner.provider_ref == sandbox_id:
            return None
        return winner

    async def health(self, region: str) -> ProviderHealthProbe:
        await self._runner.run(
            "info",
            "--format",
            "{{json .ServerVersion}}",
            timeout_sec=self._provider.operation_timeout_sec,
        )
        return ProviderHealthProbe(
            provider=self.provider,
            region=region,
            state=ProviderCircuitState.HEALTHY,
        )

    async def _inspect_document(self, provider_ref: str) -> dict[str, Any]:
        document = await self._inspect_container_optional(f"neos-{provider_ref}")
        if document is None:
            raise ManagedAdapterNotFoundError(provider_ref)
        labels = document.get("Config", {}).get("Labels") or {}
        if labels.get(SANDBOX_ID_LABEL) != provider_ref:
            raise ManagedAdapterOwnershipError("sandbox_id_label_mismatch")
        return document

    async def _wait_for_claim_owner(
        self,
        request: ManagedAllocationRequest,
    ) -> AllocationResult | None:
        """클레임 소유자가 컨테이너를 완성하기를 기다린다.

        소유자가 나타나면 그 결과를 재생(replay)해서 돌려준다. 컨테이너가 끝내
        나타나지 않고 클레임의 claimed_at 이 claim_lease_seconds 보다 오래됐다고
        판정되면(죽은 소유자) 클레임 볼륨을 회수하고 `None` 을 돌려준다 -- 호출자는
        이 신호를 받아 딱 한 번만 재획득을 시도해야 한다.

        획득의 원자성만으로는 부족하다: 소유자가 죽어도 해제를 보장해야
        fail-closed 가 fail-forever 로 굳지 않는다.
        """
        claim_name = self._claim_volume_name(request.idempotency_key)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._provider.create_timeout_sec
        while loop.time() < deadline:
            existing = await self.find_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                replay = self._replayed_allocation(existing, request)
                ownership = await self._inspect_volume_optional(
                    self._ownership_volume_name(existing.provider_ref)
                )
                if ownership is None:
                    await asyncio.sleep(0.01)
                    continue
                self._verify_resource_metadata(
                    ownership,
                    {
                        ALLOCATION_ID_LABEL: request.allocation_id,
                        IDEMPOTENCY_KEY_LABEL: request.idempotency_key,
                        OWNERSHIP_DIGEST_LABEL: request.ownership_digest,
                        SANDBOX_ID_LABEL: existing.provider_ref,
                    },
                    volume=True,
                )
                return replay
            stale_token = await self._stale_claim_token(claim_name)
            if stale_token is not None:
                # 죽은 소유자의 토큰으로만 CAS 삭제한다 (finding 1): 우리가
                # 판정한 뒤 삭제하기까지 사이에 다른 대기자(B)도 같은 클레임을
                # 죽었다고 판정할 수 있다. 그 사이 A 가 먼저 회수해 새 토큰으로
                # 이겼다면, B 의 삭제는 관찰했던 죽은 토큰과 지금 토큰이 달라
                # 거부된다 -- A 의 살아있는 클레임을 B 가 훔쳐 지우는 사고를
                # 막는다.
                await self._release_claim(claim_name, stale_token)
                return None
            await asyncio.sleep(0.01)
        raise ManagedAdapterTimeoutError("idempotent_allocation_claim_pending")

    async def _stale_claim_token(self, claim_name: str) -> str | None:
        """소유자가 죽어 남은 클레임이면 그 클레임이 물고 있던 토큰을 돌려준다.

        컨테이너가 없는 상태에서 클레임의 claimed_at 이 claim_lease_seconds 보다
        오래됐으면 죽은 소유자의 클레임으로 간주하고, 그 클레임이 들고 있던
        `CLAIM_TOKEN_LABEL` 값을 돌려준다 -- 호출자는 이 값을 `_release_claim`
        에 넘겨, 지금 이 순간에도 여전히 그 죽은 토큰을 들고 있을 때만 지우게
        한다. 이 판정과 실제 삭제 사이에도 시간이 지난다 -- 그 사이 누군가
        이미 회수해 새 토큰으로 이겼다면 `_release_claim`의 확인에서 토큰이
        달라 삭제가 거부된다(`_release_claim` 문서 참고: 원자적 CAS 는 아니다).

        판단 근거가 없으면(라벨이 없거나, 문자열이 아니거나, 파싱할 수 없거나,
        오프셋 없는 naive 타임스탬프거나, 아직 lease 안이거나, 토큰 라벨 자체가
        없으면) `None` 을 돌려준다 -- 회수하지 않는다. naive 타임스탬프를 UTC 로
        임의 가정하지 않는 것도 이 안전한 쪽 fail 의 일부다: UTC 동쪽 지역에서
        쓰인 naive 값을 UTC 로 잘못 해석하면 실제보다 더 오래된 것으로 보여,
        claim_lease_seconds(최대 3600 초) 안에서도 아직 살아있는 소유자의
        클레임을 회수해버릴 수 있다.
        """
        claim = await self._inspect_volume_optional(claim_name)
        if claim is None:
            return None
        labels = claim.get("Labels") or {}
        claimed_at_text = labels.get(CLAIMED_AT_LABEL)
        if not claimed_at_text:
            return None
        try:
            claimed_at = datetime.fromisoformat(claimed_at_text)
            if claimed_at.tzinfo is None:
                # 오프셋이 없다 -- 우리가 쓰는 값은 항상 UTC 오프셋을 붙여
                # 쓰므로, 어떤 시간대의 naive 값인지 알 길이 없다. 임의로 UTC
                # 로 가정하면 살아있는 소유자를 회수할 위험이 있으므로 판단
                # 근거 없음으로 처리한다.
                return None
            age_seconds = (datetime.now(UTC) - claimed_at).total_seconds()
        except (TypeError, ValueError):
            # 라벨 값이 문자열이 아니거나(docker inspect JSON 은 shape 만
            # 검증된다) ISO 형식이 아니다 -- 판단 근거가 없으므로 회수하지
            # 않는다.
            return None
        if age_seconds <= self._claim_lease_seconds:
            return None
        observed_token = labels.get(CLAIM_TOKEN_LABEL)
        return observed_token or None

    async def _release_claim(self, claim_name: str, claim_token: str) -> None:
        """`claim_token`을 들고 있을 때만 클레임을 반납한다 (확인 후 삭제).

        `docker volume rm`에는 compare-and-swap 이 없다 -- 이건 원자적 CAS 가
        아니라 "확인한 뒤 지우는" 순차 동작이다: inspect 로 토큰이 여전히
        `claim_token` 인지 확인하고, 맞으면 지운다. 이 두 단계 사이에도 다른
        프로세스가 끼어들 수 있는 아주 좁은 창이 남는다 -- 완전한 상호배제는
        아니다. 그래도 이름만 보고 무조건 지우는 것보다는 훨씬 안전하다:
        Step 8 이후 클레임은 재할당 가능해져서, 무조건 지우면 이미 다른
        프로세스가 죽은 것으로 오판해 회수하고 새로 이긴 클레임을 실수로
        지워버릴 수 있다(그 프로세스의 락을 훔치는 셈). 그러면 같은
        idempotency_key 로 컨테이너가 두 개 생긴다. 토큰이 검사 시점에
        `claim_token`과 다르면 아무것도 하지 않는다.
        """
        claim = await self._inspect_volume_optional(claim_name)
        if claim is None:
            return
        if (claim.get("Labels") or {}).get(CLAIM_TOKEN_LABEL) != claim_token:
            return
        await self._remove_volume_if_present(claim_name)

    async def _best_effort_release_claim(
        self,
        claim_name: str,
        claim_token: str,
    ) -> None:
        """취소된 컨텍스트에서도 클레임 반납을 최선을 다해 시도한다.

        `except BaseException:` 블록에서만 호출된다 -- 이미 취소됐을 수 있는
        컨텍스트다. `asyncio.shield` 로 두 번째 취소가 반납 시도 자체를
        끊지 못하게 막고, `wait_for` 로 전체 시도 시간을 묶어 죽은 docker
        데몬이 취소 처리 자체를 hang 시키지 않게 한다. 실패해도 원래
        예외를 삼키지 않는다 -- 호출자가 곧바로 `raise` 한다.

        `ManagedAdapterError`도 잡는다: `_release_claim` -> `_inspect_volume_optional`
        은 docker inspect 출력이 깨지면 `ManagedAdapterOwnershipError`(그 기반
        클래스가 `ManagedAdapterError`)를 올린다 -- `SandboxError`의 자손이
        아니므로 따로 잡지 않으면 여기를 빠져나가 호출자의 `raise`(원래
        예외 -- 취소였을 수도 있다)를 대체해버린다.
        """
        try:
            await asyncio.wait_for(
                asyncio.shield(self._release_claim(claim_name, claim_token)),
                timeout=self._provider.operation_timeout_sec,
            )
        except (
            TimeoutError,
            asyncio.TimeoutError,
            asyncio.CancelledError,
            SandboxError,
            ManagedAdapterError,
        ):
            pass

    @staticmethod
    def _replayed_allocation(
        existing: ProviderSandboxState,
        request: ManagedAllocationRequest,
    ) -> AllocationResult:
        if (
            existing.allocation_id != request.allocation_id
            or existing.ownership_digest != request.ownership_digest
        ):
            raise ManagedAdapterOwnershipError("idempotency_metadata_mismatch")
        return AllocationResult(
            provider_ref=existing.provider_ref,
            ownership_digest=existing.ownership_digest,
            state=existing.state,
        )

    async def _inspect_container_optional(
        self,
        name: str,
    ) -> dict[str, Any] | None:
        inspected = await self._runner.run(
            "inspect",
            name,
            timeout_sec=self._provider.operation_timeout_sec,
            allowed_exit_codes=(0, 1),
        )
        if inspected.exit_code == 1:
            return None
        documents = self._decode_inspection(inspected.stdout)
        if len(documents) != 1:
            raise ManagedAdapterOwnershipError("docker_inspect_output_invalid")
        return documents[0]

    async def _inspect_volume(self, name: str) -> dict[str, Any]:
        document = await self._inspect_volume_optional(name)
        if document is None:
            raise ManagedAdapterOwnershipError("managed_resource_missing")
        return document

    async def _inspect_volume_optional(
        self,
        name: str,
    ) -> dict[str, Any] | None:
        inspected = await self._runner.run(
            "volume",
            "inspect",
            name,
            timeout_sec=self._provider.operation_timeout_sec,
            allowed_exit_codes=(0, 1),
        )
        if inspected.exit_code == 1:
            return None
        documents = self._decode_inspection(inspected.stdout)
        if len(documents) != 1:
            raise ManagedAdapterOwnershipError("docker_inspect_output_invalid")
        return documents[0]

    async def _remove_container_if_present(self, name: str) -> None:
        if await self._inspect_container_optional(name) is None:
            return
        try:
            await self._runner.run(
                "rm",
                "--force",
                name,
                timeout_sec=self._provider.operation_timeout_sec,
            )
        except SandboxError:
            return

    async def _remove_volume_if_present(self, name: str) -> None:
        if await self._inspect_volume_optional(name) is None:
            return
        try:
            await self._runner.run(
                "volume",
                "rm",
                name,
                timeout_sec=self._provider.operation_timeout_sec,
            )
        except SandboxError:
            return

    @staticmethod
    def _verify_resource_metadata(
        document: dict[str, Any],
        expected: Mapping[str, str],
        *,
        volume: bool,
    ) -> None:
        labels = (
            document.get("Labels")
            if volume
            else document.get("Config", {}).get("Labels")
        ) or {}
        if any(labels.get(key) != value for key, value in expected.items()):
            raise ManagedAdapterOwnershipError("managed_resource_metadata_mismatch")

    @classmethod
    def _expected_destroy_metadata(
        cls,
        resources: tuple[
            tuple[dict[str, Any] | None, bool, bool],
            ...,
        ],
        *,
        provider_ref: str,
        ownership_digest: str,
    ) -> dict[str, str]:
        expected: dict[str, str] | None = None
        for document, volume, binds_provider_ref in resources:
            if document is None:
                continue
            labels = cls._resource_labels(document, volume=volume)
            if expected is None:
                if labels.get(OWNERSHIP_DIGEST_LABEL) != ownership_digest:
                    raise ManagedAdapterOwnershipError("ownership_digest_mismatch")
                try:
                    expected = {
                        ALLOCATION_ID_LABEL: labels[ALLOCATION_ID_LABEL],
                        IDEMPOTENCY_KEY_LABEL: labels[IDEMPOTENCY_KEY_LABEL],
                        OWNERSHIP_DIGEST_LABEL: ownership_digest,
                    }
                except KeyError as error:
                    raise ManagedAdapterOwnershipError(
                        "managed_resource_metadata_missing"
                    ) from error
            cls._verify_resource_metadata(
                document,
                expected,
                volume=volume,
            )
            if binds_provider_ref and labels.get(SANDBOX_ID_LABEL) != provider_ref:
                raise ManagedAdapterOwnershipError("managed_resource_metadata_mismatch")
            if not volume and labels.get(OWNER_ID_LABEL) != ownership_digest:
                raise ManagedAdapterOwnershipError("managed_resource_metadata_mismatch")
        if expected is None:
            raise ManagedAdapterOwnershipError("managed_resource_missing")
        return expected

    @staticmethod
    def _resource_labels(
        document: dict[str, Any],
        *,
        volume: bool,
    ) -> Mapping[str, str]:
        return (
            document.get("Labels")
            if volume
            else document.get("Config", {}).get("Labels")
        ) or {}

    @staticmethod
    def _claim_volume_name(idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:32]
        return f"neos-managed-claim-{digest}"

    @staticmethod
    def _ownership_volume_name(provider_ref: str) -> str:
        return f"neos-managed-owner-{provider_ref}"

    @staticmethod
    def _label_args(labels: Mapping[str, str]) -> tuple[str, ...]:
        return tuple(
            value
            for key, label_value in labels.items()
            for value in ("--label", f"{key}={label_value}")
        )

    def _state_from_document(
        self,
        document: dict[str, Any],
    ) -> ProviderSandboxState:
        labels = document.get("Config", {}).get("Labels") or {}
        if any(not labels.get(name) for name in _MANAGED_LABELS):
            raise ManagedAdapterOwnershipError("managed_metadata_missing")
        provider_ref = labels.get(SANDBOX_ID_LABEL)
        if not provider_ref:
            raise ManagedAdapterOwnershipError("sandbox_id_label_missing")
        if labels.get(OWNER_ID_LABEL) != labels[OWNERSHIP_DIGEST_LABEL]:
            raise ManagedAdapterOwnershipError("ownership_label_mismatch")
        running = bool(document.get("State", {}).get("Running"))
        return ProviderSandboxState(
            provider_ref=provider_ref,
            allocation_id=labels[ALLOCATION_ID_LABEL],
            idempotency_key=labels[IDEMPOTENCY_KEY_LABEL],
            state=(
                ManagedSandboxState.ACTIVE if running else ManagedSandboxState.SUSPENDED
            ),
            ownership_digest=labels[OWNERSHIP_DIGEST_LABEL],
            ownership_verified=True,
        )

    async def _ensure_provider_record(self, provider_ref: str) -> None:
        try:
            await self._provider.get(provider_ref)
        except SandboxNotFound:
            await self._provider.reconcile()
            try:
                await self._provider.get(provider_ref)
            except SandboxNotFound as error:
                raise ManagedAdapterNotFoundError(provider_ref) from error

    @staticmethod
    def _decode_inspection(payload: bytes) -> list[dict[str, Any]]:
        try:
            documents = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ManagedAdapterOwnershipError(
                "docker_inspect_output_invalid"
            ) from error
        if not isinstance(documents, list) or not all(
            isinstance(document, dict) for document in documents
        ):
            raise ManagedAdapterOwnershipError("docker_inspect_output_invalid")
        return documents

    @staticmethod
    def _managed_state(state: SandboxState) -> ManagedSandboxState:
        if state is SandboxState.RUNNING:
            return ManagedSandboxState.ACTIVE
        if state is SandboxState.SUSPENDED:
            return ManagedSandboxState.SUSPENDED
        raise ManagedAdapterValidationError(
            f"unsupported docker sandbox state: {state.value}"
        )

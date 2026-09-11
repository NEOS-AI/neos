import asyncio
import threading
from pathlib import Path
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from neos.utils.anthropic_client import build_async_anthropic

from neos.coding.application.run_service import (
    CodingRunService,
    InProcessRunInterrupter,
)
from neos.coding.application.approval_service import CodingApprovalService
from neos.coding.application.snapshot_service import CodingSnapshotService
from neos.coding.application.workspace_service import CodingWorkspaceService
from neos.coding.application.workspace_stream_service import (
    CodingWorkspaceStreamService,
)
from neos.coding.loop.base import CodingLoop
from neos.coding.loop.fake import FakeDurableCodingLoop
from neos.coding.loop.anthropic import AnthropicCodingLoop, AnthropicLoopConfig
from neos.coding.prompts import CodingPromptEnv, build_coding_system_prompt
from neos.coding.model.anthropic import AnthropicCodingModel
from neos.dataset.adapters import TrackedCodingModel
from neos.coding.managed.adapters import (
    DockerShadowManagedAdapter,
    ManagedNetworkPolicy,
)
from neos.coding.managed.admin import (
    ManagedSandboxAdminService,
    ManagedSandboxStatusService,
)
from neos.coding.managed.archive import (
    LocalPortableArchiveStore,
    ManagedSandboxArchiveService,
    SessionPortableArchiveBuilder,
    SessionPortableArchiveImporter,
)
from neos.coding.managed.health_store import create_provider_health_store
from neos.coding.managed.allocation import ManagedSandboxAllocationService
from neos.coding.managed.crypto import (
    AesGcmProviderReferenceCipher,
    decode_provider_reference_key,
)
from neos.coding.managed.repository import (
    MANAGED_POLICY_VERSION,
    PostgresManagedSandboxRepository,
)
from neos.coding.repositories.sandbox_repository import PostgresSandboxBindingRepository
from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.bindings import SandboxBindingService
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import CodingToolRegistry
from neos.coding.outbox.dispatcher import CodingOutboxDispatcher
from neos.coding.outbox.repository import PostgresCodingOutboxRepository
from neos.coding.persistence.postgres import PostgresCodingService
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
from neos.coding.repositories.workspace_edit_repository import (
    PostgresWorkspaceEditRepository,
)
from neos.coding.repositories.projection_repository import (
    PostgresCodingProjectionRepository,
)
from neos.coding.repositories.task_repository import CodingTaskRepository
from neos.coding.transport.base import CodingEventTransport, CodingTicketStore
from neos.coding.transport.memory import (
    InMemoryWsTicketStore,
    InProcessCodingEventBroker,
)
from neos.coding.transport.redis_events import RedisCodingEventTransport
from neos.coding.transport.redis_tickets import RedisCodingTicketStore
from neos.coding.transport.workspace_tickets import (
    InMemoryWorkspaceTicketStore,
    RedisWorkspaceTicketStore,
    WorkspaceTicketStore,
)
from neos.coding.workers.development_supervisor import (
    CodingDevelopmentSupervisor,
)
from neos.coding.workers.dispatcher import (
    CeleryCodingTaskDispatcher,
    CodingDispatchSource,
)
from neos.coding.workers.celery_runtime import (
    validate_coding_worker_settings,
)
from neos.coding.sandbox.factory import create_sandbox_provider
from neos.coding.sandbox.observability import LoggingCodingAuditSink
from neos.database.connection import db_manager
from neos.config.model_routing import resolve_model
from neos.config.settings import settings
from neos.config.schema import AppConfig
from neos.observability.metrics import metrics


@dataclass(frozen=True, slots=True)
class CodingRuntimeTransport:
    tickets: CodingTicketStore
    events: CodingEventTransport
    workspace_tickets: WorkspaceTicketStore


@dataclass(slots=True)
class CodingRuntime:
    events: Any
    runs: CodingRunService
    snapshots: CodingSnapshotService
    approvals: CodingApprovalService
    workspace: CodingWorkspaceService
    workspace_streams: CodingWorkspaceStreamService
    sandboxes: Any
    supervisor: CodingDevelopmentSupervisor | None = None
    _closed: bool = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.supervisor is not None:
            await self.supervisor.stop()
        await self.workspace_streams.close()
        await self.sandboxes.close()


coding_transport = CodingRuntimeTransport(
    tickets=InMemoryWsTicketStore(),
    events=InProcessCodingEventBroker(),
    workspace_tickets=InMemoryWorkspaceTicketStore(),
)
coding_outbox_repository = PostgresCodingOutboxRepository(db_manager.get_session)
coding_outbox_dispatcher = CodingOutboxDispatcher(
    coding_outbox_repository, coding_transport.events
)
coding_service = PostgresCodingService(
    db_manager.get_session, wake_outbox=coding_outbox_dispatcher.wake
)


def create_coding_runtime(
    *,
    events,
    tasks,
    run_repository,
    projection_repository,
    loop: CodingLoop | None,
    metrics_collector=None,
    interrupter=None,
    clock=None,
    sandboxes=None,
    approval_wake=None,
    config: AppConfig | None = None,
) -> CodingRuntime:
    config = config or settings.config
    snapshots = CodingSnapshotService(projection_repository)
    run_kwargs = {}
    if clock is not None:
        run_kwargs["clock"] = clock
    runs = CodingRunService(
        tasks=tasks,
        runs=run_repository,
        events=events,
        loop=loop,
        metrics=metrics_collector,
        interrupter=interrupter or InProcessRunInterrupter(),
        workspace_edit_batch_size=config.sandbox.workspace.edit_batch_size,
        **run_kwargs,
    )
    sandbox_provider = sandboxes or create_sandbox_provider(settings.config.sandbox)
    sandbox_config = config.sandbox
    resources = sandbox_config.resources
    execution = sandbox_config.execution
    binding_service = SandboxBindingService(
        repository=PostgresSandboxBindingRepository(db_manager.get_session),
        provider=sandbox_provider,
        limits=SandboxLimits(
            cpu_count=resources.cpu_count,
            memory_bytes=resources.memory_bytes,
            pids=resources.pids,
            workspace_bytes=resources.workspace_bytes,
            command_timeout_sec=execution.command_timeout_sec,
            max_output_bytes=execution.max_output_bytes,
            max_stdin_bytes=execution.max_stdin_bytes,
        ),
        snapshot_cadence=config.coding_model.mutation_snapshot_interval,
    )
    workspace_config = sandbox_config.workspace
    if approval_wake is None:
        async def approval_wake(_task_id: str, _checkpoint_id: str) -> None:
            return None
    return CodingRuntime(
        events=events,
        runs=runs,
        snapshots=snapshots,
        approvals=CodingApprovalService(
            run_repository,
            wake=approval_wake,
            metrics=metrics_collector,
            audit=LoggingCodingAuditSink(),
        ),
        workspace=CodingWorkspaceService(
            tasks=tasks,
            runs=run_repository,
            bindings=binding_service,
            edits=PostgresWorkspaceEditRepository(
                db_manager.get_session,
                wake_outbox=coding_outbox_dispatcher.wake,
            ),
            max_file_bytes=workspace_config.file_max_bytes,
            max_tree_entries=workspace_config.tree_max_entries,
            max_diff_bytes=workspace_config.diff_max_bytes,
        ),
        workspace_streams=CodingWorkspaceStreamService(
            tasks=tasks,
            bindings=binding_service,
            pty_max_sessions=workspace_config.pty_max_sessions,
            pty_idle_ttl_seconds=workspace_config.pty_idle_ttl_seconds,
        ),
        sandboxes=sandbox_provider,
    )


def _managed_adapter_registry(
    *, config: AppConfig, sandboxes
) -> dict[str, DockerShadowManagedAdapter]:
    """관리형이 꺼져 있으면 아무것도 만들지 않는다 -- 기존 동작 불변.

    claim_lease_seconds 를 여기서 넘긴다 -- `DockerShadowManagedAdapter`가
    받는 kwarg지만 지금까지 아무도 호출하지 않아 config 값이 죽어 있었다.
    """
    managed = config.sandbox.managed
    if not managed.enabled:
        return {}
    return {
        "docker": DockerShadowManagedAdapter(
            provider=sandboxes,
            claim_lease_seconds=managed.claim_lease_seconds,
        )
    }


def _managed_sandbox_resource_limits(config: AppConfig) -> SandboxLimits:
    """관리형 할당의 provider 컨테이너 자체가 지킬 배치 정책 한도.

    `_prepare_real_coding_loop`가 도구 실행용 `limits`를 채우는 것과 같은
    방식으로 `config.sandbox.resources`에서 채운다. 다만 도구 호출 타임아웃
    (`coding.tool_timeout_sec`)으로 깎지는 않는다 -- 그건 도구 클레임의
    한도이지 provider 컨테이너의 자원 상한이 아니다.
    """
    resources = config.sandbox.resources
    execution = config.sandbox.execution
    return SandboxLimits(
        cpu_count=resources.cpu_count,
        memory_bytes=resources.memory_bytes,
        pids=resources.pids,
        workspace_bytes=resources.workspace_bytes,
        command_timeout_sec=execution.command_timeout_sec,
        max_output_bytes=execution.max_output_bytes,
        max_stdin_bytes=execution.max_stdin_bytes,
    )


def _managed_provider_reference_cipher(
    *, config: AppConfig, allocation_id: str, provider: str, generation: int
) -> AesGcmProviderReferenceCipher:
    """AAD 에 allocation_id:provider:generation 을 묶어 다른 할당의 봉인을
    가져다 쓰는 것을 막는다.

    `ManagedSandboxCipher` 프로토콜(`neos.coding.managed.allocation`)은
    `encrypt(value)`/`decrypt(value)`만 받고 호출마다 문맥을 넘기지 않는다 --
    그래서 이 cipher는 서비스 생성자에 한 번 박아 넣고 재사용할 수 없고,
    advance() 대상 할당을 이미 아는 호출자가 매 할당마다 새로 만들어야 한다.
    """
    managed = config.sandbox.managed
    secret = config.secrets.managed_provider_reference_key
    if not secret:
        # AppConfig.validate_managed_provider_reference_key 가 managed.enabled=true
        # 인 구성에서는 이미 막았어야 한다 -- 여기 도달하면 그 가드를 우회해
        # 호출된 것이므로 조용히 진행하지 않는다.
        raise RuntimeError("managed_provider_reference_key_missing")
    key = decode_provider_reference_key(secret)
    return AesGcmProviderReferenceCipher(
        key=key,
        key_version=managed.provider_reference_key_version,
        associated_data=f"{allocation_id}:{provider}:{generation}",
    )


def _managed_sandbox_repository(
    session_factory=None,
) -> PostgresManagedSandboxRepository:
    """`PostgresSandboxBindingRepository`가 이미 쓰는 것과 같은
    session_factory 대체 규칙을 따른다."""
    return PostgresManagedSandboxRepository(session_factory or db_manager.get_session)


def _managed_archive_store(config: AppConfig) -> LocalPortableArchiveStore:
    """로컬 파일시스템 스토어.

    객체 스토어로 갈아 끼우려면 `PortableArchiveStore` 프로토콜만 만족하면
    된다 -- 서비스도 빌더도 구현체를 모른다.
    """
    return LocalPortableArchiveStore(Path(config.sandbox.managed.archive_root))


def create_managed_archive_service(
    *, config: AppConfig, repository, session_factory=None
) -> ManagedSandboxArchiveService:
    """아카이브 검증과 복구 승인 서비스."""
    del session_factory
    managed = config.sandbox.managed
    return ManagedSandboxArchiveService(
        repository=repository,
        store=_managed_archive_store(config),
        image_identity=config.sandbox.docker.image,
        toolchain_identity=managed.toolchain_identity,
        max_archive_bytes=managed.archive_max_bytes,
        max_archive_entries=managed.archive_max_entries,
        policy_version=MANAGED_POLICY_VERSION,
        lifetime_seconds=int(config.sandbox.lifecycle.max_lifetime_sec),
        reservation_lease_seconds=managed.reservation_lease_seconds,
    )


def create_managed_archive_importer(
    *, config: AppConfig, sandboxes
) -> SessionPortableArchiveImporter:
    """복구 세대의 워크스페이스를 되살리는 포트의 프로덕션 구현.

    provider 참조로 세션을 연다 -- 세션 계약만 쓰므로 provider 가 무엇이든
    같은 코드가 돈다.
    """
    managed = config.sandbox.managed
    return SessionPortableArchiveImporter(
        store=_managed_archive_store(config),
        open_session=sandboxes.open_session,
        max_archive_bytes=managed.archive_max_bytes,
        max_archive_entries=managed.archive_max_entries,
    )


def create_managed_archive_taker(*, config: AppConfig, repository, sandboxes):
    """`allocation_id -> PortableArchiveManifest` 콜러블을 조립한다.

    provider 참조는 봉인돼 있으므로 **할당별 cipher** 로 열어야 한다
    (`_managed_provider_reference_cipher` 문서 참조). 그 조립이 여기 있는
    이유이고, 관리자 서비스가 콜러블만 받는 이유다.
    """

    async def take(allocation_id: str):
        allocation = await repository.read_allocation(allocation_id)
        if allocation.provider_ref is None:
            # 아직 provider 리소스가 없다. 뜰 워크스페이스 자체가 없으므로
            # 조용히 빈 아카이브를 만들지 않는다.
            raise RuntimeError("managed_sandbox_not_allocated")
        cipher = _managed_provider_reference_cipher(
            config=config,
            allocation_id=allocation_id,
            provider=allocation.provider,
            generation=allocation.generation,
        )
        session = await sandboxes.open_session(
            cipher.decrypt(allocation.provider_ref)
        )
        managed = config.sandbox.managed
        manifest = await SessionPortableArchiveBuilder(
            store=_managed_archive_store(config),
            image_identity=sandboxes.image_identity,
            toolchain_identity=managed.toolchain_identity,
            max_archive_bytes=managed.archive_max_bytes,
            max_archive_entries=managed.archive_max_entries,
            retention_seconds=managed.archive_retention_seconds,
        ).build(
            session,
            allocation_id=allocation_id,
            generation=allocation.generation,
        )
        await repository.set_archive_ref(
            allocation_id,
            archive_id=manifest.archive_id,
            now=datetime.now(UTC),
        )
        return manifest

    return take


def managed_sandbox_status_service(
    session_factory=None,
) -> ManagedSandboxStatusService:
    """소유자 조회 서비스. `sandbox.managed.enabled`와 무관하게 조립된다.

    플래그가 꺼져 있으면 할당 행이 아예 없어서 조회가 `None`을 내고 API 는
    404 를 낸다 -- 별도 분기를 두지 않는 편이 "꺼져 있음"과 "샌드박스 없음"을
    같은 답으로 유지한다.
    """
    return ManagedSandboxStatusService(
        repository=_managed_sandbox_repository(session_factory)
    )


def managed_sandbox_admin_service(
    session_factory=None,
) -> ManagedSandboxAdminService:
    """운영자 조치 서비스.

    드레인은 **내구 저장소**를 거친다(마이그레이션 046) -- API 프로세스에서
    켠 드레인을 Celery 워커의 admission 이 곧바로 본다.

    아카이브 서비스도 배선돼 있다(CA10 종결) -- 복구 승인이 실제로 검증된
    아카이브 위에서 일어난다.
    """
    factory = session_factory or db_manager.get_session
    config = settings.config
    repository = _managed_sandbox_repository(factory)
    provider = create_sandbox_provider(config.sandbox)
    return ManagedSandboxAdminService(
        repository=repository,
        archives=create_managed_archive_service(
            config=config, repository=repository
        ),
        archiver=create_managed_archive_taker(
            config=config, repository=repository, sandboxes=provider
        ),
        drains=create_provider_health_store(
            factory, config=config.sandbox.managed
        ),
    )


def create_managed_sandbox_allocation_service(
    *,
    config: AppConfig,
    sandboxes,
    repository,
    cipher,
    archive_importer=None,
) -> ManagedSandboxAllocationService | None:
    """관리형 할당 서비스를 config 로 배선한다.

    레지스트리가 비어 있으면(=`sandbox.managed.enabled`가 꺼져 있으면) 아무것도
    만들지 않는다 -- 기존 경로를 불변으로 둔다. resource_limits·network_policy·
    image_identity·lease_seconds 는 배치 정책이라 할당별로 저장하지 않고
    (`ManagedSandboxAllocationService`·`AllocationPlan` 문서 참고) 여기서 매번
    config 로부터 채운다. `cipher`는 이 함수가 만들지 않는다 -- 호출자가
    `_managed_provider_reference_cipher()`로 advance() 대상 할당에 맞춰 만들어
    넘겨야 한다(그 함수 문서 참고).
    """
    adapters = _managed_adapter_registry(config=config, sandboxes=sandboxes)
    if not adapters:
        return None
    return ManagedSandboxAllocationService(
        repository=repository,
        adapters=adapters,
        cipher=cipher,
        resource_limits=_managed_sandbox_resource_limits(config),
        network_policy=ManagedNetworkPolicy.BLOCK_ALL,
        image_identity=sandboxes.image_identity,
        lease_seconds=config.sandbox.managed.allocation_lease_seconds,
        # 복구 세대(`archive_ref`가 있는 할당)만 이 포트를 쓴다. 배선되지
        # 않은 채 복구 세대가 오면 서비스가 조용히 넘어가지 않고
        # `ManagedArchiveImportUnavailable`를 올려 원장에 사유를 남긴다
        # (`ManagedSandboxAllocationService._import_archive`). 프로덕션
        # 구현체 배선은 Task 8/9 몫이다.
        archive_importer=archive_importer,
    )


def _prepare_real_coding_loop(*, config: AppConfig, session_factory=None):
    coding = config.coding_model
    coding_model = resolve_model(
        config=config.model_routing,
        provider=coding.provider,
        role="everyday",
        feature_override=coding.model,
    ).model
    sandbox = config.sandbox
    resources = sandbox.resources
    execution = sandbox.execution
    limits = SandboxLimits(
        cpu_count=resources.cpu_count,
        memory_bytes=resources.memory_bytes,
        pids=resources.pids,
        workspace_bytes=resources.workspace_bytes,
        command_timeout_sec=min(execution.command_timeout_sec, coding.tool_timeout_sec),
        max_output_bytes=execution.max_output_bytes,
        max_stdin_bytes=execution.max_stdin_bytes,
    )
    repository = PostgresSandboxBindingRepository(
        session_factory or db_manager.get_session
    )
    allowlist = coding.command_allowlist if coding.command_enabled else []
    tools = CodingToolRegistry.default(
        command_allowlist=frozenset(allowlist),
        max_command_timeout_sec=coding.tool_timeout_sec,
        max_command_output_bytes=execution.max_output_bytes,
        max_command_stdin_bytes=execution.max_stdin_bytes,
        allowed_env_names=frozenset(execution.allowed_env_names),
    )
    # 계측은 전송 계층 **밖에서** 감싼다 (D1c). 프로바이더 구현을 건드리지
    # 않으므로 D4(네이티브 SDK 전환)가 그 아래를 바꿔도 함께 무너지지 않는다.
    # 코딩 루프는 Celery 워커에서 도는데, D1b 이후 레코드가 그 프로세스에서
    # 바로 디스크에 남으므로 flush 지점을 지나갈 필요가 없다.
    model = TrackedCodingModel(
        AnthropicCodingModel(
            build_async_anthropic(api_key=config.secrets.anthropic_api_key)
        ),
        workflow_step="coding_loop",
    )
    executor = SandboxToolExecutor(
        max_preview_bytes=execution.max_output_bytes,
        max_entries=1000,
    )
    loop_config = AnthropicLoopConfig(
        model=coding_model,
        system=build_coding_system_prompt(
            tools.definitions(),
            env=CodingPromptEnv(
                command_allowlist=tuple(sorted(allowlist)),
            ),
        ),
        max_output_tokens=coding.max_output_tokens,
        timeout_sec=coding.model_timeout_sec,
        tool_claim_ttl_sec=coding.tool_timeout_sec,
        max_turns=coding.max_turns,
        max_tools=coding.max_tool_calls,
        max_consecutive_tool_errors=coding.max_consecutive_tool_errors,
        max_cost_micros=int(coding.max_cost_usd * 1_000_000),
        input_cost_micros_per_million=(coding.input_cost_micros_per_million),
        output_cost_micros_per_million=(coding.output_cost_micros_per_million),
        max_transcript_bytes=coding.max_transcript_bytes,
        max_text_delta_bytes=coding.max_text_delta_bytes,
        max_public_text_bytes=coding.max_public_text_bytes,
        approval_ttl_sec=coding.approval_ttl_seconds,
    )

    def finish(sandboxes) -> AnthropicCodingLoop:
        bindings = SandboxBindingService(
            repository=repository,
            provider=sandboxes,
            limits=limits,
            snapshot_cadence=coding.mutation_snapshot_interval,
        )
        loop = AnthropicCodingLoop(
            model=model,
            tools=tools,
            executor=executor,
            bindings=bindings,
            config=loop_config,
            metrics=metrics,
            audit=LoggingCodingAuditSink(),
        )
        # 코딩 루프의 model 축(TrackedCodingModel 계측, 위)과 이 sandbox
        # provider 축은 직교한다 -- 관리형이 꺼져 있으면(기본값) 빈 dict라
        # 아래는 부작용이 없다. 실제 ManagedSandboxAllocationService는
        # create_managed_sandbox_allocation_service()가 따로 조립한다: cipher는
        # 할당마다 새로 만들어야 해서(_managed_provider_reference_cipher 문서
        # 참고) 여기서 함께 만들 수 없다.
        loop.managed_adapters = _managed_adapter_registry(
            config=config, sandboxes=sandboxes
        )
        return loop

    return finish


def _create_real_coding_loop(
    *, config: AppConfig, sandboxes, session_factory=None
) -> AnthropicCodingLoop:
    return _prepare_real_coding_loop(config=config, session_factory=session_factory)(
        sandboxes
    )


def _close_provider_sync(provider) -> None:
    error: list[BaseException] = []

    def close() -> None:
        try:
            asyncio.run(provider.close())
        except BaseException as caught:
            error.append(caught)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        close()
    else:
        thread = threading.Thread(target=close, name="coding-provider-close")
        thread.start()
        thread.join()
    if error:
        raise error[0]


def create_development_coding_runtime(
    *, config: AppConfig | None = None
) -> CodingRuntime:
    config = config or settings.config
    if settings.CODING_FAKE_LOOP_ENABLED and settings.CODING_CELERY_ENABLED:
        raise RuntimeError(
            "CODING_FAKE_LOOP_ENABLED and CODING_CELERY_ENABLED "
            "cannot be enabled together"
        )
    if settings.CODING_FAKE_LOOP_ENABLED and config.coding_model.enabled:
        raise RuntimeError("fake and real coding loops cannot be enabled together")
    finish_loop = None
    if config.coding_model.enabled:
        finish_loop = _prepare_real_coding_loop(config=config)
    sandboxes = create_sandbox_provider(config.sandbox)
    try:
        if settings.CODING_FAKE_LOOP_ENABLED:
            loop = FakeDurableCodingLoop(clock=lambda: datetime.now(UTC))
        elif finish_loop is not None:
            loop = finish_loop(sandboxes)
        else:
            loop = None
        run_repository = PostgresCodingRunRepository(db_manager.get_session)
        runtime = create_coding_runtime(
            events=coding_service,
            tasks=CodingTaskRepository(db_manager),
            run_repository=run_repository,
            projection_repository=PostgresCodingProjectionRepository(
                db_manager.get_session
            ),
            loop=loop,
            metrics_collector=metrics,
            interrupter=InProcessRunInterrupter(),
            sandboxes=sandboxes,
            config=config,
        )
        supervisor = None
        if settings.CODING_FAKE_LOOP_ENABLED:
            supervisor = CodingDevelopmentSupervisor(
                runs=runtime.runs,
                work_repository=run_repository,
                metrics=metrics,
                reconciliation_interval=(settings.CODING_DEV_RECONCILIATION_SECONDS),
                discovery_batch_size=settings.CODING_DEV_DISCOVERY_BATCH_SIZE,
                shutdown_timeout=settings.CODING_DEV_SHUTDOWN_SECONDS,
            )
        notifier = None
        if supervisor is not None:
            notifier = supervisor.notify
        elif settings.CODING_CELERY_ENABLED:
            validate_coding_worker_settings(settings)

            def notify_celery(task_id):
                dispatcher = create_celery_dispatcher()
                return dispatcher.enqueue(
                    task_id,
                    expected_checkpoint_id=None,
                    source=CodingDispatchSource.API,
                )

            notifier = notify_celery
        coding_service.set_task_created_notifier(notifier)
        async def wake_approval(task_id: str, checkpoint_id: str) -> None:
            if supervisor is not None:
                supervisor.notify(task_id)
            elif settings.CODING_CELERY_ENABLED:
                create_celery_dispatcher().enqueue(
                    task_id,
                    expected_checkpoint_id=checkpoint_id,
                    source=CodingDispatchSource.APPROVAL,
                )

        runtime.approvals = CodingApprovalService(
            run_repository,
            wake=wake_approval,
            metrics=metrics,
            audit=LoggingCodingAuditSink(),
        )
        return replace(runtime, supervisor=supervisor)
    except BaseException:
        _close_provider_sync(sandboxes)
        raise


def create_celery_dispatcher() -> CeleryCodingTaskDispatcher:
    from neos.workflow.celery_app import app

    return CeleryCodingTaskDispatcher(
        app=app,
        queue=settings.CODING_CELERY_QUEUE,
        metrics=metrics,
    )


coding_runtime = create_development_coding_runtime()
coding_run_service = coding_runtime.runs
coding_snapshot_service = coding_runtime.snapshots
coding_approval_service = coding_runtime.approvals
coding_workspace_service = coding_runtime.workspace
coding_workspace_stream_service = coding_runtime.workspace_streams


def initialize_coding_transport(
    *, redis_client: Any | None, production: bool
) -> CodingRuntimeTransport:
    global coding_transport
    if production:
        if redis_client is None:
            raise RuntimeError("Redis is required for production coding transport")
        runtime = CodingRuntimeTransport(
            tickets=RedisCodingTicketStore(redis_client),
            events=RedisCodingEventTransport(redis_client),
            workspace_tickets=RedisWorkspaceTicketStore(
                redis_client,
                ttl_seconds=settings.config.sandbox.workspace.ticket_ttl_seconds,
            ),
        )
    else:
        runtime = CodingRuntimeTransport(
            tickets=InMemoryWsTicketStore(),
            events=InProcessCodingEventBroker(),
            workspace_tickets=InMemoryWorkspaceTicketStore(),
        )
    coding_transport = runtime
    coding_outbox_dispatcher.set_publisher(runtime.events)
    return runtime


async def close_coding_transport() -> None:
    await coding_transport.events.close()


def get_coding_ticket_store() -> CodingTicketStore:
    return coding_transport.tickets


def get_coding_event_transport() -> CodingEventTransport:
    return coding_transport.events


def get_workspace_ticket_store() -> WorkspaceTicketStore:
    return coding_transport.workspace_tickets


def start_coding_outbox_dispatcher(
    dispatcher: CodingOutboxDispatcher = coding_outbox_dispatcher,
) -> asyncio.Task:
    return asyncio.create_task(dispatcher.run(), name="coding-outbox-dispatcher")


async def stop_coding_outbox_dispatcher(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

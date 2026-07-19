import asyncio
import threading
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from anthropic import AsyncAnthropic

from neos.coding.application.run_service import (
    CodingRunService,
    InProcessRunInterrupter,
)
from neos.coding.application.snapshot_service import CodingSnapshotService
from neos.coding.loop.base import CodingLoop
from neos.coding.loop.fake import FakeDurableCodingLoop
from neos.coding.loop.anthropic import AnthropicCodingLoop, AnthropicLoopConfig
from neos.coding.model.anthropic import AnthropicCodingModel
from neos.coding.repositories.sandbox_repository import PostgresSandboxBindingRepository
from neos.coding.sandbox.base import SandboxLimits
from neos.coding.sandbox.bindings import SandboxBindingService
from neos.coding.tools.executor import SandboxToolExecutor
from neos.coding.tools.registry import CodingToolRegistry
from neos.coding.outbox.dispatcher import CodingOutboxDispatcher
from neos.coding.outbox.repository import PostgresCodingOutboxRepository
from neos.coding.persistence.postgres import PostgresCodingService
from neos.coding.repositories.run_repository import PostgresCodingRunRepository
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
from neos.database.connection import db_manager
from neos.config.settings import settings
from neos.config.schema import AppConfig
from neos.observability.metrics import metrics


@dataclass(frozen=True, slots=True)
class CodingRuntimeTransport:
    tickets: CodingTicketStore
    events: CodingEventTransport


@dataclass(slots=True)
class CodingRuntime:
    events: Any
    runs: CodingRunService
    snapshots: CodingSnapshotService
    sandboxes: Any
    supervisor: CodingDevelopmentSupervisor | None = None
    _closed: bool = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.supervisor is not None:
            await self.supervisor.stop()
        await self.sandboxes.close()


coding_transport = CodingRuntimeTransport(
    tickets=InMemoryWsTicketStore(),
    events=InProcessCodingEventBroker(),
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
) -> CodingRuntime:
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
        **run_kwargs,
    )
    sandbox_provider = sandboxes or create_sandbox_provider(
        settings.config.sandbox
    )
    return CodingRuntime(
        events=events,
        runs=runs,
        snapshots=snapshots,
        sandboxes=sandbox_provider,
    )


def _prepare_real_coding_loop(*, config: AppConfig, session_factory=None):
    coding = config.coding_model
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
    model = AnthropicCodingModel(
        AsyncAnthropic(api_key=config.secrets.anthropic_api_key)
    )
    executor = SandboxToolExecutor(
        max_preview_bytes=execution.max_output_bytes,
        max_entries=1000,
    )
    loop_config = AnthropicLoopConfig(
            model=coding.model,
            system="Work safely in the provided sandbox and complete the coding task.",
            max_output_tokens=coding.max_output_tokens,
            timeout_sec=coding.model_timeout_sec,
            tool_claim_ttl_sec=coding.tool_timeout_sec,
            max_turns=coding.max_turns,
            max_tools=coding.max_tool_calls,
            max_consecutive_tool_errors=coding.max_consecutive_tool_errors,
            max_cost_micros=int(coding.max_cost_usd * 1_000_000),
            input_cost_micros_per_million=(
                coding.input_cost_micros_per_million
            ),
            output_cost_micros_per_million=(
                coding.output_cost_micros_per_million
            ),
        max_transcript_bytes=coding.max_transcript_bytes,
    )

    def finish(sandboxes) -> AnthropicCodingLoop:
        bindings = SandboxBindingService(
            repository=repository,
            provider=sandboxes,
            limits=limits,
            snapshot_cadence=coding.mutation_snapshot_interval,
        )
        return AnthropicCodingLoop(
            model=model,
            tools=tools,
            executor=executor,
            bindings=bindings,
            config=loop_config,
        )

    return finish


def _create_real_coding_loop(
    *, config: AppConfig, sandboxes, session_factory=None
) -> AnthropicCodingLoop:
    return _prepare_real_coding_loop(
        config=config, session_factory=session_factory
    )(sandboxes)


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


def create_development_coding_runtime(*, config: AppConfig | None = None) -> CodingRuntime:
    config = config or settings.config
    if (
        settings.CODING_FAKE_LOOP_ENABLED
        and settings.CODING_CELERY_ENABLED
    ):
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
        )
        supervisor = None
        if settings.CODING_FAKE_LOOP_ENABLED:
            supervisor = CodingDevelopmentSupervisor(
                runs=runtime.runs,
                work_repository=run_repository,
                metrics=metrics,
                reconciliation_interval=(
                    settings.CODING_DEV_RECONCILIATION_SECONDS
                ),
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
                return dispatcher.enqueue(task_id, source=CodingDispatchSource.API)

            notifier = notify_celery
        coding_service.set_task_created_notifier(notifier)
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
        )
    else:
        runtime = CodingRuntimeTransport(
            tickets=InMemoryWsTicketStore(),
            events=InProcessCodingEventBroker(),
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


def start_coding_outbox_dispatcher(
    dispatcher: CodingOutboxDispatcher = coding_outbox_dispatcher,
) -> asyncio.Task:
    return asyncio.create_task(
        dispatcher.run(), name="coding-outbox-dispatcher"
    )


async def stop_coding_outbox_dispatcher(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

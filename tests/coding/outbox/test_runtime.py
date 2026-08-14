import asyncio

import pytest

from neos.coding import runtime as coding_runtime_module
from neos.coding.runtime import (
    close_coding_transport,
    coding_outbox_dispatcher,
    initialize_coding_transport,
    start_coding_outbox_dispatcher,
    stop_coding_outbox_dispatcher,
)
from neos.coding.transport.memory import (
    InMemoryWsTicketStore,
    InProcessCodingEventBroker,
)
from neos.coding.transport.redis_events import RedisCodingEventTransport
from neos.coding.transport.redis_tickets import RedisCodingTicketStore


@pytest.fixture(autouse=True)
def restore_the_process_wide_transport():
    """이 파일은 프로세스 전역 `coding_transport` 를 갈아끼운다. 되돌린다.

    `test_production_requires_redis_and_selects_redis_adapters` 는 Redis 클라이언트
    자리에 `object()` 를 넣고 production 어댑터를 고르게 한다 -- 그 단언은
    "어떤 어댑터를 고르는가" 이므로 진짜 Redis 가 필요 없다. 문제는 그 결과가
    **모듈 전역에 남는다**는 것이다.

    뒤이어 도는 웹소켓 테스트는 `get_coding_event_transport()` 로 그 전역을
    읽고, `object()` 를 감싼 Redis 어댑터에서 `'object' object has no attribute
    'pubsub'` 로 죽는다. 핸들러가 그것을 소켓 종료로 바꾸므로 증상은
    `anyio.EndOfStream` 이다.

    **이것이 2026-08-14 게이트가 간헐적으로 붉었던 이유다**(시드 3510494599 로
    재현). 순서 의존이라 파일 단독 실행에서는 영원히 안 보이고,
    `pytest-randomly` 를 켠 뒤에야 드러났다.
    """
    previous = coding_runtime_module.coding_transport
    previous_publisher = coding_outbox_dispatcher._publisher
    yield
    coding_runtime_module.coding_transport = previous
    coding_outbox_dispatcher._publisher = previous_publisher


class BlockingDispatcher:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(self) -> None:
        self.started.set()
        await asyncio.Event().wait()


async def test_start_and_stop_manage_dispatcher_task() -> None:
    dispatcher = BlockingDispatcher()
    task = start_coding_outbox_dispatcher(dispatcher)
    await dispatcher.started.wait()

    await stop_coding_outbox_dispatcher(task)

    assert task.cancelled()


def test_production_requires_redis_and_selects_redis_adapters() -> None:
    try:
        initialize_coding_transport(redis_client=None, production=True)
    except RuntimeError as error:
        assert "Redis" in str(error)
    else:
        raise AssertionError("production initialization must fail without Redis")

    redis = object()
    runtime = initialize_coding_transport(redis_client=redis, production=True)

    assert isinstance(runtime.tickets, RedisCodingTicketStore)
    assert isinstance(runtime.events, RedisCodingEventTransport)


async def test_development_explicitly_selects_in_memory_adapters() -> None:
    runtime = initialize_coding_transport(redis_client=None, production=False)

    assert isinstance(runtime.tickets, InMemoryWsTicketStore)
    assert isinstance(runtime.events, InProcessCodingEventBroker)
    await close_coding_transport()
    initialize_coding_transport(redis_client=None, production=False)

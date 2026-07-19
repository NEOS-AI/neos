import asyncio

import pytest

from neos.coding.sandbox.base import ReplayGap, SandboxStateConflict
from neos.coding.sandbox.streams import BoundedReplayStream


async def test_replay_stream_orders_and_replays_after_cursor() -> None:
    stream = BoundedReplayStream[str](
        max_events=3,
        max_bytes=20,
        size_of=len,
    )

    one = await stream.publish("one")
    two = await stream.publish("two")

    replay = await stream.replay(after_cursor=one.cursor)
    assert [event.value for event in replay] == ["two"]
    assert two.cursor == one.cursor + 1


async def test_event_limit_evicts_old_cursor() -> None:
    stream = BoundedReplayStream[str](
        max_events=2,
        max_bytes=20,
        size_of=len,
    )
    first = await stream.publish("one")
    await stream.publish("two")
    await stream.publish("three")

    with pytest.raises(ReplayGap, match="cursor 0 was evicted"):
        await stream.replay(after_cursor=first.cursor - 1)


async def test_byte_limit_evicts_old_cursor() -> None:
    stream = BoundedReplayStream[str](
        max_events=10,
        max_bytes=5,
        size_of=len,
    )
    await stream.publish("abc")
    await stream.publish("def")

    with pytest.raises(ReplayGap):
        await stream.replay(after_cursor=0)
    assert [event.value for event in await stream.replay(after_cursor=1)] == [
        "def"
    ]


async def test_subscriber_receives_replay_then_live_event_without_gap() -> None:
    stream = BoundedReplayStream[str](
        max_events=5,
        max_bytes=20,
        size_of=len,
    )
    first = await stream.publish("replayed")
    subscription = stream.subscribe(after_cursor=0)

    assert (await anext(subscription)) == first

    published = await stream.publish("live")
    async with asyncio.timeout(1):
        assert (await anext(subscription)) == published
    await subscription.aclose()


async def test_close_ends_subscribers_and_rejects_publish() -> None:
    stream = BoundedReplayStream[str](
        max_events=2,
        max_bytes=20,
        size_of=len,
    )
    subscription = stream.subscribe(after_cursor=0)
    pending = asyncio.create_task(anext(subscription))
    await asyncio.sleep(0)

    await stream.close()

    with pytest.raises(StopAsyncIteration):
        await pending
    with pytest.raises(SandboxStateConflict, match="stream_closed"):
        await stream.publish("late")

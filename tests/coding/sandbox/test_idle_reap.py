from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from neos.coding.sandbox.base import SandboxLimits, SandboxNotFound
from neos.coding.sandbox.bindings import reap_unbound_idle_sandboxes
from neos.coding.sandbox.memory import MemorySandboxProvider

pytestmark = pytest.mark.no_db

NOW = datetime(2026, 7, 19, 10, tzinfo=UTC)
IDLE = timedelta(seconds=30)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _provider(tmp_path: Path, clock: Clock) -> MemorySandboxProvider:
    return MemorySandboxProvider(
        root=tmp_path,
        clock=clock,
        idle_timeout=IDLE,
    )


@pytest.mark.asyncio
async def test_create_sets_idle_deadline_from_clock(tmp_path: Path) -> None:
    clock = Clock(NOW)
    provider = _provider(tmp_path, clock)
    sandbox = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())

    assert sandbox.idle_expires_at == NOW + IDLE
    await provider.close()


@pytest.mark.asyncio
async def test_session_activity_bumps_idle_deadline(tmp_path: Path) -> None:
    clock = Clock(NOW)
    provider = _provider(tmp_path, clock)
    created = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
    session = await provider.open_session(created.sandbox_id)

    clock.now = NOW + timedelta(seconds=10)
    await session.write_file("foo.py", b"x")
    after_write = await provider.get(created.sandbox_id)
    assert after_write.idle_expires_at == clock.now + IDLE

    clock.now = NOW + timedelta(seconds=20)
    await session.read_file("foo.py")
    after_read = await provider.get(created.sandbox_id)
    assert after_read.idle_expires_at == clock.now + IDLE
    await provider.close()


@pytest.mark.asyncio
async def test_reap_releases_unbound_idle_sandbox(tmp_path: Path) -> None:
    clock = Clock(NOW)
    provider = _provider(tmp_path, clock)
    idle = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
    live = await provider.create(owner_id="u2", limits=SandboxLimits.safe_defaults())

    clock.now = NOW + IDLE + timedelta(seconds=1)
    reaped = await reap_unbound_idle_sandboxes(
        provider,
        bound_sandbox_ids=frozenset({live.sandbox_id}),
        now=clock.now,
    )

    assert idle.sandbox_id in reaped
    assert live.sandbox_id not in reaped
    with pytest.raises(SandboxNotFound):
        await provider.get(idle.sandbox_id)
    assert (await provider.get(live.sandbox_id)).sandbox_id == live.sandbox_id
    await provider.close()


@pytest.mark.asyncio
async def test_reap_does_not_kill_bound_live_task(tmp_path: Path) -> None:
    clock = Clock(NOW)
    provider = _provider(tmp_path, clock)
    bound = await provider.create(owner_id="task-live", limits=SandboxLimits.safe_defaults())

    clock.now = NOW + IDLE + timedelta(minutes=5)
    reaped = await reap_unbound_idle_sandboxes(
        provider,
        bound_sandbox_ids=frozenset({bound.sandbox_id}),
        now=clock.now,
    )

    assert reaped == ()
    assert (await provider.get(bound.sandbox_id)).state.value == "running"
    await provider.close()


@pytest.mark.asyncio
async def test_activity_extends_idle_so_unbound_is_not_reaped(tmp_path: Path) -> None:
    clock = Clock(NOW)
    provider = _provider(tmp_path, clock)
    created = await provider.create(owner_id="u1", limits=SandboxLimits.safe_defaults())
    session = await provider.open_session(created.sandbox_id)

    clock.now = NOW + timedelta(seconds=20)
    await session.write_file("keep.py", b"ok")
    clock.now = NOW + IDLE + timedelta(seconds=1)
    reaped = await reap_unbound_idle_sandboxes(
        provider,
        bound_sandbox_ids=frozenset(),
        now=clock.now,
    )

    assert reaped == ()
    assert await provider.get(created.sandbox_id)
    await provider.close()

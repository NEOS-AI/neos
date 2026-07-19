from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from neos.coding.sandbox.base import SandboxProvider
from neos.coding.sandbox.memory import MemorySandboxProvider


@asynccontextmanager
async def memory_provider(
    root: Path,
) -> AsyncIterator[SandboxProvider]:
    provider = MemorySandboxProvider(root=root)
    try:
        yield provider
    finally:
        await provider.close()

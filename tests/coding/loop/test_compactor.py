"""The compactor as a component: built on its own, same defaults as the loop's."""

import pytest

from neos.coding.hooks import NullCodingHooks
from neos.coding.loop import Compactor, ToolCatalog, initial_state
from tests.coding.loop.support import INPUT, harness

pytestmark = pytest.mark.no_db


def test_a_compactor_without_hooks_uses_the_null_hooks() -> None:
    h = harness([])
    compactor = Compactor(
        config=h.config,
        model=h.model,
        catalog=ToolCatalog(h.loop_kwargs["tools"], h.config),
    )

    assert isinstance(compactor._hooks, NullCodingHooks)


@pytest.mark.asyncio
async def test_a_compactor_without_hooks_still_compacts_after_prompt_too_long() -> None:
    h = harness([])
    state = initial_state(INPUT)

    after = await h.compactor().compact_after_prompt_too_long(state)

    assert after.prompt_compact_retries == state.prompt_compact_retries + 1

"""The shared loop harness: constructor pass-through and `rebuilt`."""

from dataclasses import replace

import pytest

from neos.coding.loop import initial_state
from neos.coding.model.base import ModelCompleted, ModelUsage
from tests.coding.loop.support import (
    INPUT,
    NOW,
    checkpoint_for,
    collect,
    completed,
    harness,
    tool_call,
)

pytestmark = pytest.mark.no_db


def test_harness_passes_constructor_arguments_through() -> None:
    later = lambda: NOW  # noqa: E731
    rules = object()
    h = harness([], clock=later, user_rules=rules)

    assert h.loop_kwargs["clock"] is later
    assert h.loop_kwargs["user_rules"] is rules
    assert h.config.model == "claude-test"


def test_harness_uses_a_given_model_instead_of_turns() -> None:
    class Custom:
        async def stream(self, request):
            yield ModelCompleted("end_turn", ModelUsage(1, 1))

    model = Custom()
    h = harness(model=model)

    assert h.model is model
    assert h.loop_kwargs["model"] is model


@pytest.mark.asyncio
async def test_rebuilt_shares_the_repository_and_the_model_queue() -> None:
    h = harness([[tool_call(), completed()], [ModelCompleted("end_turn", ModelUsage(1, 1))]])
    await collect(h)
    parked = h.repository.checkpoints[-1]

    again = h.rebuilt(config=replace(h.config, max_turns=h.config.max_turns))

    assert again.loop is not h.loop
    assert again.repository is h.repository
    assert again.model is h.model
    assert again.deps is h.deps
    assert again.config == h.config
    before = len(h.repository.checkpoints)
    await collect(again, parked)
    assert len(h.repository.checkpoints) > before
    assert len(h.model.requests) == 2


def test_rebuilt_rejects_an_unknown_dependency() -> None:
    with pytest.raises(TypeError):
        harness([]).rebuilt(not_a_dependency=1)


def test_checkpoint_for_encodes_the_state() -> None:
    checkpoint = checkpoint_for(initial_state(INPUT))

    assert checkpoint.loop_state["current_instruction"] == "Fix it"
    assert checkpoint.checkpoint_id == "cc_test"

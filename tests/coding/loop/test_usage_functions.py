"""Usage and window arithmetic: pure functions of the loop config."""

from dataclasses import replace

import pytest

from neos.coding.loop import AnthropicLoopConfig, parent_headroom_chars, transcript_token_limit
from neos.coding.loop import initial_state
from tests.coding.loop.support import INPUT

pytestmark = pytest.mark.no_db

BASE = AnthropicLoopConfig(model="claude-test", system="code")


def test_without_a_context_window_the_transcript_cap_is_the_configured_one() -> None:
    config = replace(BASE, context_window=None, max_transcript_tokens=12_345)

    assert transcript_token_limit(config) == 12_345


def test_with_a_context_window_the_cap_is_the_usable_window() -> None:
    config = replace(BASE, context_window=40_000, max_output_tokens=8_192, max_transcript_tokens=80_000)

    assert transcript_token_limit(config) < 40_000


def test_parent_headroom_is_four_chars_per_remaining_token() -> None:
    config = replace(BASE, context_window=None, max_transcript_tokens=1_000)
    state = replace(initial_state(INPUT), last_prompt_tokens=400)

    assert parent_headroom_chars(config, state) == 600 * 4


def test_headroom_never_goes_negative() -> None:
    config = replace(BASE, context_window=None, max_transcript_tokens=100)
    state = replace(initial_state(INPUT), last_prompt_tokens=10_000)

    assert parent_headroom_chars(config, state) == 0

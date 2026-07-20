import os

import pytest


pytestmark = [
    pytest.mark.no_db,
    pytest.mark.skipif(
        os.getenv("NEOS_RUN_ANTHROPIC_INTEGRATION") != "1"
        or not os.getenv("ANTHROPIC_API_KEY"),
        reason=(
            "requires NEOS_RUN_ANTHROPIC_INTEGRATION=1 and ANTHROPIC_API_KEY"
        ),
    ),
]


@pytest.mark.asyncio
async def test_anthropic_one_turn_text_smoke() -> None:
    from anthropic import AsyncAnthropic

    response = await AsyncAnthropic().messages.create(
        model=os.getenv("NEOS_ANTHROPIC_INTEGRATION_MODEL", "claude-haiku-4-5"),
        max_tokens=8,
        messages=[{"role": "user", "content": "Reply with OK only."}],
    )

    assert response.content

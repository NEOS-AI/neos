"""Coding-model reflector. The model client is faked."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.no_db


@pytest.mark.asyncio
async def test_reflector_calls_the_coding_model_and_counts_io_tokens(monkeypatch) -> None:
    import neos.gepa_opt.provider as provider

    seen = {}

    def create_coding_model(*, provider: str):
        seen["provider"] = provider
        return object()

    async def collect_model_turn(client, request):
        seen["client"] = client
        seen["request"] = request
        return SimpleNamespace(
            text_parts=("```\nb\n```",),
            completion=SimpleNamespace(
                stop_reason="end_turn",
                usage=SimpleNamespace(
                    input_tokens=4,
                    output_tokens=6,
                    cache_read_tokens=9,
                    reasoning_tokens=2,
                ),
            ),
        )

    monkeypatch.setattr(provider, "create_coding_model", create_coding_model)
    monkeypatch.setattr(provider, "collect_model_turn", collect_model_turn)
    result = await provider.reflect_with_coding_model(
        "instr",
        "current",
        "<side_info>{}",
        run_id="run-1",
        provider="anthropic",
        model="claude-test",
    )
    assert seen["provider"] == "anthropic"
    assert seen["request"].task_id == "gepa_opt"
    assert seen["request"].run_id == "run-1"
    assert seen["request"].turn_id
    assert seen["request"].model == "claude-test"
    assert result.delta == {"instr": "b"}
    assert result.usage.input_tokens == 4
    assert result.usage.output_tokens == 6
    assert not hasattr(result.usage, "cache_read_tokens") or result.usage.input_tokens == 4

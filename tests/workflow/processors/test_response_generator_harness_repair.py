from datetime import datetime
from types import SimpleNamespace

import pytest

from neos.workflow.processors.response_generator import ResponseGenerator


@pytest.mark.asyncio
async def test_response_generator_mentions_repair_plan_in_refinement_prompt(
    monkeypatch,
):
    captured = {}

    class _FakeLLM:
        async def ainvoke(self, messages):
            captured["prompt"] = messages[0].content
            return "repaired answer"

    monkeypatch.setattr(ResponseGenerator, "_get_llm", lambda self, **kwargs: _FakeLLM())
    monkeypatch.setattr(
        "neos.workflow.processors.response_generator.create_tracked_llm",
        lambda llm, **kwargs: llm,
    )
    monkeypatch.setattr(
        "neos.workflow.processors.response_generator.extract_text_from_response",
        lambda response: str(response),
    )
    monkeypatch.setattr(
        "neos.workflow.processors.response_generator.settings.ENABLE_RESPONSE_REFINEMENT",
        True,
    )

    state = {
        "original_query": "Explain the market impact",
        "search_results": [],
        "analysis_results": [],
        "generation_results": [SimpleNamespace(content="draft", content_type="summary")],
        "search_metadata": {"partial_success": True},
        "errors": [],
        "detected_language": "en",
        "execution_start": datetime.now(),
        "execution_steps": [],
        "harness_repair_plan": {
            "actions": [
                {
                    "action_type": "regenerate_unsupported_claims",
                    "target_check": "factuality",
                    "reason": "Unsupported claim found",
                    "params": {"failed_items": [{"claim": "unsupported"}]},
                }
            ]
        },
    }

    await ResponseGenerator().generate_response(state)

    assert "regenerate_unsupported_claims" in captured["prompt"]
    assert "Unsupported claim found" in captured["prompt"]

"""Reflect one component with the coding model client. No CodingRun."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from neos.coding.harness.turn import collect_model_turn
from neos.coding.model.base import CanonicalMessage, ModelLimits, ModelRequest, TextContent
from neos.gepa_opt.reflect import ParseSkip, parse_proposal
from neos.utils.llm_factory import create_coding_model


async def reflect_with_coding_model(
    component_name: str,
    curr_param: str,
    side_info_text: str,
    *,
    run_id: str,
    provider: str,
    model: str,
) -> SimpleNamespace:
    """One completion. Token cost is input_tokens + output_tokens only."""
    client = create_coding_model(provider=provider)
    request = ModelRequest(
        system=curr_param,
        messages=(CanonicalMessage("user", (TextContent(side_info_text),)),),
        tools=(),
        model=model,
        limits=ModelLimits(max_output_tokens=4096, timeout_sec=120),
        task_id="gepa_opt",
        run_id=run_id,
        turn_id=uuid.uuid4().hex,
    )
    turn = await collect_model_turn(client, request)
    text = "".join(turn.text_parts)
    usage = turn.completion.usage if turn.completion is not None else None
    stop = turn.completion.stop_reason if turn.completion is not None else None
    parsed = parse_proposal(text, stop)
    delta = {} if isinstance(parsed, ParseSkip) else {component_name: parsed}
    return SimpleNamespace(
        component_name=component_name,
        delta=delta,
        usage=SimpleNamespace(
            input_tokens=0 if usage is None else usage.input_tokens,
            output_tokens=0 if usage is None else usage.output_tokens,
            finish_reason=stop,
        ),
        text=text,
    )

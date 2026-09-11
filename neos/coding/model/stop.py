from __future__ import annotations

_STOP_REASON_ALIASES = {
    "end_turn": "end_turn",
    "stop": "end_turn",
    "STOP": "end_turn",
    "tool_use": "tool_use",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "max_tokens": "max_tokens",
    "length": "max_tokens",
    "MAX_TOKENS": "max_tokens",
    "max_output_tokens": "max_tokens",
}


def normalize_stop_reason(
    raw: object, *, has_tool_calls: bool = False
) -> str:
    """Map vendor finish reasons onto the coding loop's three outcomes.

    The durable loop only branches on `tool_use`, `end_turn`, and
    `max_tokens`. Vendor adapters must collapse everything else here so
    the harness never learns a provider's vocabulary.
    """
    if has_tool_calls:
        return "tool_use"
    if raw is None:
        return "unknown"
    mapped = _STOP_REASON_ALIASES.get(str(raw))
    return mapped or str(raw) or "unknown"

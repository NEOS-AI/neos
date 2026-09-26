from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import jsonschema
from jsonschema.exceptions import SchemaError, ValidationError

HANDOFF_TOOL_NAME = "handoff.v1"

ALLOWED_TARGETS: frozenset[str] = frozenset(
    {
        "pitch-agent",
        "market-researcher",
        "earnings-reviewer",
        "meeting-prep-agent",
        "model-builder",
        "gl-reconciler",
        "kyc-screener",
        "valuation-reviewer",
        "month-end-closer",
        "statement-auditor",
    }
)

ALLOWED_EDGES: frozenset[tuple[str, str]] = frozenset(
    {
        ("pitch-agent", "model-builder"),
        ("earnings-reviewer", "model-builder"),
        ("market-researcher", "model-builder"),
        ("gl-reconciler", "month-end-closer"),
        ("valuation-reviewer", "gl-reconciler"),
    }
)

HANDOFF_INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["target", "event"],
    "properties": {
        "target": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": r"^[A-Za-z0-9_-]+$",
        },
        "event": {"type": "string", "minLength": 1, "maxLength": 2000},
        "context_ref": {
            "type": "string",
            "maxLength": 256,
            "pattern": r"^[A-Za-z0-9 ._/:#-]+$",
        },
    },
}

_SCHEMA_INVALID: dict[str, object] = {
    "ok": False,
    "error": "policy_schema_invalid",
}
_HANDOFF_DENIED: dict[str, object] = {
    "ok": False,
    "error": "policy_handoff_denied",
}


@dataclass(frozen=True, slots=True)
class HandoffCommand:
    from_slug: str
    target: str
    event: str
    context_ref: str | None


def validate_handoff(
    from_slug: str, payload: Mapping[str, object]
) -> HandoffCommand | Mapping[str, object]:
    instance = dict(payload)
    try:
        jsonschema.validate(instance=instance, schema=HANDOFF_INPUT_SCHEMA)
    except (ValidationError, SchemaError):
        return dict(_SCHEMA_INVALID)
    target = instance.get("target")
    event = instance.get("event")
    if not isinstance(target, str) or not isinstance(event, str):
        return dict(_SCHEMA_INVALID)
    context_ref = instance.get("context_ref")
    if context_ref is not None and not isinstance(context_ref, str):
        return dict(_SCHEMA_INVALID)
    if target not in ALLOWED_TARGETS or (from_slug, target) not in ALLOWED_EDGES:
        return dict(_HANDOFF_DENIED)
    return HandoffCommand(
        from_slug=from_slug,
        target=target,
        event=event,
        context_ref=context_ref if isinstance(context_ref, str) else None,
    )

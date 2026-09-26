from __future__ import annotations

import json
import re
from typing import Any

import jsonschema
from jsonschema.exceptions import SchemaError, ValidationError

_MAX_SERIALIZED_BYTES = 32768
_BIDI_OVERRIDES = frozenset(
    {
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
    }
)
_FENCE = re.compile(r"\A```(?:json)?\r?\n(.*)\r?\n```\Z", re.DOTALL)


class FoldRefused(ValueError):
    def __init__(self) -> None:
        super().__init__("schema_invalid")
        self.code = "schema_invalid"


READER_SCHEMAS: dict[str, dict] = {
    "univer-reader": {
        "type": "object",
        "required": ["unit_id", "kind", "sheets"],
        "additionalProperties": False,
        "properties": {
            "unit_id": {"type": "string", "maxLength": 64, "pattern": r"^[A-Za-z0-9_-]+$"},
            "kind": {"enum": ["sheet", "doc"]},
            "sheets": {
                "type": "array",
                "maxItems": 64,
                "items": {
                    "type": "object",
                    "required": ["name", "range", "preview"],
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string", "maxLength": 64, "pattern": r"^[A-Za-z0-9 ._-]+$"},
                        "range": {"type": "string", "maxLength": 32, "pattern": r"^[A-Za-z]+[0-9]+(:[A-Za-z]+[0-9]+)?$"},
                        "preview": {"type": "string", "maxLength": 2000},
                    },
                },
            },
        },
    },
    "univer-formula": {
        "type": "object",
        "required": ["unit_id", "wait_status", "error_count"],
        "additionalProperties": False,
        "properties": {
            "unit_id": {
                "type": "string",
                "maxLength": 64,
                "pattern": r"^[A-Za-z0-9_-]+$",
            },
            "wait_status": {"enum": ["applied", "timeout", "skipped"]},
            "error_count": {"type": "integer"},
            "errors": {
                "type": "array",
                "maxItems": 200,
                "items": {
                    "type": "object",
                    "required": ["code", "a1"],
                    "additionalProperties": False,
                    "properties": {
                        "code": {
                            "enum": [
                                "#DIV/0!",
                                "#NAME?",
                                "#VALUE!",
                                "#NUM!",
                                "#N/A",
                                "#CYCLE!",
                                "#REF!",
                                "#SPILL!",
                                "#CALC!",
                                "#ERROR!",
                                "#GETTING_DATA",
                                "#NULL!",
                            ]
                        },
                        "a1": {
                            "type": "string",
                            "maxLength": 32,
                            "pattern": r"^[A-Za-z0-9:$]+$",
                        },
                        "sheet": {
                            "type": "string",
                            "maxLength": 64,
                            "pattern": r"^[A-Za-z0-9 ._()-]+$",
                        },
                    },
                },
            },
        },
    },
}


def validate_child_fold(spec_name: str, text: str) -> dict:
    schema = READER_SCHEMAS.get(spec_name)
    if schema is None:
        return {"text": text}
    payload = _parse_fold_json(text)
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except (ValidationError, SchemaError) as exc:
        raise FoldRefused() from exc
    _refuse_oversized_or_hostile(payload)
    return payload


def _parse_fold_json(text: str) -> dict:
    body = text.strip()
    if body.startswith("```"):
        match = _FENCE.fullmatch(body)
        if match is None:
            raise FoldRefused()
        body = match.group(1)
    try:
        instance = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FoldRefused() from exc
    if not isinstance(instance, dict):
        raise FoldRefused()
    return instance


def _refuse_oversized_or_hostile(instance: dict) -> None:
    serialized = json.dumps(instance)
    if len(serialized.encode("utf-8")) > _MAX_SERIALIZED_BYTES:
        raise FoldRefused()
    if "\0" in serialized or _contains_forbidden(instance):
        raise FoldRefused()


def _contains_forbidden(value: Any) -> bool:
    if isinstance(value, str):
        return "\0" in value or any(ch in value for ch in _BIDI_OVERRIDES)
    if isinstance(value, dict):
        return any(
            _contains_forbidden(key) or _contains_forbidden(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden(item) for item in value)
    return False

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
    "gl-reconciler-reader": {
        "type": "object",
        "required": ["asset_class", "status", "breaks"],
        "additionalProperties": False,
        "properties": {
            "asset_class": {
                "type": "string",
                "maxLength": 32,
                "pattern": r"^[A-Za-z0-9_-]+$",
            },
            "status": {"enum": ["clean", "breaks_found", "error"]},
            "breaks": {
                "type": "array",
                "maxItems": 500,
                "items": {
                    "type": "object",
                    "required": ["account", "gl_balance", "sub_balance", "variance"],
                    "additionalProperties": False,
                    "properties": {
                        "account": {
                            "type": "string",
                            "maxLength": 64,
                            "pattern": r"^[A-Za-z0-9._:-]+$",
                        },
                        "gl_balance": {"type": "number"},
                        "sub_balance": {"type": "number"},
                        "variance": {"type": "number"},
                        "suspected_cause": {
                            "enum": [
                                "temporal_cutoff",
                                "system_drift",
                                "reclass",
                                "unknown",
                            ]
                        },
                        "evidence_refs": {
                            "type": "array",
                            "maxItems": 10,
                            "items": {
                                "type": "string",
                                "maxLength": 256,
                                "pattern": r"^[A-Za-z0-9 ._/:#-]+$",
                            },
                        },
                    },
                },
            },
        },
    },
    "kyc-doc-reader": {
        "type": "object",
        "required": ["packet_id", "entity", "ubos"],
        "additionalProperties": False,
        "properties": {
            "packet_id": {
                "type": "string",
                "maxLength": 32,
                "pattern": r"^[A-Za-z0-9_-]+$",
            },
            "entity": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "legal_name": {
                        "type": "string",
                        "maxLength": 200,
                        "pattern": r"^[A-Za-z0-9 .,&_/-]+$",
                    },
                    "country": {
                        "type": "string",
                        "maxLength": 2,
                        "pattern": r"^[A-Z]{2}$",
                    },
                },
            },
            "ubos": {
                "type": "array",
                "maxItems": 100,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {
                            "type": "string",
                            "maxLength": 200,
                            "pattern": r"^[A-Za-z0-9 .,'_-]+$",
                        },
                        "pct": {"type": "number"},
                    },
                },
            },
        },
    },
    "earnings-transcript-reader": {
        "type": "object",
        "required": ["ticker", "period", "actuals"],
        "additionalProperties": False,
        "properties": {
            "ticker": {
                "type": "string",
                "maxLength": 12,
                "pattern": r"^[A-Z.]+$",
            },
            "period": {
                "type": "string",
                "maxLength": 16,
                "pattern": r"^[A-Za-z0-9_-]+$",
            },
            "actuals": {
                "type": "object",
                "additionalProperties": {"type": "number"},
            },
            "guidance_notes": {
                "type": "array",
                "maxItems": 50,
                "items": {
                    "type": "string",
                    "maxLength": 256,
                    "pattern": r"^[A-Za-z0-9 .,%$()_/:-]+$",
                },
            },
        },
    },
    "market-sector-reader": {
        "type": "object",
        "required": ["sector", "facts"],
        "additionalProperties": False,
        "properties": {
            "sector": {
                "type": "string",
                "maxLength": 64,
                "pattern": r"^[A-Za-z0-9 &/._-]+$",
            },
            "facts": {
                "type": "array",
                "maxItems": 100,
                "items": {
                    "type": "object",
                    "required": ["claim", "source"],
                    "additionalProperties": False,
                    "properties": {
                        "claim": {
                            "type": "string",
                            "maxLength": 256,
                            "pattern": r"^[A-Za-z0-9 .,%$()_/&:-]+$",
                        },
                        "source": {
                            "type": "string",
                            "maxLength": 128,
                            "pattern": r"^[A-Za-z0-9 .,_/:-]+$",
                        },
                    },
                },
            },
        },
    },
    "briefing-news-reader": {
        "type": "object",
        "required": ["items"],
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "maxItems": 50,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "headline": {
                            "type": "string",
                            "maxLength": 200,
                            "pattern": r"^[A-Za-z0-9 .,%$()_/:-]+$",
                        },
                        "source": {
                            "type": "string",
                            "maxLength": 64,
                            "pattern": r"^[A-Za-z0-9 ._/:-]+$",
                        },
                    },
                },
            },
        },
    },
    "close-ledger-reader": {
        "type": "object",
        "required": ["entity", "period", "support"],
        "additionalProperties": False,
        "properties": {
            "entity": {
                "type": "string",
                "maxLength": 32,
                "pattern": r"^[A-Za-z0-9_-]+$",
            },
            "period": {
                "type": "string",
                "maxLength": 7,
                "pattern": r"^[0-9]{4}-[0-9]{2}$",
            },
            "support": {
                "type": "array",
                "maxItems": 500,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "ref": {
                            "type": "string",
                            "maxLength": 64,
                            "pattern": r"^[A-Za-z0-9 ._/:-]+$",
                        },
                        "amount": {"type": "number"},
                        "gl": {
                            "type": "string",
                            "maxLength": 32,
                            "pattern": r"^[A-Za-z0-9._-]+$",
                        },
                    },
                },
            },
        },
    },
    "stmt-statement-reader": {
        "type": "object",
        "required": ["batch_id", "lps"],
        "additionalProperties": False,
        "properties": {
            "batch_id": {
                "type": "string",
                "maxLength": 64,
                "pattern": r"^[A-Za-z0-9_-]+$",
            },
            "lps": {
                "type": "array",
                "maxItems": 2000,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "lp_id": {
                            "type": "string",
                            "maxLength": 32,
                            "pattern": r"^[A-Za-z0-9_-]+$",
                        },
                        "nav": {"type": "number"},
                        "contrib": {"type": "number"},
                        "distrib": {"type": "number"},
                    },
                },
            },
        },
    },
    "valuation-package-reader": {
        "type": "object",
        "required": ["fund", "as_of", "portcos"],
        "additionalProperties": False,
        "properties": {
            "fund": {
                "type": "string",
                "maxLength": 64,
                "pattern": r"^[A-Za-z0-9 ._-]+$",
            },
            "as_of": {
                "type": "string",
                "maxLength": 10,
                "pattern": r"^[0-9-]+$",
            },
            "portcos": {
                "type": "array",
                "maxItems": 500,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "portco_id": {
                            "type": "string",
                            "maxLength": 32,
                            "pattern": r"^[A-Za-z0-9_-]+$",
                        },
                        "reported_fv": {"type": "number"},
                        "method": {
                            "enum": [
                                "market_multiple",
                                "dcf",
                                "recent_round",
                                "cost",
                                "other",
                            ]
                        },
                    },
                },
            },
        },
    },
    "pitch-researcher": {
        "type": "object",
        "required": ["target", "comps"],
        "additionalProperties": False,
        "properties": {
            "target": {
                "type": "string",
                "maxLength": 64,
                "pattern": r"^[A-Za-z0-9 ._-]+$",
            },
            "comps": {
                "type": "array",
                "maxItems": 30,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "maxLength": 12,
                            "pattern": r"^[A-Z.]+$",
                        },
                        "metric": {
                            "type": "string",
                            "maxLength": 32,
                            "pattern": r"^[A-Za-z0-9 /_-]+$",
                        },
                        "value": {"type": "number"},
                    },
                },
            },
            "precedents": {
                "type": "array",
                "maxItems": 30,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "target": {
                            "type": "string",
                            "maxLength": 64,
                            "pattern": r"^[A-Za-z0-9 ._-]+$",
                        },
                        "acquirer": {
                            "type": "string",
                            "maxLength": 64,
                            "pattern": r"^[A-Za-z0-9 ._-]+$",
                        },
                        "ev": {"type": "number"},
                        "multiple": {"type": "number"},
                    },
                },
            },
        },
    },
    "model-data-puller": {
        "type": "object",
        "required": ["ticker", "historicals"],
        "additionalProperties": False,
        "properties": {
            "ticker": {
                "type": "string",
                "maxLength": 12,
                "pattern": r"^[A-Z.]+$",
            },
            "historicals": {
                "type": "object",
                "additionalProperties": {"type": "number"},
            },
            "consensus": {
                "type": "object",
                "additionalProperties": {"type": "number"},
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

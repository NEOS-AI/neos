"""세션 상태 코덱 -- `AgentState` 값을 JSON 으로, 다시 원래 타입으로 (spec 2026-10-13 §4.3).

옛 PostgreSQL 체크포인터는 모르는 객체를 문자열로 바꿔 저장했다 -- `SearchResult` 가 dict 로
돌아왔고 2턴째 노드의 `r.title` 에서야 드러났다(R2). 여기서는 등록된 타입만 태그를 달아 저장하고
나머지는 **실패한다**. 저장 실패는 턴을 막지 않는다(호출자가 경고와 카운터로 처리한다).

태그 모양: `{"__t": <종류>, ...}`. 사용자 dict 가 우연히 `__t` 키를 가지면 `{"__t": "dict", "v": …}`
로 감싸 구별한다.
"""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from neos.workflow.errors import ErrorCategory, WorkflowError
from neos.workflow.metrics import PerformanceMetrics
from neos.workflow.state import AnalysisResult, GenerationResult, SearchResult

_TAG = "__t"

_DATACLASSES: dict[str, type] = {
    cls.__name__: cls
    for cls in (SearchResult, AnalysisResult, GenerationResult, WorkflowError, PerformanceMetrics)
}
_ENUMS: dict[str, type[enum.Enum]] = {cls.__name__: cls for cls in (ErrorCategory,)}

REGISTERED_TYPES: frozenset[type] = frozenset(_DATACLASSES.values()) | frozenset(_ENUMS.values())


class CodecError(TypeError):
    pass


def encode_state(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _encode(value, key)
        for key, value in state.items()
        if not str(key).startswith("_")
    }


def decode_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _decode(value, key) for key, value in payload.items()}


def _encode(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        name = type(value).__name__
        if _ENUMS.get(name) is not type(value):
            raise CodecError(f"{path}: 등록되지 않은 enum {type(value)!r}")
        return {_TAG: "enum", "c": name, "v": value.value}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        name = type(value).__name__
        if _DATACLASSES.get(name) is not type(value):
            raise CodecError(f"{path}: 등록되지 않은 dataclass {type(value)!r}")
        return {
            _TAG: "dc",
            "c": name,
            "v": {
                field.name: _encode(getattr(value, field.name), f"{path}.{field.name}")
                for field in dataclasses.fields(value)
            },
        }
    if isinstance(value, datetime):
        return {_TAG: "datetime", "v": value.isoformat()}
    if isinstance(value, Decimal):
        return {_TAG: "decimal", "v": str(value)}
    if isinstance(value, tuple):
        return {_TAG: "tuple", "v": [_encode(item, f"{path}[{i}]") for i, item in enumerate(value)]}
    if isinstance(value, list):
        return [_encode(item, f"{path}[{i}]") for i, item in enumerate(value)]
    if isinstance(value, Mapping):
        encoded: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CodecError(f"{path}: 문자열이 아닌 dict 키 {key!r}")
            encoded[key] = _encode(item, f"{path}.{key}")
        if _TAG in encoded:
            return {_TAG: "dict", "v": encoded}
        return encoded
    raise CodecError(f"{path}: 등록되지 않은 타입 {type(value)!r}")


def _decode(value: Any, path: str) -> Any:
    if isinstance(value, list):
        return [_decode(item, f"{path}[{i}]") for i, item in enumerate(value)]
    if not isinstance(value, Mapping):
        return value
    tag = value.get(_TAG)
    if tag is None:
        return {key: _decode(item, f"{path}.{key}") for key, item in value.items()}
    if tag == "dict":
        return {key: _decode(item, f"{path}.{key}") for key, item in value["v"].items()}
    if tag == "datetime":
        return datetime.fromisoformat(value["v"])
    if tag == "decimal":
        return Decimal(value["v"])
    if tag == "tuple":
        return tuple(_decode(item, f"{path}[{i}]") for i, item in enumerate(value["v"]))
    if tag == "enum":
        cls = _ENUMS.get(value["c"])
        if cls is None:
            raise CodecError(f"{path}: 모르는 enum {value['c']!r}")
        return cls(value["v"])
    if tag == "dc":
        cls = _DATACLASSES.get(value["c"])
        if cls is None:
            raise CodecError(f"{path}: 모르는 dataclass {value['c']!r}")
        fields = {key: _decode(item, f"{path}.{key}") for key, item in value["v"].items()}
        instance = cls.__new__(cls)
        for key, item in fields.items():
            object.__setattr__(instance, key, item)
        return instance
    raise CodecError(f"{path}: 모르는 태그 {tag!r}")

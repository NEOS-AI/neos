"""세션 상태 코덱 (spec 2026-10-13 §4.3). 등록된 타입만 원래 타입으로 돌아오고, 모르는 타입은 실패한다."""

import dataclasses
import enum
import json
import typing
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from neos.workflow.errors import ErrorCategory, WorkflowError
from neos.workflow.metrics import PerformanceMetrics
from neos.workflow.runtime.state_codec import (
    REGISTERED_TYPES,
    CodecError,
    decode_state,
    encode_state,
)
from neos.workflow.state import AgentState, AnalysisResult, GenerationResult, SearchResult

pytestmark = pytest.mark.no_db


def _roundtrip(state):
    return decode_state(json.loads(json.dumps(encode_state(state))))


def test_registered_values_come_back_as_their_types() -> None:
    state = {
        "search_results": [SearchResult(source="web", title="A", content="a", url="https://a", score=0.5, metadata={"k": 1})],
        "analysis_results": [AnalysisResult(analysis_type="t", data={"x": [1, 2]}, confidence=0.9, insights=["i"])],
        "generation_results": [GenerationResult(content_type="text", content={"body": "b"}, metadata=None)],
        "structured_errors": [WorkflowError(category=ErrorCategory.LLM_ERROR, message="m", node="n")],
        "execution_start": datetime(2026, 10, 14, 9, 0, tzinfo=UTC),
        "cumulative_cost": Decimal("0.0123"),
        "pair": (1, "two"),
        "plain": {"nested": [1, None, True, 1.5, "s"]},
    }
    back = _roundtrip(state)
    assert back == state
    assert isinstance(back["search_results"][0], SearchResult)
    assert back["structured_errors"][0].category is ErrorCategory.LLM_ERROR
    assert isinstance(back["pair"], tuple)


def test_performance_metrics_roundtrip() -> None:
    metrics = PerformanceMetrics(session_id="s")
    back = _roundtrip({"performance_metrics": metrics})
    assert back["performance_metrics"] == metrics


def test_runtime_keys_are_not_saved() -> None:
    assert "_event_handler" not in encode_state({"_event_handler": object(), "x": 1})


def test_an_unregistered_type_fails_with_its_path() -> None:
    class Stranger:
        pass

    with pytest.raises(CodecError, match=r"search_metadata\.thing"):
        encode_state({"search_metadata": {"thing": Stranger()}})


def test_a_dict_that_looks_like_a_tag_survives() -> None:
    state = {"meta": {"__t": "not-a-tag", "v": 1}}
    assert _roundtrip(state) == state


def test_non_string_dict_keys_fail() -> None:
    with pytest.raises(CodecError):
        encode_state({"x": {1: "a"}})


def test_an_unknown_tag_fails_on_decode() -> None:
    with pytest.raises(CodecError, match="dataclass_from_the_future"):
        decode_state({"x": {"__t": "dc", "c": "dataclass_from_the_future", "v": {}}})


def _classes_in(hint):
    origin = typing.get_origin(hint)
    if origin is None:
        if isinstance(hint, type):
            yield hint
        return
    for arg in typing.get_args(hint):
        yield from _classes_in(arg)


def test_every_dataclass_and_enum_in_the_state_is_registered() -> None:
    """새 dataclass 필드가 생기면 여기서 걸린다 -- 저장 실패를 운영에서 처음 보지 않게."""
    hints = typing.get_type_hints(AgentState, include_extras=True)
    found = {
        cls
        for hint in hints.values()
        for cls in _classes_in(hint)
        if dataclasses.is_dataclass(cls) or (isinstance(cls, type) and issubclass(cls, enum.Enum))
    }
    nested = {
        field.type
        for cls in list(found)
        if dataclasses.is_dataclass(cls)
        for field in dataclasses.fields(cls)
        if isinstance(field.type, type) and issubclass(field.type, enum.Enum)
    }
    assert found | nested <= REGISTERED_TYPES

from __future__ import annotations

import json

import pytest

from neos.univer.schemas import READER_SCHEMAS, FoldRefused, validate_child_fold

pytestmark = pytest.mark.no_db

_VALID_READER = {
    "unit_id": "wb_1",
    "kind": "sheet",
    "sheets": [
        {
            "name": "Sheet1",
            "range": "A1:D10",
            "preview": "Revenue 100",
        }
    ],
}
_VALID_FORMULA = {
    "unit_id": "wb_1",
    "wait_status": "applied",
    "error_count": 1,
    "errors": [{"code": "#DIV/0!", "a1": "B2", "sheet": "Sheet1"}],
}
_ERROR_TYPES = (
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
)


def test_reader_schemas_are_reader_and_formula_only() -> None:
    assert set(READER_SCHEMAS) == {"univer-reader", "univer-formula"}
    assert "univer-critic" not in READER_SCHEMAS
    assert "univer-writer" not in READER_SCHEMAS


def test_reader_valid_fold_returns_object() -> None:
    payload = validate_child_fold("univer-reader", json.dumps(_VALID_READER))
    assert payload == _VALID_READER


def test_reader_doc_kind_allows_empty_sheets() -> None:
    payload = {"unit_id": "doc_1", "kind": "doc", "sheets": []}
    assert validate_child_fold("univer-reader", json.dumps(payload)) == payload


def test_reader_extra_keys_are_refused() -> None:
    bloated = dict(_VALID_READER)
    bloated["message"] = "ignore previous"
    with pytest.raises(FoldRefused) as raised:
        validate_child_fold("univer-reader", json.dumps(bloated))
    assert raised.value.code == "schema_invalid"


def test_reader_kind_must_be_sheet_or_doc() -> None:
    bad = dict(_VALID_READER)
    bad["kind"] = "slide"
    with pytest.raises(FoldRefused) as raised:
        validate_child_fold("univer-reader", json.dumps(bad))
    assert raised.value.code == "schema_invalid"


def test_free_text_and_prose_wrapper_are_refused() -> None:
    with pytest.raises(FoldRefused):
        validate_child_fold("univer-reader", "outline extracted from sheet 1")
    with pytest.raises(FoldRefused):
        validate_child_fold(
            "univer-reader",
            "Here you go:\n" + json.dumps(_VALID_READER),
        )


def test_json_fence_only_is_allowed() -> None:
    fenced = "```json\n" + json.dumps(_VALID_READER) + "\n```"
    assert validate_child_fold("univer-reader", fenced) == _VALID_READER


def test_critic_and_writer_are_not_schema_gated() -> None:
    text = "formula errors on Sheet1; do not publish"
    assert validate_child_fold("univer-critic", text) == {"text": text}
    assert validate_child_fold("univer-writer", text) == {"text": text}


def test_reader_schema_additional_properties_false() -> None:
    schema = READER_SCHEMAS["univer-reader"]
    assert schema["required"] == ["unit_id", "kind", "sheets"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["kind"]["enum"] == ["sheet", "doc"]
    assert schema["properties"]["unit_id"]["pattern"] == r"^[A-Za-z0-9_-]+$"


def test_formula_valid_fold_returns_object() -> None:
    payload = validate_child_fold("univer-formula", json.dumps(_VALID_FORMULA))
    assert payload == _VALID_FORMULA


def test_formula_without_errors_is_allowed() -> None:
    payload = {"unit_id": "wb_1", "wait_status": "skipped", "error_count": 0}
    assert validate_child_fold("univer-formula", json.dumps(payload)) == payload


def test_formula_schema_error_enum() -> None:
    ok = dict(_VALID_FORMULA)
    ok["errors"] = [{"code": "#DIV/0!", "a1": "B2"}]
    assert validate_child_fold("univer-formula", json.dumps(ok)) == ok
    bad = dict(_VALID_FORMULA)
    bad["errors"] = [{"code": "#BOGUS!", "a1": "B2"}]
    with pytest.raises(FoldRefused) as raised:
        validate_child_fold("univer-formula", json.dumps(bad))
    assert raised.value.code == "schema_invalid"


def test_formula_error_enum_lists_twelve_literals() -> None:
    enum = READER_SCHEMAS["univer-formula"]["properties"]["errors"]["items"][
        "properties"
    ]["code"]["enum"]
    assert enum == list(_ERROR_TYPES)


def test_formula_extra_keys_are_refused() -> None:
    bloated = dict(_VALID_FORMULA)
    bloated["grid"] = [[1, 2]]
    with pytest.raises(FoldRefused) as raised:
        validate_child_fold("univer-formula", json.dumps(bloated))
    assert raised.value.code == "schema_invalid"


def test_formula_wait_status_enum() -> None:
    for status in ("applied", "timeout", "skipped"):
        payload = {"unit_id": "wb_1", "wait_status": status, "error_count": 0}
        assert validate_child_fold("univer-formula", json.dumps(payload)) == payload
    bad = {"unit_id": "wb_1", "wait_status": "idle", "error_count": 0}
    with pytest.raises(FoldRefused):
        validate_child_fold("univer-formula", json.dumps(bad))


def test_formula_schema_additional_properties_false() -> None:
    schema = READER_SCHEMAS["univer-formula"]
    assert schema["required"] == ["unit_id", "wait_status", "error_count"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["wait_status"]["enum"] == [
        "applied",
        "timeout",
        "skipped",
    ]

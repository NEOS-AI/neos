"""Reflection prompt render and proposal parse. No model client."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from neos.gepa_opt.reflect import (
    REFLECTION_TEMPLATE,
    ParseSkip,
    cap_side_info,
    parse_proposal,
    render_reflection,
)

pytestmark = pytest.mark.no_db

_REFLECT_PY = Path(__file__).resolve().parents[2] / "neos" / "gepa_opt" / "reflect.py"
_FORBIDDEN_IMPORT = re.compile(
    r"^(?:import|from) (?:gepa|litellm|pickle|cloudpickle|bwrap)\b",
    re.MULTILINE,
)


def test_render_replaces_placeholders_and_sorts_json_keys():
    assert "<curr_param>" in REFLECTION_TEMPLATE
    assert "<side_info>" in REFLECTION_TEMPLATE
    assert "Provide the new instructions within ``` blocks." in REFLECTION_TEMPLATE
    rendered = render_reflection("CURR-PARAM", {"b": 1, "a": 2})
    assert "CURR-PARAM" in rendered
    assert "<curr_param>" not in rendered
    assert "<side_info>" not in rendered
    assert '{"a": 2, "b": 1}' in rendered
    ordered = render_reflection("KEEP", {"k": "<curr_param>"})
    assert ordered.count("<curr_param>") == 1
    assert ordered.count("KEEP") == 1
    injected = render_reflection("X <side_info> Y", {"z": 1})
    assert "<side_info>" not in injected
    assert injected.count('{"z": 1}') == 2


def test_fenced_body_with_language_tag_drops_tag_line():
    text = "preamble\n```python\nbe concise\nstill here\n```\ntrailer"
    assert parse_proposal(text, None) == "be concise\nstill here"


def test_unfenced_text_is_returned_stripped():
    assert parse_proposal("  \n  keep this  \n", "stop") == "keep this"


def test_unpaired_leading_fence_is_stripped():
    assert parse_proposal("```python\nbe concise\n", None) == "be concise"
    assert parse_proposal("body stays\n```\n", None) == "body stays"


def test_finish_reason_length_without_fence_returns_parse_skip():
    result = parse_proposal("partial output", "length")
    assert isinstance(result, ParseSkip)
    assert not isinstance(result, BaseException)
    assert isinstance(parse_proposal("partial output", "max_tokens"), ParseSkip)
    think = parse_proposal("<think>\nstill thinking", "stop")
    assert isinstance(think, ParseSkip)


def test_complete_fence_with_unclosed_think_returns_body():
    text = "<think>\nreasoning never closes\n```markdown\nnew instructions\n```"
    assert parse_proposal(text, "length") == "new instructions"
    assert not isinstance(parse_proposal(text, "length"), ParseSkip)


def test_cap_side_info_over_8192_returns_truncated_marker():
    small = {"b": 1, "a": 2}
    assert cap_side_info(small) == small
    assert len(json.dumps(small, sort_keys=True).encode("utf-8")) <= 8192
    wide = {"keep": "no", "blob": "x" * 9000}
    encoded = json.dumps(wide, sort_keys=True).encode("utf-8")
    assert len(encoded) > 8192
    assert cap_side_info(wide) == {"truncated": True}


def test_reflect_source_has_no_forbidden_imports():
    source = _REFLECT_PY.read_text(encoding="utf-8")
    assert _FORBIDDEN_IMPORT.search(source) is None

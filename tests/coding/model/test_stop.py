import pytest

from neos.coding.model.stop import normalize_stop_reason


@pytest.mark.parametrize(
    ("raw", "has_tools", "expected"),
    [
        ("stop", False, "end_turn"),
        ("end_turn", False, "end_turn"),
        ("tool_calls", False, "tool_use"),
        ("length", False, "max_tokens"),
        ("max_tokens", False, "max_tokens"),
        ("stop", True, "tool_use"),
        (None, False, "unknown"),
        ("content_filter", False, "unknown"),
        ("SAFETY", False, "unknown"),
        ("1", False, "unknown"),
    ],
)
def test_vendor_finish_reasons_collapse_to_loop_vocabulary(
    raw, has_tools, expected
) -> None:
    assert normalize_stop_reason(raw, has_tool_calls=has_tools) == expected

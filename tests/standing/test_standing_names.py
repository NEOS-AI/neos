"""Q13 decision 3: names have no length limit and do not repeat within an owner.

Duplicates are compared ignoring case and surrounding whitespace -- calling an
agent by name in a channel must not find two.
"""

from __future__ import annotations

import pytest

from neos.standing.models import agent_name_key, normalize_agent_name

pytestmark = pytest.mark.no_db


def test_the_stored_name_is_trimmed() -> None:
    assert normalize_agent_name("  Dot  ") == "Dot"


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_an_empty_name_is_refused(name: str) -> None:
    with pytest.raises(ValueError):
        normalize_agent_name(name)


def test_there_is_no_length_limit() -> None:
    long = "d" * 10_000

    assert normalize_agent_name(long) == long


def test_case_and_surrounding_space_do_not_make_a_new_name() -> None:
    assert agent_name_key("Dot") == agent_name_key("  dOT ")
    assert agent_name_key("Dot") != agent_name_key("Dots")

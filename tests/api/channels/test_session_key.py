import pytest

from neos.api.channels.session_key import build_session_key

pytestmark = pytest.mark.no_db


def test_session_key_uses_v2_prefix_and_defaults() -> None:
    assert build_session_key("slack", "T1", "C1", "111.222") == "v2:slack:T1:C1:111.222"
    assert build_session_key("discord", None, "99") == "v2:discord:dm:99:-"
    assert build_session_key("telegram", "", "42", "") == "v2:telegram:dm:42:-"


def test_session_key_replaces_colons() -> None:
    assert build_session_key("slack", "T:1", "C:2", "1:2") == "v2:slack:T_1:C_2:1_2"

from __future__ import annotations

import pytest

from neos.coding.redact import redact_sensitive

pytestmark = pytest.mark.no_db


def test_redact_sensitive_replaces_openai_like_prefix_inside_string_values() -> None:
    token = "sk-" + ("a" * 20)
    redacted = redact_sensitive({"preview": f"token {token}"})
    assert redacted["preview"] == "token <redacted>"
    assert token not in redacted["preview"]


def test_redact_sensitive_still_masks_secret_keys_wholly() -> None:
    assert redact_sensitive({"API_TOKEN": "x"}) == {"API_TOKEN": "<redacted>"}
    assert redact_sensitive({"API_TOKEN": "sk-" + ("b" * 20)}) == {
        "API_TOKEN": "<redacted>"
    }


def test_redact_sensitive_covers_well_known_secret_prefixes() -> None:
    samples = {
        "github_classic": "header ghp_abc123DEF",
        "github_oauth": "gho_oauthToken1",
        "github_pat": "github_pat_fineGrained1",
        "aws": "AKIA" + ("A" * 16),
        "slack_bot": "xoxb-1-abc",
        "slack_user": "xoxp-2-def",
        "slack_app": "xoxa-3-ghi",
        "xai": "xai-secretvalue",
        "bearer": "Authorization: Bearer abc.def-ghi",
    }
    redacted = redact_sensitive(samples)
    assert redacted["github_classic"] == "header <redacted>"
    assert redacted["github_oauth"] == "<redacted>"
    assert redacted["github_pat"] == "<redacted>"
    assert redacted["aws"] == "<redacted>"
    assert redacted["slack_bot"] == "<redacted>"
    assert redacted["slack_user"] == "<redacted>"
    assert redacted["slack_app"] == "<redacted>"
    assert redacted["xai"] == "<redacted>"
    assert redacted["bearer"] == "Authorization: <redacted>"


def test_redact_sensitive_walks_lists_and_keeps_short_sk_prefix() -> None:
    short = "sk-short"
    long_token = "sk-" + ("c" * 20)
    redacted = redact_sensitive(
        {"items": [f"keep {short}", {"note": f"leak {long_token}"}]}
    )
    assert redacted["items"][0] == f"keep {short}"
    assert redacted["items"][1]["note"] == "leak <redacted>"


def test_redact_sensitive_still_clips_long_strings_after_value_redaction() -> None:
    token = "sk-" + ("d" * 20)
    redacted = redact_sensitive({"note": f"{token} " + ("x" * 400)})
    assert redacted["note"].startswith("<redacted> ")
    assert redacted["note"].endswith("…")
    assert len(redacted["note"]) == 401
    assert token not in redacted["note"]

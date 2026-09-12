from __future__ import annotations

import pytest

from neos.subagent.identity import (
    new_checkpoint_id,
    new_run_id,
    persist_payload,
    strip_channel_keys,
)


pytestmark = pytest.mark.no_db


def test_run_and_checkpoint_ids_use_sa_and_sc_prefixes() -> None:
    run_id = new_run_id()
    checkpoint_id = new_checkpoint_id()
    assert run_id.startswith("sa_")
    assert checkpoint_id.startswith("sc_")
    assert run_id != new_run_id()
    assert checkpoint_id != new_checkpoint_id()
    assert run_id[3:] and all(ch in "0123456789abcdef" for ch in run_id[3:])
    assert checkpoint_id[3:] and all(
        ch in "0123456789abcdef" for ch in checkpoint_id[3:]
    )


def test_strip_channel_keys_removes_nested_identity_fields() -> None:
    payload = {
        "goal": "inspect",
        "session_key": "sk_should_go",
        "nested": {
            "chat_id": "C123",
            "keep": "yes",
            "deeper": {"thread_id": "T1", "channel_id": "CH", "ok": 1},
        },
        "items": [
            {"session_key": "nope", "path": "README.md"},
            "plain",
        ],
    }
    stripped = strip_channel_keys(payload)
    assert stripped == {
        "goal": "inspect",
        "nested": {"keep": "yes", "deeper": {"ok": 1}},
        "items": [{"path": "README.md"}, "plain"],
    }
    assert "session_key" in payload


def test_strip_channel_keys_leaves_unrelated_keys() -> None:
    payload = {"parent_id": "ct_1", "spec": "explore", "model": "claude"}
    assert strip_channel_keys(payload) == payload
    assert strip_channel_keys("text") == "text"
    assert strip_channel_keys(3) == 3
    assert strip_channel_keys(None) is None


def test_strip_channel_keys_recurses_tuple_of_dicts() -> None:
    payload = (
        {"session_key": "sk_should_go", "keep": "yes"},
        {"chat_id": "C1", "ok": 1},
    )
    stripped = strip_channel_keys(payload)
    assert stripped == ({"keep": "yes"}, {"ok": 1})
    assert isinstance(stripped, tuple)
    assert payload[0]["session_key"] == "sk_should_go"


def test_persist_payload_strips_channel_keys_and_redacts_secrets() -> None:
    payload = {
        "goal": "inspect",
        "session_key": "sk_should_go",
        "api_key": "super-secret",
        "nested": {
            "chat_id": "C123",
            "token": "abc",
            "note": "token sk-abcdefghijklmnopqrstuvwxyz1234",
        },
    }
    persisted = persist_payload(payload)
    assert persisted == {
        "goal": "inspect",
        "api_key": "<redacted>",
        "nested": {
            "token": "<redacted>",
            "note": persist_payload("token sk-abcdefghijklmnopqrstuvwxyz1234"),
        },
    }
    assert "session_key" in payload
    assert payload["api_key"] == "super-secret"

from __future__ import annotations

import pytest

from tests.api.channels.test_gateway_router import _gateway, _message

pytestmark = pytest.mark.no_db


async def test_workflow_query_prefixes_platform_id_only_without_display_name(
    monkeypatch,
) -> None:
    gateway, workflow, _coding = _gateway(monkeypatch)
    await gateway.dispatch(_message("hello <@U_BOT>"))
    query = workflow.calls[0]["query"]
    assert query.startswith("[U_alice] ")
    assert "hello <@U_BOT>" in query
    assert "<@U_alice>" not in query


async def test_workflow_query_prefixes_neutralized_display_name(monkeypatch) -> None:
    gateway, workflow, _coding = _gateway(monkeypatch)
    message = _message("hello")
    message.metadata["slack_user_name"] = "Alice]\u202e\n<script>"
    await gateway.dispatch(message)
    query = workflow.calls[0]["query"]
    assert query.startswith("[Alice <script> | U_alice] ")
    assert query.count("[") == 1
    assert "] ignore" not in query
    assert "\u202e" not in query
    assert "\n" not in query.split("]", 1)[0]


async def test_code_prompt_prefixes_sender_and_does_not_invent_slack_mentions(
    monkeypatch,
) -> None:
    gateway, _workflow, coding = _gateway(monkeypatch)
    message = _message("<@U_BOT> /code fix the test")
    message.metadata["slack_user_name"] = "Alice"
    await gateway.dispatch(message)
    prompt = coding.started[0][1]
    assert prompt.startswith("[Alice | U_alice] ")
    assert prompt.endswith("fix the test")
    assert "<@" not in prompt or prompt.count("<@") == 1  # original bot mention stripped
    assert "<@U_alice>" not in prompt
    assert "<@Alice>" not in prompt


async def test_attachment_name_is_neutralized_in_workflow_and_code(monkeypatch) -> None:
    gateway, workflow, coding = _gateway(monkeypatch)
    chat = _message("see file")
    chat.metadata["attachments"] = [
        {"name": "bug\u202e\n.png", "content_type": "image/png", "data": b"x"}
    ]
    await gateway.dispatch(chat)
    assert "bug .png" in workflow.calls[0]["query"]
    assert "\u202e" not in workflow.calls[0]["query"]

    code = _message("<@U_BOT> /code inspect")
    code.metadata["attachments"] = [
        {"name": "shot\x00.txt", "content_type": "text/plain", "data": b"hi"}
    ]
    await gateway.dispatch(code)
    assert "shot.txt" in coding.started[0][1]
    assert "\x00" not in coding.started[0][1]

"""Per-turn /diff via the channel command/bridge. Not a workspace snapshot."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from neos.api.channels.commands import ChannelCommandKind, parse_channel_command
from neos.api.channels.turn_diff import format_turn_diff
from tests.api.channels.test_gateway_router import FakeCoding, _gateway, _message

pytestmark = pytest.mark.no_db


def test_parse_diff_is_a_channel_command() -> None:
    command = parse_channel_command("/diff")
    assert command.kind is ChannelCommandKind.DIFF
    assert command.rest == ""


def test_turn_diff_uses_last_model_tool_step_not_workspace_snapshot() -> None:
    snapshot = SimpleNamespace(
        task=SimpleNamespace(task_id="ct_1"),
        workspace=SimpleNamespace(
            changed_files=("src/old.py", "README.md", "src/app.py"),
        ),
        latest_checkpoint=SimpleNamespace(
            loop_state={
                "changed_files": ["src/old.py", "README.md", "src/app.py"],
                "transcript": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "write_file.v1",
                                "tool_call_id": "old",
                                "input": {"path": "src/old.py"},
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_call_id": "old",
                                "name": "write_file.v1",
                                "content": {"preview": "stale workspace file"},
                            }
                        ],
                    },
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "edit_file.v1",
                                "tool_call_id": "new",
                                "input": {
                                    "path": "src/app.py",
                                    "patch": "token sk-abcdefghijklmnopqrstuvwxyz",
                                },
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_call_id": "new",
                                "name": "edit_file.v1",
                                "content": {
                                    "preview": "api_key=sk-abcdefghijklmnopqrstuvwxyz"
                                },
                            }
                        ],
                    },
                ],
            }
        ),
    )

    text = format_turn_diff(snapshot)

    assert "src/app.py" in text
    assert "edit_file.v1" in text
    assert "src/old.py" not in text
    assert "README.md" not in text
    assert "sk-" not in text
    assert "<redacted>" in text


async def test_diff_command_uses_turn_dump_not_workspace_http(monkeypatch) -> None:
    class DiffCoding(FakeCoding):
        async def turn_diff(self, *, task_id: str, owner_id: str) -> str:
            del owner_id
            return f"{task_id} turn src/app.py edit_file.v1"

    gateway, workflow, _coding = _gateway(monkeypatch)
    gateway._coding = DiffCoding()
    await gateway.bind_session("sess-diff", "ct_1", "u_owner")

    reply = await gateway.dispatch(_message("/diff", "sess-diff"))

    assert "src/app.py" in reply
    assert "turn" in reply.lower() or "edit_file" in reply
    assert workflow.calls == []


async def test_diff_without_task_does_not_start_loop(monkeypatch) -> None:
    gateway, workflow, coding = _gateway(monkeypatch)
    reply = await gateway.dispatch(_message("/diff", "sess-no-diff"))
    assert reply == "No coding task in this thread."
    assert coding.started == []
    assert workflow.calls == []

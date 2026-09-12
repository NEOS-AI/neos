"""Slack Block Kit cards for channel coding replies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from neos.coding.domain.approvals import requires_approval_answers

ACTION_STOP = "neos_code_stop"
ACTION_STATUS = "neos_code_status"
ACTION_APPROVE = "neos_code_approve"
ACTION_DENY = "neos_code_deny"
ACTION_PREFIX = "neos_code_"

_STARTED = re.compile(r"^Started coding task (\S+)$")
_STOPPED = re.compile(r"^Stopped (\S+)$")
_APPROVAL = re.compile(r"^(\S+) (approved|denied)$")
_STATUS = re.compile(r"^(\S+) (\S+)$")
_WAITING = re.compile(r"^(\S+) waiting_approval(?: (\S+)(?: (\S+))?)?$")

_TEXT_ONLY = frozenset(
    {
        "No pending coding approval.",
        "No coding task in this thread.",
        "Usage: /code <task>",
        "Coding invoke is disabled.",
        "Coding owner is not configured.",
        "Owner is not configured.",
    }
)

_KNOWN_STATUSES = frozenset(
    {
        "draft",
        "queued",
        "provisioning",
        "cloning",
        "ready",
        "running",
        "waiting_approval",
        "waiting_user",
        "pausing",
        "paused",
        "cancelling",
        "completed",
        "failed",
        "cancelled",
        "expired",
        "archived",
    }
)
_TERMINAL_STATUSES = frozenset({"cancelled", "completed", "failed"})

_ACTION_COMMANDS = {
    ACTION_STOP: "/stop",
    ACTION_STATUS: "/status",
    ACTION_APPROVE: "/approve",
    ACTION_DENY: "/deny",
}


@dataclass(frozen=True, slots=True)
class CodingAction:
    label: str
    action_id: str
    value: str
    style: str | None = None


def started_task_id(text: str) -> str | None:
    match = _STARTED.fullmatch((text or "").strip())
    return match.group(1) if match else None


def command_for_action(action_id: str, value: str = "") -> str | None:
    command = _ACTION_COMMANDS.get(action_id)
    if command is None:
        return None
    if action_id in {ACTION_APPROVE, ACTION_DENY} and value:
        approval_id = value.rsplit(":", 1)[-1]
        return f"{command} {approval_id}"
    return command


def parse_action_payload(data: str) -> tuple[str, str] | None:
    raw = (data or "").strip()
    if not raw.startswith(ACTION_PREFIX):
        return None
    action_id, sep, value = raw.partition(":")
    if not sep or action_id not in _ACTION_COMMANDS:
        return None
    return action_id, value


def coding_actions(text: str) -> list[CodingAction]:
    blocks = coding_blocks(text)
    if not blocks:
        return []
    actions: list[CodingAction] = []
    for block in blocks:
        if block.get("type") != "actions":
            continue
        for element in block.get("elements") or []:
            action_id = str(element.get("action_id") or "")
            if not action_id:
                continue
            label = ""
            label_obj = element.get("text")
            if isinstance(label_obj, dict):
                label = str(label_obj.get("text") or "")
            actions.append(
                CodingAction(
                    label=label or action_id,
                    action_id=action_id,
                    value=str(element.get("value") or ""),
                    style=element.get("style"),
                )
            )
    return actions


def telegram_inline_keyboard(text: str) -> dict[str, Any] | None:
    actions = coding_actions(text)
    if not actions:
        return None
    return {
        "inline_keyboard": [
            [
                {
                    "text": action.label,
                    "callback_data": f"{action.action_id}:{action.value}",
                }
                for action in actions
            ]
        ]
    }


def discord_buttons(text: str) -> list[dict[str, str]] | None:
    actions = coding_actions(text)
    if not actions:
        return None
    return [
        {
            "label": action.label,
            "custom_id": f"{action.action_id}:{action.value}",
            "style": action.style or "",
        }
        for action in actions
    ]


def coding_blocks(text: str) -> list[dict[str, Any]] | None:
    stripped = (text or "").strip()
    if not stripped or stripped in _TEXT_ONLY:
        return None

    started = started_task_id(stripped)
    if started:
        return [
            _section(stripped),
            _actions(
                [
                    _button("Stop", ACTION_STOP, started, style="danger"),
                    _button("Status", ACTION_STATUS, started),
                ]
            ),
        ]

    if _STOPPED.fullmatch(stripped) or _APPROVAL.fullmatch(stripped):
        return [_context(stripped)]

    waiting = _WAITING.fullmatch(stripped)
    if waiting:
        task_id, approval_id, tool_name = waiting.group(1), waiting.group(2), waiting.group(3)
        buttons = [_button("Stop", ACTION_STOP, task_id, style="danger")]
        if approval_id:
            if not requires_approval_answers(tool_name or ""):
                buttons.append(_button("Approve", ACTION_APPROVE, approval_id))
            buttons.append(_button("Deny", ACTION_DENY, approval_id))
        return [_section(stripped), _actions(buttons)]

    status = _STATUS.fullmatch(stripped)
    if status:
        task_id, state = status.group(1), status.group(2)
        if state in _KNOWN_STATUSES:
            blocks: list[dict[str, Any]] = [_section(stripped)]
            if state not in _TERMINAL_STATUSES:
                blocks.append(
                    _actions([_button("Stop", ACTION_STOP, task_id, style="danger")])
                )
            return blocks
    return None


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text: str) -> dict[str, Any]:
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": text}],
    }


def _actions(elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "actions", "elements": elements}


def _button(
    label: str, action_id: str, value: str, *, style: str | None = None
) -> dict[str, Any]:
    button: dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "action_id": action_id,
        "value": value,
    }
    if style:
        button["style"] = style
    return button

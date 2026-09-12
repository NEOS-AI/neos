"""Application-layer command execution. Gateway and HTTP share this."""

from __future__ import annotations

from typing import Any

from neos.coding.commands.catalog import all_command_specs, catalog_listings, lookup_command
from neos.coding.commands.export import export_transcript
from neos.coding.commands.interpret import interpret_coding_command
from neos.coding.commands.parse import sanitize_command_args
from neos.coding.commands.types import (
    CommandDecision,
    CommandDisposition,
    CommandResult,
    CommandStatus,
)
from neos.coding.domain.errors import CodingTaskNotFound
from neos.coding.domain.phases import SteeringMode


def format_help(name: str = "") -> str:
    wanted = (name or "").strip().lstrip("/!").lower()
    if wanted:
        spec = lookup_command(wanted)
        if spec is None:
            return f"Unknown command /{wanted}. Try /help."
        state = "enabled" if spec.enabled else "disabled"
        return f"/{spec.name} ({state}) — {spec.description} Usage: {spec.usage}"
    lines = ["Commands this deployment interprets:"]
    for spec in all_command_specs():
        mark = "" if spec.enabled else " [disabled]"
        lines.append(f"/{spec.name}{mark} — {spec.description}")
    return "\n".join(lines)


def cost_payload_from_loop_state(loop_state: Any) -> dict[str, int]:
    if not isinstance(loop_state, dict):
        return {}
    payload: dict[str, int] = {}
    for key in ("cost_micros", "input_tokens", "output_tokens"):
        value = loop_state.get(key)
        if isinstance(value, int):
            payload[key] = value
    return payload


def format_cost_line(task_id: str, payload: dict[str, int]) -> str:
    if not payload:
        return f"{task_id} cost is tracked on the task."
    parts: list[str] = []
    if "cost_micros" in payload:
        parts.append(f"cost_micros={payload['cost_micros']}")
    inbound = payload.get("input_tokens")
    outbound = payload.get("output_tokens")
    if inbound is not None or outbound is not None:
        parts.append(f"tokens={int(inbound or 0)}+{int(outbound or 0)}")
    return f"{task_id} " + " ".join(parts)


def loop_state_from_snapshot(snapshot: Any) -> dict[str, Any]:
    if snapshot is None:
        return {}
    checkpoint = getattr(snapshot, "latest_checkpoint", None)
    if checkpoint is None and isinstance(snapshot, dict):
        checkpoint = snapshot.get("latest_checkpoint")
    if checkpoint is None:
        return {}
    loop_state = getattr(checkpoint, "loop_state", None)
    if loop_state is None and isinstance(checkpoint, dict):
        loop_state = checkpoint.get("loop_state")
    return loop_state if isinstance(loop_state, dict) else {}


class CodingCommandService:
    """Single invoke() entry for REST and ChannelCodingPort."""

    def __init__(self, *, runs: Any, snapshots: Any) -> None:
        self._runs = runs
        self._snapshots = snapshots

    async def invoke(
        self,
        *,
        text: str,
        task_id: str,
        owner_id: str,
    ) -> CommandResult:
        decision = interpret_coding_command(text)
        name = (decision.spec.name if decision.spec else decision.parsed.name) or ""
        args = sanitize_command_args(decision.parsed.args)
        if decision.disposition is CommandDisposition.CHAT:
            return CommandResult(
                name="",
                status=CommandStatus.CHAT,
                message="Not a slash command.",
                args=args,
            )
        if decision.disposition is CommandDisposition.UNKNOWN:
            return CommandResult(
                name=name or decision.parsed.name,
                status=CommandStatus.UNKNOWN,
                message=decision.message,
                args=args,
            )
        if decision.disposition is CommandDisposition.DENIED:
            return CommandResult(
                name=name,
                status=CommandStatus.DENIED,
                message=decision.message,
                args=args,
            )
        if decision.disposition is CommandDisposition.CHANNEL:
            return CommandResult(
                name=name,
                status=CommandStatus.CHANNEL,
                message=self._channel_message(name),
                args=args,
            )
        if decision.disposition is CommandDisposition.INJECT:
            await self._queue(task_id, owner_id, decision.inject_text)
            return CommandResult(
                name=name,
                status=CommandStatus.QUEUED,
                message=decision.message,
                args=args,
            )
        if decision.disposition is CommandDisposition.APPLY_IN_LOOP:
            await self._queue(task_id, owner_id, decision.canonical_text)
            return CommandResult(
                name=name,
                status=CommandStatus.QUEUED,
                message=decision.message,
                args=args,
            )
        return await self._execute(decision, task_id=task_id, owner_id=owner_id)

    async def _execute(
        self,
        decision: CommandDecision,
        *,
        task_id: str,
        owner_id: str,
    ) -> CommandResult:
        spec = decision.spec
        assert spec is not None
        args = sanitize_command_args(decision.parsed.args)
        if spec.name == "help":
            return CommandResult(
                name="help",
                status=CommandStatus.OK,
                message=format_help(args),
                args=args,
                payload={"commands": list(catalog_listings())},
            )
        snapshot = await self._snapshots.get_owned(task_id, owner_id)
        if snapshot is None:
            raise CodingTaskNotFound(task_id)
        if spec.name == "cost":
            payload = cost_payload_from_loop_state(loop_state_from_snapshot(snapshot))
            return CommandResult(
                name="cost",
                status=CommandStatus.OK,
                message=format_cost_line(task_id, payload),
                payload=payload,
            )
        if spec.name == "export":
            exported = export_transcript(loop_state_from_snapshot(snapshot))
            count = int(exported.get("message_count") or 0)
            return CommandResult(
                name="export",
                status=CommandStatus.OK,
                message=(
                    f"Redacted transcript has {count} messages. "
                    "Full dump is in the response payload, not raw loop_state."
                ),
                payload=exported,
            )
        if spec.name == "status":
            status_fn = getattr(snapshot.task, "status", None)
            status = getattr(status_fn, "value", status_fn)
            return CommandResult(
                name="status",
                status=CommandStatus.OK,
                message=f"{task_id} {status}",
                payload={"task_id": task_id, "status": str(status)},
            )
        if spec.name == "stop":
            await self._runs.stop(task_id=task_id, owner_id=owner_id)
            return CommandResult(
                name="stop",
                status=CommandStatus.OK,
                message=f"Stopped {task_id}",
                payload={"task_id": task_id, "status": "cancelled"},
            )
        return CommandResult(
            name=spec.name,
            status=CommandStatus.UNAVAILABLE,
            message=f"Command /{spec.name} is not available.",
            args=args,
        )

    async def _queue(self, task_id: str, owner_id: str, instruction: str) -> None:
        await self._runs.steer(
            task_id=task_id,
            owner_id=owner_id,
            instruction=instruction,
            mode=SteeringMode.SAFE_POINT,
        )

    @staticmethod
    def _channel_message(name: str) -> str:
        if name == "code":
            return "Use /code on a channel thread or POST /coding/tasks."
        if name in {"approve", "deny"}:
            return "Use the approval endpoint or /approve /deny on the channel."
        if name == "new":
            return "Use /new on the channel thread to unbind. /clear keeps the task."
        if name == "learn":
            return "Use /learn on a channel. Learning stays fail-closed."
        return f"Command /{name} is handled by the channel gateway."

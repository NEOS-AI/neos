"""One child safe point: a model turn XOR a tool batch."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from neos.coding.harness import fold_model_event, iter_model_turn
from neos.coding.model.base import (
    CanonicalMessage,
    CodingModel,
    ModelLimits,
    ModelRequest,
    TextContent,
    ToolDefinition,
    ToolResultContent,
    ToolUseContent,
)
from neos.coding.model.errors import CodingModelError
from neos.subagent.catalog import SubagentSpec
from neos.subagent.prompts import build_explore_system_prompt, render_brief
from neos.subagent.store import CasReservation, CheckpointWrite, is_placeholder
from neos.subagent.types import (
    SubagentStatus,
    SubagentTicket,
    ToolPort,
)

REFUSED_TOOLS = frozenset(
    {
        "spawn_agent.v1",
        "subagent_list.v1",
        "subagent_steer.v1",
        "edit_file.v1",
        "write_file.v1",
        "execute.v1",
        "ask_user.v1",
        "set_phase.v1",
        "todo_write.v1",
        "web_fetch.v1",
        "search_tools.v1",
    }
)
_MAX_TOOL_BATCH = 10
_MAX_TRANSCRIPT_BYTES = 1024 * 1024
_MAX_TOOL_BODY = 32 * 1024
_COMPACT_AFTER_TURNS = 2
_COMPACT_CHAR_CAP = 64 * 1024


class ChildStepper:
    def __init__(self, *, model: CodingModel, tools: ToolPort) -> None:
        self._model = model
        self._tools = tools

    async def step(
        self,
        *,
        ticket: SubagentTicket,
        spec: SubagentSpec,
        reservation: CasReservation,
    ) -> CheckpointWrite:
        state = _restore(ticket, reservation)
        if int(state["turn_count"]) >= ticket.max_turns:
            state["error_code"] = "turns_exhausted"
            return _write(state, SubagentStatus.COMPLETED)
        pending = list(state.get("pending_tools") or [])
        if pending:
            return await self._run_tools(state, spec, pending)
        return await self._run_model(ticket, spec, reservation, state)

    async def _run_model(
        self,
        ticket: SubagentTicket,
        spec: SubagentSpec,
        reservation: CasReservation,
        state: dict[str, Any],
    ) -> CheckpointWrite:
        run_id = reservation.run.run_id
        _apply_pending_steer(state)
        request_kwargs = _thinking_off_kwargs()
        request = ModelRequest(
            system=build_explore_system_prompt(),
            messages=_canonical_messages(state),
            tools=_child_tools(spec, self._tools),
            model=ticket.model.alias or ticket.model.model,
            limits=ModelLimits(max_output_tokens=4096, timeout_sec=120),
            task_id=run_id,
            run_id=run_id,
            turn_id=f"sat_{uuid4().hex}",
            **request_kwargs,
        )
        text_parts: list[str] = []
        tool_calls: list[Any] = []
        try:
            async for event in iter_model_turn(self._model, request):
                completed = fold_model_event(
                    event, text_parts=text_parts, tool_calls=tool_calls
                )
                if completed is not None and completed.usage is not None:
                    state["input_tokens"] = int(state["input_tokens"]) + (
                        completed.usage.input_tokens
                    )
                    state["output_tokens"] = int(state["output_tokens"]) + (
                        completed.usage.output_tokens
                    )
        except CodingModelError as exc:
            if exc.retryable:
                raise
            state["error_code"] = exc.code
            return _write(state, SubagentStatus.FAILED)
        text = "".join(text_parts)
        state["last_assistant_text"] = text
        state["turn_count"] = int(state["turn_count"]) + 1
        pending: list[dict[str, Any]] = []
        recorded_calls: list[dict[str, Any]] = []
        for call in tool_calls:
            recorded = {
                "tool_call_id": call.tool_call_id,
                "name": call.name,
                "input": dict(call.input),
            }
            recorded_calls.append(recorded)
            pending.append(recorded)
        state["messages"].append(
            {"role": "assistant", "text": text, "tool_calls": recorded_calls}
        )
        if not pending:
            return _write(state, SubagentStatus.COMPLETED)
        state["pending_tools"] = pending
        return _write(state, SubagentStatus.RUNNING)

    async def _run_tools(
        self,
        state: dict[str, Any],
        spec: SubagentSpec,
        pending: list[dict[str, Any]],
    ) -> CheckpointWrite:
        batch = pending[:_MAX_TOOL_BATCH]
        rest = pending[_MAX_TOOL_BATCH:]
        for call in batch:
            name = str(call.get("name") or "")
            raw_input = call.get("input") or {}
            payload = dict(raw_input) if isinstance(raw_input, Mapping) else {}
            if name in REFUSED_TOOLS or name not in spec.allowed_tools:
                result: Mapping[str, Any] = {"error": "tool_not_allowed"}
                status = "error"
            else:
                try:
                    result = await self._tools.execute(name, payload)
                    status = "ok"
                except Exception as exc:
                    result = {"error": str(exc)}
                    status = "error"
            content = dict(result) if isinstance(result, Mapping) else {"value": result}
            state["messages"].append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("tool_call_id"),
                    "name": name,
                    "status": status,
                    "content": content,
                }
            )
            state["tool_count"] = int(state["tool_count"]) + 1
            _collect_citations(state, content)
        state["pending_tools"] = rest
        if _transcript_bytes(state) > _MAX_TRANSCRIPT_BYTES:
            state["error_code"] = "child_transcript_too_large"
            return _write(state, SubagentStatus.FAILED)
        _compact(state)
        return _write(state, SubagentStatus.RUNNING)


def _restore(ticket: SubagentTicket, reservation: CasReservation) -> dict[str, Any]:
    raw = reservation.restore_state
    if raw and not is_placeholder(raw):
        state = json.loads(json.dumps(raw))
        state.setdefault("messages", [])
        state.setdefault("pending_tools", [])
        state.setdefault("turn_count", 0)
        state.setdefault("tool_count", 0)
        state.setdefault("last_assistant_text", "")
        state.setdefault("input_tokens", 0)
        state.setdefault("output_tokens", 0)
        state.setdefault("cost_micros", 0)
        state.setdefault("error_code", "")
        state.setdefault("citations", [])
        state.setdefault("pending_steer", "")
        state.setdefault("steer_applied", "")
    else:
        state = {
            "messages": [{"role": "user", "text": render_brief(ticket.briefing)}],
            "pending_tools": [],
            "turn_count": 0,
            "tool_count": 0,
            "last_assistant_text": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_micros": 0,
            "error_code": "",
            "citations": [],
            "pending_steer": "",
            "steer_applied": "",
        }
    _queue_pending_steer(state, getattr(ticket, "pending_steer", "") or "")
    return state


def _write(state: dict[str, Any], status: SubagentStatus) -> CheckpointWrite:
    return CheckpointWrite(
        loop_state=state,
        status=status,
        turn_count=int(state.get("turn_count") or 0),
        tool_count=int(state.get("tool_count") or 0),
        input_tokens=int(state.get("input_tokens") or 0),
        output_tokens=int(state.get("output_tokens") or 0),
        cost_micros=int(state.get("cost_micros") or 0),
        error_code=str(state.get("error_code") or ""),
    )


def _tool_name(item: Any) -> str:
    if isinstance(item, str):
        return item
    return str(getattr(item, "name", "") or "")


def _child_tools(spec: SubagentSpec, port: ToolPort) -> tuple[ToolDefinition, ...]:
    definitions: list[ToolDefinition] = []
    seen: set[str] = set()
    for item in port.definitions():
        name = _tool_name(item)
        if (
            not name
            or name not in spec.allowed_tools
            or name in REFUSED_TOOLS
            or name in seen
        ):
            continue
        seen.add(name)
        if isinstance(item, ToolDefinition):
            definitions.append(item)
            continue
        definitions.append(
            ToolDefinition(
                name=name,
                description=name,
                input_schema={"type": "object", "properties": {}},
            )
        )
    return tuple(definitions)


def _canonical_messages(state: Mapping[str, Any]) -> tuple[CanonicalMessage, ...]:
    messages: list[CanonicalMessage] = []
    for raw in state.get("messages") or ():
        if not isinstance(raw, Mapping):
            continue
        role = raw.get("role")
        if role == "user":
            text = str(raw.get("text") or ".")
            messages.append(CanonicalMessage("user", (TextContent(text),)))
        elif role == "assistant":
            parts: list[Any] = []
            text = str(raw.get("text") or "")
            if text:
                parts.append(TextContent(text))
            for call in raw.get("tool_calls") or ():
                if not isinstance(call, Mapping):
                    continue
                parts.append(
                    ToolUseContent(
                        tool_call_id=str(call.get("tool_call_id") or ""),
                        name=str(call.get("name") or ""),
                        input=dict(call.get("input") or {}),
                    )
                )
            if not parts:
                parts.append(TextContent("."))
            messages.append(CanonicalMessage("assistant", tuple(parts)))
        elif role == "tool":
            content = raw.get("content") or {}
            if not isinstance(content, Mapping):
                content = {"text": str(content)}
            status = raw.get("status") or "ok"
            if status not in {"ok", "error", "denied"}:
                status = "ok"
            messages.append(
                CanonicalMessage(
                    "tool",
                    (
                        ToolResultContent(
                            tool_call_id=str(raw.get("tool_call_id") or ""),
                            status=status,
                            content=dict(content),
                        ),
                    ),
                )
            )
    return tuple(messages)


def _collect_citations(state: dict[str, Any], result: Mapping[str, Any]) -> None:
    cites = [str(item) for item in state.get("citations") or ()]
    for key in ("path", "url"):
        value = result.get(key)
        if value and str(value) not in cites:
            cites.append(str(value))
    state["citations"] = cites


def _thinking_off_kwargs() -> dict[str, Any]:
    fields = getattr(ModelRequest, "__dataclass_fields__", {})
    if "thinking" in fields:
        return {"thinking": False}
    if "thinking_enabled" in fields:
        return {"thinking_enabled": False}
    return {}


def _steer_remainder(snapshot: str, applied: str) -> str:
    """Ticket text is the parent snapshot. Queue only the unapplied suffix."""
    snap = str(snapshot or "").strip()
    done = str(applied or "").strip()
    if not snap or snap == done:
        return ""
    if not done:
        return snap
    prefix = f"{done}\n"
    if snap.startswith(prefix):
        return snap[len(prefix) :]
    if snap.startswith(done):
        return snap[len(done) :].lstrip("\n")
    return snap


def _queue_pending_steer(state: dict[str, Any], text: str) -> None:
    state["pending_steer"] = _steer_remainder(
        text, str(state.get("steer_applied") or "")
    )


def _apply_pending_steer(state: dict[str, Any]) -> None:
    text = str(state.pop("pending_steer", "") or "").strip()
    if not text:
        return
    state["messages"].append({"role": "user", "text": text})
    state["steer_applied"] = text


def _should_compact(state: Mapping[str, Any]) -> bool:
    if int(state.get("turn_count") or 0) >= _COMPACT_AFTER_TURNS:
        return True
    return _transcript_bytes(state) > _COMPACT_CHAR_CAP


def _compact(state: dict[str, Any]) -> None:
    if not _should_compact(state):
        return
    for message in state.get("messages") or ():
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        content = message.get("content")
        if isinstance(content, Mapping) and content.get("_ref"):
            continue
        blob = json.dumps(content, default=str)
        if len(blob) > _MAX_TOOL_BODY:
            message["content"] = {"_ref": "dropped", "bytes": len(blob)}


def _transcript_bytes(state: Mapping[str, Any]) -> int:
    return len(json.dumps(state.get("messages") or [], default=str).encode())

"""Which tools the model is offered, and which it has unlocked.

Three filters stack on the registry's definitions: the phase hides some, a
loaded skill can narrow to its `allowed_tools`, and deferred tools stay out
of the array until `search_tools.v1` reveals them. A reveal is announced by
appending a `ToolAdditionContent`, never by growing the tool array -- that
would change the request prefix and invalidate every thinking block.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping, Sequence

from neos.coding.model.base import (
    CanonicalMessage,
    ToolAdditionContent,
    ToolResultContent,
    ToolUseContent,
)
from neos.coding.phases import hidden_tools_for_phase
from neos.coding.tools.registry import _CONTROL_PLANE_TOOLS
from neos.config.model_config import supports_mid_conversation_tools
from neos.coding.loop._durable.state import AgentLoopState


def _entry_names(content: object) -> set[str]:
    """`name` of each entry in a `search_tools.v1` result."""
    entries = content.get("entries") if isinstance(content, Mapping) else None
    if not isinstance(entries, (list, tuple)):
        return set()
    return {
        str(entry["name"])
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("name")
    }


def _skill_allowed_names(content: Mapping[str, object]) -> set[str]:
    incoming: set[str] = set()
    entries = content.get("entries") if isinstance(content, Mapping) else None
    if not isinstance(entries, (list, tuple)):
        return incoming
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        raw = entry.get("allowed_tools")
        if isinstance(raw, str) and raw.strip():
            incoming.add(raw.strip())
        elif isinstance(raw, (list, tuple)):
            incoming.update(str(item).strip() for item in raw if str(item).strip())
    return incoming


class ToolCatalogMixin:
    @staticmethod
    def _tool_allowed_by_skills(name: str, state: AgentLoopState) -> bool:
        if not state.allowed_tools:
            return True
        if name == "load_skill.v1":
            return True
        return name in state.allowed_tools

    def _tool_definitions(self, state: AgentLoopState):
        method = self._tools.definitions
        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):
            parameters = {}
        # Registries grew these filters over time; older fakes take none.
        kwargs: dict[str, object] = {}
        if "phase" in parameters:
            kwargs["phase"] = state.phase
        if "revealed" in parameters:
            kwargs["revealed"] = state.revealed_tools
        if "declare_deferred" in parameters:
            kwargs["declare_deferred"] = supports_mid_conversation_tools(
                self._config.model
            )
        if kwargs:
            definitions = method(**kwargs)
        else:
            hidden = hidden_tools_for_phase(state.phase)
            definitions = tuple(item for item in method() if item.name not in hidden)
        if not self._config.subagent_enabled:
            definitions = tuple(
                item
                for item in definitions
                if getattr(item, "name", item) not in _CONTROL_PLANE_TOOLS
            )
        view = getattr(state, "device_bridge", None)
        if view is not None:
            # 트랙 Q16a: 소유자의 브리지가 지금 붙어 있을 때만, 끝에 덧붙인다. 붙고 끊길 때
            # 배열이 바뀌는 것은 `_guard_thinking_prefix` 가 사고 블록을 한 번 벗겨 받는다.
            from neos.coding.bridge.catalog import device_tool_definitions

            definitions = tuple(definitions) + device_tool_definitions(view.tools)
        if state.allowed_tools:
            definitions = tuple(
                item
                for item in definitions
                if self._tool_allowed_by_skills(getattr(item, "name", item), state)
            )
        return definitions

    def _registry_tool_names(self) -> frozenset[str]:
        specs = getattr(self._tools, "_tools", None)
        if isinstance(specs, Mapping):
            return frozenset(str(name) for name in specs)
        method = getattr(self._tools, "definitions", None)
        if not callable(method):
            return frozenset()
        try:
            return frozenset(str(item.name) for item in method())
        except TypeError:
            return frozenset()

    def _union_skill_allowed_tools(
        self, current: frozenset[str], content: Mapping[str, object]
    ) -> frozenset[str]:
        incoming = _skill_allowed_names(content)
        if not incoming:
            return current
        registry = self._registry_tool_names()
        merged = incoming if not current else set(current) | incoming
        if registry:
            merged &= set(registry)
        return frozenset(merged)

    def _revealed_from_transcript(
        self, transcript: Sequence[CanonicalMessage]
    ) -> frozenset[str]:
        deferred = frozenset(self._tools.deferred_tool_names())
        search_ids: set[str] = set()
        names: set[str] = set()
        for message in transcript:
            for item in message.content:
                if isinstance(item, ToolUseContent):
                    if item.name == "search_tools.v1":
                        search_ids.add(item.tool_call_id)
                    elif item.name in deferred:
                        names.add(item.name)
                elif (
                    isinstance(item, ToolResultContent)
                    and item.tool_call_id in search_ids
                ):
                    names |= _entry_names(item.content)
        return frozenset(names)

    def _announce_reveals(self, transcript, before, after):
        """Append newly revealed tools instead of growing the tool array.

        Defined once because two call sites widen `revealed_tools`, and a
        reveal announced at only one of them is the stale copy this
        repository keeps rediscovering.
        """
        if not supports_mid_conversation_tools(self._config.model):
            return transcript
        names = sorted(frozenset(after) - frozenset(before))
        if not names:
            return transcript
        return transcript + (
            CanonicalMessage(
                "system", tuple(ToolAdditionContent(name) for name in names)
            ),
        )

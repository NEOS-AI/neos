"""ToolPort the coding parent injects into a child stepper.

Every call goes through the parent's gate (roadmap CHILD-GATE). The port checks
only what the *spec* allows; whether *this* call may run is decided where the
parent decides its own calls -- hooks, static approval policy, Jev -- through
the `authorize` callback the parent binds. The port keeps no copy of that
policy. Unbound, it refuses everything: a child that reaches the executor
without a gate is the hole this closes.

**One port, many tasks** (roadmap CHILD-PORT-SHARED). The runtime builds one
port, and the development runtime is a module singleton whose supervisor runs
several coding tasks at once. A binding kept as port state let task B's spawn
rebind the port while task A's child was awaiting a tool -- A's child then ran
in B's session under B's gate. So bindings are keyed by the coding task
(`ticket.parent_id`, which nested children inherit), and the stepper reaches
the port only through `for_ticket`, which also takes the spec from the ticket
instead of from whatever was bound last.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from neos.coding.redact import strip_binary_payloads
from neos.coding.tools.registry import CodingToolRegistry, ToolRisk, ToolValidationError
from neos.subagent.catalog import lookup_spec
from neos.subagent.types import SandboxMode


class CodingToolPortError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


# (validated call) -> (call to run, None) or (None, reason_code)
ChildAuthorizer = Callable[[Any], Awaitable[tuple[Any, str | None]]]


@dataclass(frozen=True, slots=True)
class _ChildBinding:
    session: Any
    authorize: ChildAuthorizer | None


class CodingToolPort:
    def __init__(self, *, registry: CodingToolRegistry, executor) -> None:
        self._registry = registry
        self._executor = executor
        self._bindings: dict[str, _ChildBinding] = {}

    def bind(
        self,
        *,
        task_id: str,
        session,
        authorize: ChildAuthorizer | None = None,
    ) -> None:
        # Rebinding replaces the whole binding: a rebind without a gate clears
        # the old one rather than keeping a closure over another step's state.
        self._bindings[task_id] = _ChildBinding(session=session, authorize=authorize)

    def unbind(self, task_id: str) -> None:
        self._bindings.pop(task_id, None)

    def for_ticket(self, ticket) -> "CodingToolView":
        return CodingToolView(
            registry=self._registry,
            executor=self._executor,
            spec_name=ticket.spec,
            binding=self._bindings.get(ticket.parent_id),
        )


class CodingToolView:
    """The port as one child sees it: its spec, its task's binding."""

    def __init__(
        self,
        *,
        registry: CodingToolRegistry,
        executor,
        spec_name: str,
        binding: _ChildBinding | None,
    ) -> None:
        self._registry = registry
        self._executor = executor
        self._spec_name = spec_name
        self._binding = binding

    def definitions(self) -> tuple[Any, ...]:
        spec = lookup_spec(self._spec_name)
        host = self._registry.definitions(
            phase="implement", revealed=spec.allowed_tools
        )
        return tuple(item for item in host if item.name in spec.allowed_tools)

    async def execute(self, name: str, input: Mapping[str, object]) -> Mapping[str, Any]:
        spec = lookup_spec(self._spec_name)
        if name not in spec.allowed_tools:
            raise CodingToolPortError("tool_not_allowed")
        try:
            validated = self._registry.validate(name, dict(input))
        except ToolValidationError as error:
            raise CodingToolPortError(error.reason_code) from error
        write_ok = spec.sandbox_mode is SandboxMode.WORKTREE
        if validated.risk is not ToolRisk.READ_ONLY and not write_ok:
            raise CodingToolPortError("tool_not_read_only")
        binding = self._binding
        if binding is None or binding.session is None:
            raise CodingToolPortError("sandbox_session_missing")
        if binding.authorize is None:
            raise CodingToolPortError("policy_gate_unbound")
        validated, reason_code = await binding.authorize(validated)
        if reason_code is not None:
            raise CodingToolPortError(reason_code)
        result = await self._executor.execute(binding.session, validated)
        if hasattr(result, "to_mapping"):
            return strip_binary_payloads(dict(result.to_mapping()))
        if isinstance(result, Mapping):
            return dict(result)
        return {"value": result}

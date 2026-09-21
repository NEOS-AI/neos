"""Read-only ToolPort the coding parent injects into a child stepper."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from neos.coding.redact import strip_binary_payloads
from neos.coding.tools.registry import CodingToolRegistry, ToolRisk, ToolValidationError
from neos.subagent.catalog import lookup_spec
from neos.subagent.types import SandboxMode


class CodingToolPortError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class CodingToolPort:
    def __init__(
        self,
        *,
        registry: CodingToolRegistry,
        executor,
        spec: str = "explore",
    ) -> None:
        self._registry = registry
        self._executor = executor
        self._spec_name = spec
        self._session = None

    def use_spec(self, spec: str) -> None:
        self._spec_name = spec

    def bind(
        self,
        *,
        session,
        phase: str | None = None,
        revealed: frozenset[str] | None = None,
    ) -> None:
        del phase, revealed
        self._session = session

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
        if self._session is None:
            raise CodingToolPortError("sandbox_session_missing")
        result = await self._executor.execute(self._session, validated)
        if hasattr(result, "to_mapping"):
            return strip_binary_payloads(dict(result.to_mapping()))
        if isinstance(result, Mapping):
            return dict(result)
        return {"value": result}

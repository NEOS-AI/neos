"""Fail-closed subagent spec registry. P1 catalog is explore only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from neos.subagent.types import SandboxMode


class UnknownSpec(ValueError):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


@dataclass(frozen=True, slots=True)
class SubagentSpec:
    name: str
    description: str
    allowed_tools: frozenset[str]
    sandbox_mode: SandboxMode
    load_project_instructions: bool
    thinking: Literal["off"]
    can_spawn: bool
    can_approve: bool
    one_shot: bool  # no parent follow-up on the same sa_…; fold is the end


EXPLORE = SubagentSpec(
    name="explore",
    description="Read-only investigation. Report only. Do not edit.",
    allowed_tools=frozenset(
        {
            "read_file.v1",
            "search_text.v1",
            "glob_files.v1",
            "list_tree.v1",
            "stat.v1",
            "git_status.v1",
            "git_diff.v1",
            "git_log.v1",
            # DA ToolPort names (host-provided; ignored if absent)
            "search",
            "fetch",
        }
    ),
    sandbox_mode=SandboxMode.PARENT_RO,
    load_project_instructions=False,
    thinking="off",
    can_spawn=False,
    can_approve=False,
    one_shot=True,
)


class SpecRegistry:
    def lookup_spec(self, name: str) -> SubagentSpec:
        return lookup_spec(name)


def lookup_spec(name: str) -> SubagentSpec:
    if name == EXPLORE.name:
        return EXPLORE
    raise UnknownSpec(name)

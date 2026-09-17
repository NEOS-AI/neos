"""Fail-closed subagent spec registry. Explore plus isolated implement."""

from __future__ import annotations

from dataclasses import dataclass

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
    # No thinking setting lives here. It said "off", nothing ever sent it, and
    # it is false on every model a child runs on: Fable 5.1 cannot disable
    # thinking, and Sonnet 5 / Opus 5 think by default (roadmap K1d).
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
            "spawn_agent.v1",
        }
    ),
    sandbox_mode=SandboxMode.PARENT_RO,
    load_project_instructions=False,
    can_spawn=True,
    can_approve=False,
    one_shot=True,
)


IMPLEMENT = SubagentSpec(
    name="implement",
    description="Write in an isolated worktree. Parent merges. Do not spawn.",
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
            "edit_file.v1",
            "write_file.v1",
            "execute.v1",
            "mkdir.v1",
            "rm.v1",
            "mv.v1",
            "chmod.v1",
        }
    ),
    sandbox_mode=SandboxMode.WORKTREE,
    load_project_instructions=False,
    can_spawn=False,
    can_approve=False,
    one_shot=True,
)

_MAX_SPAWN_DEPTH = 0


def may_spawn(spec: SubagentSpec, spawn_depth: int) -> bool:
    return bool(spec.can_spawn) and spawn_depth <= _MAX_SPAWN_DEPTH


class SpecRegistry:
    def lookup_spec(self, name: str) -> SubagentSpec:
        return lookup_spec(name)


def lookup_spec(name: str) -> SubagentSpec:
    if name == EXPLORE.name:
        return EXPLORE
    if name == IMPLEMENT.name:
        return IMPLEMENT
    raise UnknownSpec(name)

"""Fail-closed subagent spec registry. Explore, implement, research, FSI leaves."""

from __future__ import annotations

from collections.abc import Mapping
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

# 조사 스펙 셋 (계약 §2). 도구 목록은 계약이 정한 그대로다.
#
# `sandbox_mode` 가 `NONE` 인 이유: 서브에이전트 런타임은 워크스페이스를 붙이지
# 않는다. `/evidence`(읽기 전용)와 `/workspace` 는 오케스트레이터가
# `research-offline-v1` 프로파일로 띄운 샌드박스가 갖고, `execute.v1` 이 그리로
# 간다. `WORKTREE` 는 git 저장소를 요구하고 DA 에는 없다 (계약 §2 구현 주석).
_RESEARCH_TOOLS = frozenset(
    {
        "search.v1",
        "fetch.v1",
        "list_tree.v1",
        "read_file.v1",
        "search_text.v1",
        "write_file.v1",
        "execute.v1",
        "load_skill.v1",
        "check_claims.v1",
        "submit.v1",
    }
)
#: 계약 §2 는 analyze 를 "research 에서 이 둘을 뺀 것" 으로 적는다. 목록을 다시
#: 타이핑하지 않고 그 문장을 그대로 코드로 둔다 -- 그래야 둘이 갈라지지 않는다.
_RETRIEVAL_TOOLS = frozenset({"search.v1", "fetch.v1"})


RESEARCH = SubagentSpec(
    name="research",
    description="Investigate one question. Propose quote claims. Do not write the ledger.",
    allowed_tools=_RESEARCH_TOOLS,
    sandbox_mode=SandboxMode.NONE,
    load_project_instructions=False,
    can_spawn=False,
    can_approve=False,
    one_shot=True,
)


ANALYZE = SubagentSpec(
    name="analyze",
    description="Compute over this question's verified claims only. No retrieval.",
    allowed_tools=_RESEARCH_TOOLS - _RETRIEVAL_TOOLS,
    sandbox_mode=SandboxMode.NONE,
    load_project_instructions=False,
    can_spawn=False,
    can_approve=False,
    one_shot=True,
)


COMPOSE = SubagentSpec(
    name="compose",
    description="Read the claim files and write the report to the workspace.",
    allowed_tools=frozenset(
        {
            "list_tree.v1",
            "read_file.v1",
            "search_text.v1",
            "write_file.v1",
            "edit_file.v1",
            "check_claims.v1",
            "submit.v1",
        }
    ),
    sandbox_mode=SandboxMode.NONE,
    load_project_instructions=False,
    can_spawn=False,
    can_approve=False,
    one_shot=True,
)


FSI_READER = SubagentSpec(
    name="fsi-reader",
    description=(
        "FSI untrusted-document reader. Extract schema-validated JSON. "
        "Report only. Do not edit. No MCP. No bash."
    ),
    allowed_tools=frozenset(
        {
            "read_file.v1",
            "search_text.v1",
        }
    ),
    sandbox_mode=SandboxMode.NONE,
    load_project_instructions=False,
    can_spawn=False,
    can_approve=False,
    one_shot=True,
)


FSI_WRITER = SubagentSpec(
    name="fsi-writer",
    description=(
        "FSI writer leaf. Only worker with Write. "
        "Author ./out artifacts. Do not spawn. No untrusted MCP."
    ),
    allowed_tools=frozenset(
        {
            "read_file.v1",
            "write_file.v1",
            "edit_file.v1",
            "load_skill.v1",
        }
    ),
    sandbox_mode=SandboxMode.NONE,
    load_project_instructions=False,
    can_spawn=False,
    can_approve=False,
    one_shot=True,
)


FSI_CRITIC = SubagentSpec(
    name="fsi-critic",
    description=(
        "FSI critic. Re-verify against trusted MCP. "
        "Read-only. Do not edit. Do not spawn. No output_schema."
    ),
    allowed_tools=frozenset(
        {
            "read_file.v1",
            "search_text.v1",
        }
    ),
    sandbox_mode=SandboxMode.NONE,
    load_project_instructions=False,
    can_spawn=False,
    can_approve=False,
    one_shot=True,
)


FSI_PULLER = SubagentSpec(
    name="fsi-puller",
    description=(
        "FSI trusted market-data puller. Read + MCP. "
        "Schema-validated JSON. Do not write. Do not spawn."
    ),
    allowed_tools=frozenset(
        {
            "read_file.v1",
            "search_text.v1",
        }
    ),
    sandbox_mode=SandboxMode.NONE,
    load_project_instructions=False,
    can_spawn=False,
    can_approve=False,
    one_shot=True,
)


FSI_MODELER = SubagentSpec(
    name="fsi-modeler",
    description=(
        "FSI modeler leaf (pitch-modeler). Bash allowed, no Write. "
        "Do not spawn."
    ),
    allowed_tools=frozenset(
        {
            "read_file.v1",
            "search_text.v1",
            "execute.v1",
        }
    ),
    sandbox_mode=SandboxMode.NONE,
    load_project_instructions=False,
    can_spawn=False,
    can_approve=False,
    one_shot=True,
)


_MAX_SPAWN_DEPTH = 0


def may_spawn(spec: SubagentSpec, spawn_depth: int) -> bool:
    return bool(spec.can_spawn) and spawn_depth <= _MAX_SPAWN_DEPTH


class SpecRegistry:
    def __init__(self, specs: Mapping[str, SubagentSpec] | None = None) -> None:
        self._specs = dict(_SPECS if specs is None else specs)

    def lookup_spec(self, name: str) -> SubagentSpec:
        spec = self._specs.get(name)
        if spec is None:
            raise UnknownSpec(name)
        return spec

    def register(self, spec: SubagentSpec) -> None:
        self._specs[spec.name] = spec


#: 이름 -> 스펙. if 사슬이 다섯 갈래가 되면 하나를 빠뜨려도 조용하다 --
#: 매핑이면 등록과 조회가 같은 자리에 있다. fail-closed 는 그대로다.
_SPECS: dict[str, SubagentSpec] = {
    spec.name: spec
    for spec in (
        EXPLORE,
        IMPLEMENT,
        RESEARCH,
        ANALYZE,
        COMPOSE,
        FSI_READER,
        FSI_WRITER,
        FSI_CRITIC,
        FSI_PULLER,
        FSI_MODELER,
    )
}


def lookup_spec(name: str) -> SubagentSpec:
    spec = _SPECS.get(name)
    if spec is None:
        raise UnknownSpec(name)
    return spec

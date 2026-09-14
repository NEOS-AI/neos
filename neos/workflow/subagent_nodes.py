"""서브에이전트 템플릿 노드 -- 설계된 그래프의 노드 일부를 경계 있는 자식 실행으로.

설계 정본: `docs/GRAPH_SUBAGENT_INTEGRATION_DESIGN.md` (트랙 I, K25′).

**이 모듈은 `workflow.subagent_nodes_enabled` 가 켜졌을 때만 import 된다.**
`neos.subagent` 패키지를 import 하면 런타임·스테퍼·코딩 모델 계층이 따라 올라온다 --
플래그가 꺼진 경로(`neos.workflow.graph`)가 그 비용과 import 부작용을 지지 않도록
그래프 쪽은 이 모듈을 함수 안에서만 import 한다.

여기 있는 것:

- `SubagentNodeTemplate` -- 명세·도구·브리핑 매핑·턴 상한·모델 역할. 계약은 **생성**된다.
- 등록 검사 -- K25′ (a) 를 import 시점에 fail-closed 로 강제한다.
- 비용 상한 -- GS-K6. 카탈로그 창과 가격만으로 계산한다. 지어낸 수가 없다.
- 전개 -- 자기 루프 간선과 `loop_bounds` 를 검증 **전에** 결정론적으로 붙인다.
- `SubagentRuleInputs` 조립 -- `validate_topology` 의 템플릿 규칙 재료.
"""

from __future__ import annotations

import typing
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from typing import Any, Literal

from neos.subagent.catalog import IMPLEMENT, UnknownSpec, lookup_spec
from neos.subagent.stepper import CHILD_MAX_OUTPUT_TOKENS, REFUSED_TOOLS
from neos.subagent.types import ParentBriefing, SandboxMode
from neos.workflow.contracts import NodeContract
from neos.workflow.enums import WorkflowNode
from neos.workflow.state import AgentState
from neos.workflow.topology import GraphTopology, SubagentRuleInputs

#: 템플릿 보고를 검사하는 노드 (GS-K5). `quality_validator` 는 완결성 점수를
#: 매길 뿐 주장을 검증하지 않으므로 인정하지 않는다.
CHECK_NODES: frozenset[str] = frozenset({WorkflowNode.FACT_CHECK.value})

#: 템플릿 노드가 반환하는 키. 셋 다 리듀서가 붙어 병렬 가지에서 안전하다.
TEMPLATE_WRITES: frozenset[str] = frozenset(
    {"search_results", "subagent_runs", "subagent_reports"}
)
#: 템플릿 핸들러가 브리핑 말고 읽는 키.
TEMPLATE_READS: frozenset[str] = frozenset({"subagent_scope", "subagent_runs"})

#: 브리핑으로 매핑할 수 있는 `ParentBriefing` 문자열 필드.
_BRIEFING_TEXT_FIELDS: frozenset[str] = frozenset({"goal", "why", "scope", "success"})

#: 워크플로 자식이 절대 받지 않는 도구: 스폰, 쓰기 명세 전용 도구, 스테퍼 거부 목록.
_SPAWN_TOOL = "spawn_agent.v1"


class TemplateRegistrationError(ValueError):
    """템플릿이 K25′ 제한이나 모양 규칙을 어겼다. import 시점에 터진다."""


def _forbidden_tools() -> frozenset[str]:
    from neos.subagent.catalog import EXPLORE

    write_only = IMPLEMENT.allowed_tools - EXPLORE.allowed_tools
    return frozenset({_SPAWN_TOOL}) | write_only | REFUSED_TOOLS


def _template_handler_placeholder(*_args: Any, **_kwargs: Any) -> Any:
    """`NodeContract.handler` 자리. 템플릿 노드는 이것으로 실행되지 않는다.

    조립기는 템플릿 노드를 `SubagentNodeHost.handler_for` 로 바인딩한다. 이
    함수가 불렸다면 조립기가 템플릿을 정적 노드처럼 취급한 것이다 -- 조용히
    빈 dict 를 돌려주면 그 버그가 "노드가 아무것도 안 했다" 로 숨는다.
    """
    raise RuntimeError(
        "subagent template node was bound as a static node -- "
        "build it through SubagentNodeHost"
    )


@dataclass(frozen=True, slots=True)
class SubagentNodeTemplate:
    name: str
    spec: str
    tools: frozenset[str]
    # ParentBriefing 필드 -> AgentState 키. "goal" 은 필수다.
    briefing_from: Mapping[str, str]
    max_turns: int
    model_role: Literal["everyday", "powerful"]
    label: str

    @property
    def max_advances(self) -> int:
        """자기 루프 걸음 상한 (GS-K2).

        한 걸음은 모델 턴 하나 XOR 도구 배치 하나다. 도구를 부르는 턴마다 도구
        걸음이 하나 따르고, 턴을 다 쓰면 한 걸음이 `turns_exhausted` 로 닫는다.
        """
        return 2 * self.max_turns + 1

    @property
    def briefing_keys(self) -> frozenset[str]:
        return frozenset(self.briefing_from.values())

    def contract(self) -> NodeContract:
        """계약을 선언에서 **생성**한다 -- 손으로 채우지 않으므로 낡을 수 없다."""
        return NodeContract(
            node=self.name,
            reads=self.briefing_keys | TEMPLATE_READS,
            writes=TEMPLATE_WRITES,
            requires=self.briefing_keys,
            handler=_template_handler_placeholder,
        )


def _agent_state_keys() -> frozenset[str]:
    return frozenset(typing.get_type_hints(AgentState, include_extras=True))


def agent_state_reducer_keys() -> frozenset[str]:
    """`Annotated[..., reducer]` 로 선언된 `AgentState` 키.

    손으로 적지 않고 주석에서 뽑는다 -- 리듀서를 더하거나 빼는 변경이 이 목록을
    따로 고치지 않아도 `concurrent_write_conflict` 에 반영된다.
    """
    hints = typing.get_type_hints(AgentState, include_extras=True)
    keys: set[str] = set()
    for name, hint in hints.items():
        if _has_reducer(hint):
            keys.add(name)
    return frozenset(keys)


def _has_reducer(hint: Any) -> bool:
    origin = typing.get_origin(hint)
    if origin is typing.Annotated:
        return any(callable(meta) for meta in hint.__metadata__)
    if origin in (typing.NotRequired, typing.Required):
        return any(_has_reducer(arg) for arg in typing.get_args(hint))
    return False


def validate_template(template: SubagentNodeTemplate) -> None:
    """K25′ (a) 와 모양 규칙. 어기면 `TemplateRegistrationError`."""

    problems: list[str] = []
    try:
        spec = lookup_spec(template.spec)
    except UnknownSpec:
        raise TemplateRegistrationError(
            f"{template.name}: 명세 '{template.spec}' 가 등록돼 있지 않다"
        ) from None
    if spec.sandbox_mode is SandboxMode.WORKTREE or spec.name == IMPLEMENT.name:
        problems.append(f"쓰기 명세 '{spec.name}' 는 워크플로 부모가 스폰할 수 없다 (K25′ a)")
    if not template.tools:
        problems.append("도구 집합이 비었다")
    outside = template.tools - spec.allowed_tools
    if outside:
        problems.append(f"명세가 허용하지 않는 도구 {sorted(outside)}")
    forbidden = template.tools & _forbidden_tools()
    if forbidden:
        problems.append(f"스폰·쓰기 도구 {sorted(forbidden)} (K25′ a)")
    if "goal" not in template.briefing_from:
        problems.append("briefing_from 에 'goal' 이 없다")
    unknown_fields = set(template.briefing_from) - _BRIEFING_TEXT_FIELDS
    if unknown_fields:
        problems.append(f"ParentBriefing 문자열 필드가 아닌 {sorted(unknown_fields)}")
    missing_keys = template.briefing_keys - _agent_state_keys()
    if missing_keys:
        problems.append(f"AgentState 에 없는 키 {sorted(missing_keys)}")
    if not 1 <= template.max_turns <= 8:
        problems.append("max_turns 는 1-8 이다")
    if template.model_role not in ("everyday", "powerful"):
        problems.append(f"모델 역할 '{template.model_role}'")
    if template.name in {node.value for node in WorkflowNode}:
        problems.append("이름이 정적 노드(WorkflowNode)와 겹친다")
    if not template.label.strip():
        problems.append("진행 라벨이 비었다")
    if problems:
        raise TemplateRegistrationError(f"{template.name}: " + "; ".join(problems))


SUBAGENT_NODE_TEMPLATES: dict[str, SubagentNodeTemplate] = {}


def register_template(template: SubagentNodeTemplate) -> SubagentNodeTemplate:
    validate_template(template)
    if template.name in SUBAGENT_NODE_TEMPLATES:
        raise TemplateRegistrationError(f"{template.name}: 두 번 등록됐다")
    SUBAGENT_NODE_TEMPLATES[template.name] = template
    return template


#: 첫 템플릿. DA 어댑터와 같은 도구 둘(`search`/`fetch`)과 같은 턴 기본값(4).
EXPLORE_WEB = register_template(
    SubagentNodeTemplate(
        name="explore_web",
        spec="explore",
        tools=frozenset({"search", "fetch"}),
        briefing_from={"goal": "original_query"},
        max_turns=4,
        model_role="everyday",
        label="Investigating with a subagent",
    )
)

# `ParentBriefing` 필드 이름이 바뀌면 여기서 먼저 터진다.
assert _BRIEFING_TEXT_FIELDS <= {f.name for f in fields(ParentBriefing)}


def template_contracts(
    templates: Mapping[str, SubagentNodeTemplate] | None = None,
) -> dict[str, NodeContract]:
    source = SUBAGENT_NODE_TEMPLATES if templates is None else templates
    return {name: template.contract() for name, template in source.items()}


def merged_contracts(
    static: Mapping[str, NodeContract],
    templates: Mapping[str, SubagentNodeTemplate] | None = None,
) -> dict[str, NodeContract]:
    """정적 계약 + 템플릿 계약. 이름이 겹치면 fail closed."""
    generated = template_contracts(templates)
    overlap = set(static) & set(generated)
    if overlap:
        raise TemplateRegistrationError(f"정적 계약과 겹치는 템플릿 {sorted(overlap)}")
    return {**static, **generated}


# -- 비용 상한 (GS-K6) --------------------------------------------------------


def template_cost_ceiling_micros(
    template: SubagentNodeTemplate,
    *,
    input_ceiling_tokens: int,
    input_micros_per_million: int,
    output_micros_per_million: int,
) -> int:
    """`max_turns × (입력 천장 × 입력 단가 + 출력 상한 × 출력 단가)`, 올림.

    `max_turns` 가 곱해지는 것이 맞다: 모델을 부르는 걸음은 턴 걸음뿐이고(도구
    걸음·`turns_exhausted` 걸음은 부르지 않는다) 턴은 `max_turns` 를 넘지 않는다.
    입력 천장은 자식 요청에 입력 한도가 없어서 **모델 창**이다 -- 느슨하지만 참인
    상한이다.
    """
    per_turn = (
        input_ceiling_tokens * input_micros_per_million
        + CHILD_MAX_OUTPUT_TOKENS * output_micros_per_million
    )
    return -(-(template.max_turns * per_turn) // 1_000_000)


def resolve_template_cost_ceiling(
    template: SubagentNodeTemplate, *, provider: str, model: str
) -> int | None:
    """카탈로그로 상한을 계산한다. 창·가격 중 하나라도 모르면 `None`(미가격)."""
    from neos.config.model_config import get_model_spec, resolve_coding_rate_micros

    spec = get_model_spec(model)
    if spec is None or spec.provider != provider or spec.pricing is None:
        return None
    ceiling = spec.input_limit or spec.context_window
    if not ceiling:
        return None
    rates = resolve_coding_rate_micros(
        provider=provider,
        model=model,
        input_cost_micros_per_million=0,
        output_cost_micros_per_million=0,
    )
    if rates.input <= 0 and rates.output <= 0:
        return None
    return template_cost_ceiling_micros(
        template,
        input_ceiling_tokens=int(ceiling),
        input_micros_per_million=rates.input,
        output_micros_per_million=rates.output,
    )


# -- 전개 (GS-K2) ------------------------------------------------------------


def expand_subagent_nodes(
    topology: GraphTopology,
    templates: Mapping[str, SubagentNodeTemplate] | None = None,
) -> GraphTopology:
    """템플릿 노드에 자기 루프와 걸음 상한을 붙인다. **멱등.**

    검증 전에 부른다 -- 자기 루프와 상한이 검증기 눈에 보여야 `unbounded_cycle`
    이 무는지 확인할 수 있다. 설계자는 여전히 정적 엣지만 낸다.
    """
    source = SUBAGENT_NODE_TEMPLATES if templates is None else templates
    present = [node for node in topology.nodes if node in source]
    if not present:
        return topology
    edges = list(topology.edges)
    existing = set(edges)
    loop_bounds = dict(topology.loop_bounds)
    for node in present:
        if (node, node) not in existing:
            edges.append((node, node))
            existing.add((node, node))
        loop_bounds[node] = source[node].max_advances
    return GraphTopology(
        nodes=topology.nodes,
        edges=tuple(edges),
        loop_bounds=loop_bounds,
        initial_writes=topology.initial_writes,
    )


def template_nodes_in(
    nodes: Iterable[str],
    templates: Mapping[str, SubagentNodeTemplate] | None = None,
) -> tuple[str, ...]:
    source = SUBAGENT_NODE_TEMPLATES if templates is None else templates
    return tuple(node for node in nodes if node in source)


def build_rule_inputs(
    *,
    provider: str,
    budget_micros: int | None,
    templates: Mapping[str, SubagentNodeTemplate] | None = None,
    model_for_role: Any = None,
) -> SubagentRuleInputs:
    """`validate_topology(subagent=...)` 재료. 모델은 역할마다 한 번만 해석한다."""
    source = SUBAGENT_NODE_TEMPLATES if templates is None else templates
    resolve = model_for_role or _default_model_for_role
    ceilings: dict[str, int | None] = {}
    resolved: dict[str, str | None] = {}
    for name, template in source.items():
        if template.model_role not in resolved:
            try:
                resolved[template.model_role] = resolve(provider, template.model_role)
            except Exception:  # noqa: BLE001 -- 해석 실패는 미가격(fail closed)
                resolved[template.model_role] = None
        model = resolved[template.model_role]
        ceilings[name] = (
            None
            if model is None
            else resolve_template_cost_ceiling(template, provider=provider, model=model)
        )
    return SubagentRuleInputs(
        template_nodes=frozenset(source),
        check_nodes=CHECK_NODES,
        reducer_keys=agent_state_reducer_keys(),
        cost_ceilings_micros=ceilings,
        budget_micros=budget_micros,
    )


def _default_model_for_role(provider: str, role: str) -> str:
    from neos.config.model_routing import resolve_model
    from neos.config.settings import settings

    return resolve_model(
        config=settings.config.model_routing, provider=provider, role=role
    ).model

"""설계·검증·폴백이 만나는 단 하나의 관문.

Task 6-7 은 두 편을 나눠 놓았다: `GraphDesigner`(및 `LlmGraphDesigner`)는
토폴로지를 제안할 뿐 스스로 승인하지 않고, `validate_topology` 는 제안이
성립하는지 여덟 가지 규칙으로 계산할 뿐 누구를 부를지 모른다. 이 모듈은 그
둘을 여기서 처음으로 엮는다 -- **설계자는 제안하고, 이 함수가 승인 여부를
결정한다.** 이 분리를 지키기 위해 `LlmGraphDesigner.design` 은 절대
`validate_topology` 를 호출하지 않는다; 검증을 설계자 쪽으로 옮기거나, 검증을
거치지 않은 토폴로지를 호출자에게 그대로 흘려보내는 일은 이 모듈이 존재하는
이유 자체를 없앤다.

deep_analysis 하네스는 값비싼 교훈 하나를 남겼다: **이벤트를 하나도 남기지
않는 폴백은 성공과 구별되지 않는다.** 그래서 이 함수를 나가는 네 경로 --
요청(`graph_design_requested`)·승인(`graph_design_accepted`)·거부
(`graph_design_rejected`)·폴백(`graph_design_fallback`) -- 은 각각 반드시
이벤트를 남긴다. 거부는 어느 규칙이 어느 노드에서 깨졌는지(`violations`)를,
폴백은 예외든 타임아웃이든 사유(`reason`)를 싣는다. 사유 없는 폴백은 이
스펙이 막으려는 바로 그 "조용한 degrade" 다.

**재설계 루프는 없다.** 검증이 위반을 찾으면 그 위반 목록을 설계자에게 되돌려
다시 설계를 시도하게 하지 않는다 -- 그러면 질의 하나가 LLM 설계를 여러 번
태워, 지연 시간이 상한 없이(unbounded) 비결정적으로 늘어난다. 위반이든
예외든 타임아웃이든, 이 함수의 반응은 항상 하나다: 이벤트를 남기고
`topology=None` 을 돌려준다. 호출자는 `topology` 가 `None` 이면 정적
그래프를 쓴다.

**응답 없는 설계는 승인하지 않는다 (I1).** `mandatory` 의 기본값
(`_DEFAULT_MANDATORY_NODES`)은 `response_generator` 를 못박는다 -- 그
노드가 없는 토폴로지는 START 에서 END 까지 구조적으로 성립해도(다른 일곱
규칙을 전부 통과해도) 사용자에게 돌려줄 응답을 만들지 않는다. 그런 설계가
`graph_design_accepted` 로 조용히 승인되는 것이 이 관문이 막아야 하는
"그럴듯하지만 빈 산출물" 이다. 이 기본값은 호출자가 `mandatory=()` 를
명시적으로 넘기면 오버라이드된다 -- 그 선택은 코드에 드러난다.

**예산은 아직 강제하지 않는다.** `prompts/graph_design.md` 는 서브에이전트
에게 노드 비용 합계가 예산을 넘지 않게 설계하라고 지시하지만, 이 트리
어디에도 노드별 실제 비용 표가 없다. 없는 비용 표를 추측해 채우면 근거
없는 숫자로 설계를 거부/통과시키는 셈이라 하지 않는다. 그래서 `budget`/
`node_costs` 는 `validate_topology` 로 그대로 흘려보내는 통로만 열어 뒀고
(호출자가 실제 비용 표를 갖게 되면 채울 수 있다), 기본값은 둘 다 `None`
이라 예산 검사 자체가 돌지 않는다. `request.budget`(프롬프트에 박아 넣는
값)을 여기 `budget` 에 자동으로 흘려보내지 않는다 -- `node_costs` 없이
`budget` 만 넘기면 `validate_topology` 의 fail-closed 규칙이 모든 노드를
"비용 미선언" 위반으로 잡아, 사실상 모든 설계를 거부하게 된다.
"""

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from neos.config.settings import settings
from neos.workflow.contracts import NodeContract
from neos.workflow.enums import WorkflowNode
from neos.workflow.graph_designer import DesignRequest, GraphDesigner
from neos.workflow.topology import GraphTopology, validate_topology

# sha256 다이제스트(64자) 전체를 실어 나르는 건 원장 페이로드에 과하다. 앞
# 16자(64비트)면 우연한 충돌 확률이 무시할 만한 수준이면서도 로그에서 눈으로
# 비교하기 좋은 짧은 식별자가 된다 -- 매직 넘버로 흩어놓지 않도록 이름을 준다.
_TOPOLOGY_HASH_HEX_LENGTH = 16

# 이 관문을 통과한 설계는 반드시 응답을 만들어 낼 수 있어야 한다 -- 그렇지
# 않으면 "그럴듯하지만 빈 산출물"(§ 리뷰 I1)이 `graph_design_accepted` 로
# 조용히 승인된다. `mandatory` 의 기본값을 여기 명시적 상수로 못박는다: 이
# 요구는 "호출자가 깜빡하면 사라지는 습관"이 아니라 "이 관문 자체의 불변식"
# 이어야 한다 -- 오늘은 `design_graph_or_fallback` 을 실제로 부르는 프로덕션
# 호출자가 아직 없으므로(설계자는 아직 `execute_workflow` 에 배선되지
# 않았다), 그 불변식을 지킬 다른 자리가 없다. 호출자가 정말로 응답 없는
# 설계(예: 순수 부수효과 파이프라인)를 원한다면 `mandatory=()` 를 명시적으로
# 넘겨 이 기본값을 오버라이드할 수 있다 -- 그 선택은 호출자 책임으로 드러난다.
_DEFAULT_MANDATORY_NODES: tuple[str, ...] = (WorkflowNode.RESP_GENERATOR.value,)


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    """설계 원장에 남는 이벤트 하나.

    `deep_analysis` 의 run 원장 이벤트를 재사용하지 않고 이 태스크에서 새로
    정의한다 -- 그쪽은 run 하나의 생애주기에 묶여 있는데, 이 경로는 아직
    run 이 시작되기 전(그래프를 빌드하는 시점)이라 묶일 run 자체가 없다.
    """

    kind: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DesignOutcome:
    """이 함수가 돌려주는 결과. `topology` 가 `None` 이면 호출자는 정적
    그래프를 쓴다 -- 승인되지 않은 토폴로지가 이 경계를 넘는 경우는 없다."""

    topology: GraphTopology | None
    events: tuple[LedgerEvent, ...]


async def design_graph_or_fallback(
    *,
    designer: GraphDesigner,
    request: DesignRequest,
    contracts: Mapping[str, NodeContract],
    # 기본값을 `_DEFAULT_MANDATORY_NODES` (response_generator) 로 못박는다.
    # `validate_topology` 의 `empty_topology` 규칙은 노드 0개인 설계만 잡는다
    # -- "노드가 있지만 응답을 만드는 노드가 없는" 설계(예: query_classifier
    # 하나로 끝나는 그래프)는 그 규칙을 통과하고도 아무 응답도 내지 않는다.
    # 그게 바로 이 관문이 막아야 하는 "그럴듯하지만 빈 산출물" 이다. 호출자가
    # 정말 응답 없는 설계를 원하면(예: 순수 부수효과 파이프라인) `mandatory=()`
    # 를 명시적으로 넘겨 이 기본값을 오버라이드한다 -- 그 선택은 호출자 책임
    # 으로 코드에 드러난다.
    mandatory: Sequence[str] = _DEFAULT_MANDATORY_NODES,
    # 예산: `prompts/graph_design.md` 는 서브에이전트에게 "노드 비용 합계가
    # budget 을 넘지 않아야 한다"고 지시하지만, 오늘 이 트리 어디에도 노드별
    # 실제 비용 표(`node_costs`)가 없다 -- 그 표를 지어내면(추측한 숫자를
    # `budget_exceeded` 판정에 쓰면) 근거 없는 수치로 설계를 거부하거나
    # 통과시키는 꼴이라 하지 않는다. 그래서 `budget`/`node_costs` 는 여기서
    # `validate_topology` 로 그대로 전달하는 통로만 열어 둔다: 실제 비용 표가
    # 생기면 호출자가 이 둘을 채워 예산을 강제할 수 있다. 오늘은 둘 다
    # 기본값 `None` 이라 `validate_topology` 의 예산 검사 자체가 아예 돌지
    # 않는다(budget=None 이면 그 블록을 건너뛴다) -- "느슨하게 통과"가 아니라
    # "아직 검사하지 않음" 이며, 그 사실은 `request.budget` 을 그대로
    # `budget` 에 흘려보내지 않는 이 코드와, 위 프롬프트에 추가한 주석으로
    # 드러난다.
    budget: int | None = None,
    node_costs: Mapping[str, int] | None = None,
    timeout_sec: float | None = None,
) -> DesignOutcome:
    """설계자를 호출하고, 성공하면 검증하고, 어느 쪽이든 이벤트를 남긴다.

    `timeout_sec` 을 생략하면 설정값(`graph_design_timeout_sec`)을 쓴다 --
    `LlmGraphDesigner` 가 자체 타임아웃과 같은 기본값을 쓰는 것과 다른
    이유다: 여기서는 설계자 구현체가 스스로 타임아웃을 두지 않았을 수도
    있으므로(예: 단순한 fake), 이 함수가 바깥에서 한 번 더 상한을 건다.
    `LlmGraphDesigner.design` 이 타임아웃을 그대로 전파하도록 만들어 둔 것도
    같은 이유다 -- 폴백 여부를 결정하는 자리는 설계자가 아니라 여기다.
    """

    events: list[LedgerEvent] = [
        LedgerEvent(
            kind="graph_design_requested",
            payload={
                "query": request.query,
                "budget": request.budget,
                "catalog_size": len(request.catalog),
            },
        )
    ]
    effective_timeout = (
        timeout_sec
        if timeout_sec is not None
        else settings.config.workflow.graph_design_timeout_sec
    )

    try:
        topology = await asyncio.wait_for(
            designer.design(request), timeout=effective_timeout
        )
        violations = validate_topology(
            topology,
            contracts=contracts,
            mandatory=mandatory,
            budget=budget,
            node_costs=node_costs,
        )
    except TimeoutError:
        events.append(
            LedgerEvent(kind="graph_design_fallback", payload={"reason": "timeout"})
        )
        return DesignOutcome(topology=None, events=tuple(events))
    except Exception as exc:  # noqa: BLE001 -- 설계자·검증 어느 쪽에서 나든
        # (InvalidDesignPayload 뿐 아니라 모델 클라이언트가 던지는 임의의
        # 예외, 설계자가 계약을 어기고 None 을 돌려줘 validate_topology 가
        # 그 안에서 죽는 경우까지) 사유를 실어 폴백한다. 여기서 조용히
        # 삼키면 "이벤트 없는 폴백은 성공과 구별되지 않는다"는 이 모듈의
        # 존재 이유가 이 한 줄에서 깨진다. `asyncio.CancelledError` 는
        # `BaseException` 이라 이 절에 잡히지 않고 그대로 전파된다 -- 취소
        # 신호를 폴백으로 오인해 삼키면 안 되기 때문이다.
        events.append(
            LedgerEvent(
                kind="graph_design_fallback",
                payload={"reason": f"{type(exc).__name__}: {exc}"},
            )
        )
        return DesignOutcome(topology=None, events=tuple(events))

    if violations:
        events.append(
            LedgerEvent(
                kind="graph_design_rejected",
                payload={
                    "violations": tuple(
                        {"rule": v.rule, "node": v.node, "detail": v.detail}
                        for v in violations
                    )
                },
            )
        )
        return DesignOutcome(topology=None, events=tuple(events))

    events.append(
        LedgerEvent(
            kind="graph_design_accepted",
            payload={
                "nodes": topology.nodes,
                "topology_hash": topology_hash(topology),
            },
        )
    )
    return DesignOutcome(topology=topology, events=tuple(events))


def topology_hash(topology: GraphTopology) -> str:
    """토폴로지의 **논리적** 정체성을 나타내는 안정적 해시.

    **공개 함수인 이유:** 설계된 run 과 정적 run 을 이 해시로 조인한다
    (§14.3 G2-e). 정적 경로가 자기 산식을 따로 두면 두 값은 다르기만 하고
    아무도 그것이 틀렸다는 것을 알 수 없다 -- 해시의 실패는 조용하다.
    그래서 산식을 하나로 두고 양쪽이 이 함수를 부른다.

    노드가 나열된 순서, 엣지가 나열된 순서는 우연이다 -- 설계 서브에이전트가
    같은 그래프를 두 번 제안해도 모델이 그때그때 다른 순서로 JSON 을 낼 수
    있다. 튜플이 도착한 순서 그대로 해시하면 논리적으로 동일한 두 설계가
    다른 해시를 받아, 스펙 §7-5 가 원하는 "토폴로지 해시로 설계된 run 과
    정적 run 을 비교" 가 무의미해진다. 그래서 정렬된 노드 집합과 정렬된 엣지
    집합 위에서 계산한다.

    `loop_bounds` 도 포함한다 -- 노드·엣지 집합이 완전히 같아도 반복 상한이
    다르면 실행 시 실제로 다른 그래프다(같은 사이클이 3회로 도는 설계와 5회로
    도는 설계는 도달 가능한 상태 공간이 다르다). 그래서 이 필드도 논리적
    정체성의 일부로 본다.
    """

    canonical = {
        "nodes": sorted(topology.nodes),
        "edges": sorted(topology.edges),
        "loop_bounds": sorted(topology.loop_bounds.items()),
    }
    encoded = json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:_TOPOLOGY_HASH_HEX_LENGTH]

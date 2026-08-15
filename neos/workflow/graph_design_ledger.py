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
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from neos.config.settings import settings
from neos.workflow.contracts import NodeContract
from neos.workflow.graph_designer import DesignRequest, GraphDesigner
from neos.workflow.topology import GraphTopology, validate_topology


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
    # 기본값이 안전한 이유는 이 함수의 신중함이 아니라, `validate_topology` 의
    # `empty_topology` 규칙이 노드 0개인 설계를 `mandatory` 목록과 무관하게
    # 무조건 거부하기 때문이다(topology.py 참조). 그 규칙이 없다면
    # `{"nodes": [], "edges": []}` 처럼 `parse_topology` 는 통과하지만
    # 아무것도 하지 않는 설계가 여기서도 위반 0개로 승인됐을 것이다.
    # `mandatory` 를 "필수 노드는 없어도 그만" 으로 넓히고 싶다면, 그 전에
    # `empty_topology` 가 여전히 무조건 검사되는지부터 확인해야 한다.
    mandatory: Sequence[str] = (),
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
            topology, contracts=contracts, mandatory=mandatory
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
            payload={"nodes": topology.nodes},
        )
    )
    return DesignOutcome(topology=topology, events=tuple(events))

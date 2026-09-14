"""승인 재개용 그래프 복원.

설계된 run 이 승인 게이트에서 멈추면, 재개는 **멈출 때와 같은 토폴로지** 위에서
일어나야 한다. 설계된 그래프는 호출 스코프의 ephemeral 객체라 캐시되지 않으므로
(G2 스펙 §2.3 -- 공유 인스턴스에 두면 요청 간 경쟁한다), 상태에 실린 토폴로지로
**다시 짓는다.**

**정적으로 흐르는 경로가 없다.** 복원할 수 없으면 예외를 올리고 호출자가 거부한다.
정적 그래프로 재개하면 LangGraph 는 체크포인트의 채널을 읽고 자기 간선을 따라
계속 가므로, 사용자에게는 승인이 처리된 것으로 보이면서 설계가 의도한 것과 다른
파이프라인이 돈다 -- §3.2가 이 저장소의 관통 주제로 적은 "모든 실패가 성공처럼
보였다" 의 재개 판이다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.graph_design_ledger import _DEFAULT_MUST_WRITE
from neos.workflow.topology import (
    TopologyPayloadError,
    topology_from_payload,
    validate_topology,
)

if TYPE_CHECKING:
    from neos.workflow.graph import MultiAgentWorkflow


class ResumeGraphUnavailable(Exception):
    """이 스레드를 지금 재개할 수 없다.

    `reason` 은 사람이 읽을 사유이며 로그와 응답에 그대로 실린다. 호출자는
    이것을 503 으로 바꾼다 -- "요청이 틀렸다" 가 아니라 "서버가 지금 이 스레드를
    재개할 수 없다" 이고, 계약을 되돌리는 배포가 나가면 같은 요청이 성공한다.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def resume_graph_for(
    state_values: Mapping[str, Any],
    *,
    workflow: "MultiAgentWorkflow",
    checkpointer: Any,
) -> Any:
    """재개에 쓸 컴파일된 그래프를 돌려준다.

    정적 run(`execution_topology` 가 없거나 None)이면 정적 그래프를 그대로
    돌려준다 -- 지금 동작이며 바꾸지 않는다.
    """
    from neos.workflow.graph import _INTERRUPT_GATED_NODES, build_ephemeral_workflow

    payload = state_values.get("execution_topology")
    if payload is None:
        return workflow.graph

    try:
        topology = topology_from_payload(payload)
    except TopologyPayloadError as error:
        raise ResumeGraphUnavailable(
            f"stored topology payload could not be read: {error}"
        ) from error

    # `build_ephemeral_workflow` 는 재검증하지 않는다 -- 자기 독스트링이 "승인된
    # 토폴로지만 들어온다는 전제 위에 서 있다" 고 적는다. 그 전제는 설계 직후에는
    # 참이고 재개 시점에는 참이 아니다: 멈춘 뒤 배포가 노드를 없애거나 requires 를
    # 바꿀 수 있다. LLM 을 쓰지 않으므로 값싸다.
    #
    # `must_write=_DEFAULT_MUST_WRITE` 를 넘기는 이유: `design_graph_or_fallback`
    # (그래프를 처음 승인한 자리)이 검증할 때 정확히 이 조건으로 검증했다
    # (`graph_design_ledger.py` 의 기본값). 재검증이 다른 조건으로 하면 "설계
    # 시점엔 통과했는데 지금은 통과 못 한다" 는 판정이 더 이상 "계약이 바뀌었다"
    # 만을 뜻하지 않게 되고, "애초에 검증 조건이 달랐다" 는 잡음이 섞인다 --
    # 이 재검증이 존재하는 유일한 이유(배포 드리프트 탐지)를 흐린다. 다음
    # 사람이 "이 인자 없어도 되지 않나" 하고 지우지 않도록 이유를 남긴다.
    # 트랙 I: 정적 계약에 없는 노드가 있으면 서브에이전트 템플릿 노드일 수 있다.
    # 플래그가 꺼졌으면 재개하지 않는다 -- 템플릿을 정적 노드처럼 지으면 자리표시
    # 핸들러가 터지고, 빼고 지으면 다른 그래프로 재개한다. 켜져 있으면 템플릿
    # 계약을 합쳐 재검증한다(템플릿이 사라졌으면 `missing_contract` 로 503).
    # 저장된 페이로드는 이미 전개돼 있다 -- 다시 전개하지 않는다.
    contracts = NODE_CONTRACTS
    subagent_host = None
    extra_nodes = sorted(set(topology.nodes) - set(NODE_CONTRACTS))
    if extra_nodes:
        from neos.config.settings import settings

        if not settings.config.workflow.subagent_nodes_enabled:
            raise ResumeGraphUnavailable(
                f"stored topology has nodes outside the static contracts {extra_nodes} "
                "and workflow.subagent_nodes_enabled is off"
            )
        try:
            from neos.workflow.subagent_nodes import merged_contracts

            contracts = merged_contracts(NODE_CONTRACTS)
            if set(extra_nodes) & set(contracts):
                subagent_host = workflow._build_subagent_host(None)
        except Exception as error:  # noqa: BLE001
            raise ResumeGraphUnavailable(
                f"subagent node host unavailable: {type(error).__name__}: {error}"
            ) from error

    violations = validate_topology(
        topology, contracts=contracts, must_write=_DEFAULT_MUST_WRITE
    )
    if violations:
        raise ResumeGraphUnavailable(
            f"stored topology is no longer valid against the current contracts: {violations}"
        )

    # `interrupt_before` 는 저장하지 않고 다시 계산한다 -- 저장하면 게이트 정책이
    # 바뀌었을 때 옛 목록으로 재개한다.
    interrupt_before = sorted(set(topology.nodes) & _INTERRUPT_GATED_NODES)

    try:
        return build_ephemeral_workflow(
            workflow,
            topology,
            checkpointer=checkpointer,
            interrupt_before=interrupt_before,
            subagent_host=subagent_host,
        )
    except Exception as error:  # noqa: BLE001 -- 어떤 실패든 재개는 거부다
        raise ResumeGraphUnavailable(
            f"could not rebuild the designed graph: {type(error).__name__}: {error}"
        ) from error

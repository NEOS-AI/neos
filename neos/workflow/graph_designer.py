"""설계 서브에이전트가 낼 수 있는 출력의 계약과, 그 JSON 을 신뢰 가능한
`GraphTopology` 로 바꾸는 파서를 정의한다.

Task 1-5 는 노드 계약(`NodeContract`)과 토폴로지 검증기(`validate_topology`)를
만들었다. 이 태스크는 그 사이에 서브에이전트 하나를 끼워 넣는다 -- 서브에이전트는
**토폴로지만** 낸다. 코드를 쓰지 않고, 자신의 산출물이 쓸만한지도 판단하지
않는다. `parse_topology` 가 유일하게 보는 것은 "이게 형식에 맞고(shape) 실존하는
이름만 가리키는가(vocabulary)" 뿐이다. 그 토폴로지가 START 에서 모든 노드에
닿는지, requires 가 충족되는지, 예산 안에 드는지 같은 의미론적 타당성
(soundness)은 여기서 절대 보지 않는다 -- `validate_topology` 가 그 판단을 하는
별도의 관문이며, 설계자 자신이 그 관문을 겸하지 않는다.

`parse_topology` 는 이 시스템에서 LLM 의 자유 텍스트가 처음으로 "시스템이 그대로
행동하는 대상"으로 바뀌는 경계다. 그래서 애매한 입력을 최선을 다해 되살리는
대신(coerce) 거부한다(reject): 알 수 없는 노드 이름, 형식이 어긋난 엣지,
잘못된 타입, 누락된 키는 전부 `InvalidDesignPayload` 로 즉시 실패한다. 나쁜
엣지 하나를 조용히 버리고 넘어가는 파서는, 아예 예외를 던지는 파서보다 나쁘다
-- 남은 토폴로지가 겉보기엔 멀쩡해 보이기 때문이다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from neos.workflow.contracts import NodeContract
from neos.workflow.topology import END, START, GraphTopology

_PROMPT_PATH = Path(__file__).parent / "prompts" / "graph_design.md"
# 엣지 하나는 [source, target] 정확히 두 원소여야 한다. 그 외 길이는 형식 오류다.
_EDGE_ENDPOINT_COUNT = 2


class InvalidDesignPayload(ValueError):
    """서브에이전트의 JSON 출력이 형식(shape) 또는 어휘(vocabulary) 규칙을 어겼다.

    메시지는 항상 안정적인 snake_case 식별자로 시작한다 (`unknown_node`,
    `nodes_not_list`, ...) -- 호출부가 `TopologyViolation.rule` 과 같은 방식으로
    실패 종류를 매칭할 수 있게 하기 위해서다.
    """


@dataclass(frozen=True, slots=True)
class DesignRequest:
    """설계 서브에이전트에게 넘기는 입력.

    `catalog` 는 이번 설계에서 고를 수 있는 노드 계약 전체다 -- 서브에이전트가
    실존하지 않는 노드를 지어내지 못하게, 프롬프트에 그대로 나열해 넘긴다.
    """

    query: str
    catalog: tuple[NodeContract, ...]
    budget: int


class GraphDesigner(Protocol):
    """토폴로지 하나를 설계해 돌려주는 서브에이전트가 만족해야 할 계약.

    설계자는 자신이 낸 토폴로지를 검증하지 않는다 -- `validate_topology` 를
    호출하는 것은 이 프로토콜의 구현체가 아니라 호출자(이후 태스크)의 몫이다.
    설계와 승인을 같은 주체가 겸하지 않도록, 그 경계를 여기 타입으로 못박는다.
    """

    async def design(self, request: DesignRequest) -> GraphTopology: ...


class FakeGraphDesigner:
    """주어진 토폴로지를 그대로 돌려주는 결정론적 fake.

    실제 LLM 호출 없이 이후 태스크(그래프 빌더, 승인 루프 등)를 테스트하기
    위한 테스트 더블이다. `design_calls` 로 호출 횟수를 관찰할 수 있어, "재시도
    루프가 정확히 N 번만 설계자를 불렀는가" 같은 단언에도 쓸 수 있다.
    """

    def __init__(self, topology: GraphTopology) -> None:
        self._topology = topology
        self.design_calls = 0

    async def design(self, request: DesignRequest) -> GraphTopology:
        self.design_calls += 1
        return self._topology


def load_graph_design_prompt() -> str:
    """설계 서브에이전트에게 보낼 프롬프트 원문을 파일에서 그대로 읽는다.

    프롬프트 문구를 파이썬 문자열 리터럴로 흩어 놓으면 매직 문자열 금지
    규칙을 어기게 된다. 실제 문구는 `prompts/graph_design.md` 하나에만 있고,
    이 함수는 그 파일을 읽어 올 뿐 내용을 알지 못한다.
    """

    return _PROMPT_PATH.read_text(encoding="utf-8")


def parse_topology(payload: Mapping, *, known_nodes: frozenset[str]) -> GraphTopology:
    """서브에이전트의 JSON 출력을 `GraphTopology` 로 바꾼다.

    여기서 검사하는 것은 형식(shape)과 어휘(vocabulary) 뿐이다:
    - `nodes` 가 문자열의 리스트인가.
    - `edges` 가 [source, target] 두 원소짜리 리스트들의 리스트인가.
    - 등장하는 모든 이름(노드 이름, 엣지 양 끝)이
      `known_nodes ∪ {START, END}` 안에 있는가.

    이 토폴로지가 START 에서 모든 노드에 닿는지, requires 가 충족되는지,
    예산 안에 드는지 같은 의미론적 타당성은 절대 보지 않는다 -- 그건
    `validate_topology` 의 몫이며, 설계자가 자신의 산출물을 스스로 승인하지
    못하게 하려는 의도적 분리다.

    `known_nodes` 는 카탈로그(실제 시스템에 존재하는 노드)를 뜻한다. 이 검사는
    "서브에이전트가 없는 노드를 지어냈는가" 만 본다 -- 지어낸 게 아니라 실존하는
    노드라도 이 토폴로지의 `nodes` 목록 밖에서 엣지에만 등장하는 내부
    불일치는 `validate_topology` 의 `unknown_node` 규칙이 별도로 잡는다
    (그 규칙은 카탈로그가 아니라 이 토폴로지 자신의 `nodes` 를 기준으로 삼는다).
    """

    if not isinstance(payload, Mapping):
        raise InvalidDesignPayload(
            f"payload_not_mapping: payload 는 매핑이어야 하는데 "
            f"{type(payload).__name__} 이다"
        )

    for key in ("nodes", "edges"):
        if key not in payload:
            raise InvalidDesignPayload(f"missing_key: '{key}' 키가 없다")

    nodes = _parse_nodes(payload["nodes"])
    edges = _parse_edges(payload["edges"])

    vocabulary = known_nodes | {START, END}
    unknown: list[str] = []
    seen: set[str] = set()
    for name in nodes:
        if name not in known_nodes and name not in seen:
            seen.add(name)
            unknown.append(name)
    for source, target in edges:
        for endpoint in (source, target):
            if endpoint not in vocabulary and endpoint not in seen:
                seen.add(endpoint)
                unknown.append(endpoint)

    if unknown:
        raise InvalidDesignPayload(
            "unknown_node: 설계자가 실존하지 않는 노드를 가리켰다 -- "
            + ", ".join(unknown)
        )

    return GraphTopology(nodes=nodes, edges=edges)


def _parse_nodes(raw: object) -> tuple[str, ...]:
    """`nodes` 필드가 문자열 리스트인지 확인하고 튜플로 정규화한다."""

    if not isinstance(raw, list):
        raise InvalidDesignPayload(
            f"nodes_not_list: 'nodes' 는 리스트여야 하는데 {type(raw).__name__} 이다"
        )
    nodes: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str):
            raise InvalidDesignPayload(
                f"node_not_string: nodes[{index}] 는 문자열이어야 하는데 "
                f"{type(item).__name__} 이다"
            )
        nodes.append(item)
    return tuple(nodes)


def _parse_edges(raw: object) -> tuple[tuple[str, str], ...]:
    """`edges` 필드가 [source, target] 두 원소짜리 리스트들의 리스트인지 확인한다."""

    if not isinstance(raw, list):
        raise InvalidDesignPayload(
            f"edges_not_list: 'edges' 는 리스트여야 하는데 {type(raw).__name__} 이다"
        )
    edges: list[tuple[str, str]] = []
    for index, item in enumerate(raw):
        # 문자열도 `Sequence` 라서 먼저 걸러낸다 -- 안 그러면 "ab" 같은 문자열이
        # ['a', 'b'] 로 오인되어 엣지 하나로 통과해 버린다.
        if isinstance(item, str) or not isinstance(item, Sequence):
            raise InvalidDesignPayload(
                f"edge_not_pair: edges[{index}] 는 [source, target] 형태여야 "
                f"하는데 {type(item).__name__} 이다"
            )
        endpoints = list(item)
        if len(endpoints) != _EDGE_ENDPOINT_COUNT:
            raise InvalidDesignPayload(
                f"edge_not_pair: edges[{index}] 는 정확히 "
                f"{_EDGE_ENDPOINT_COUNT}개 원소를 가져야 하는데 {len(endpoints)}개다"
            )
        source, target = endpoints
        if not isinstance(source, str) or not isinstance(target, str):
            raise InvalidDesignPayload(
                f"edge_endpoint_not_string: edges[{index}] 의 원소는 문자열이어야 한다"
            )
        edges.append((source, target))
    return tuple(edges)

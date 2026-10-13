"""정적 그래프의 `GraphTopology` -- 배선 표(`neos.workflow.wiring`)에서 낸다.

예전에는 `_create_workflow_graph` 의 `workflow.add_*` 호출을 AST 로 읽었다. 그 소스가
배선 표를 조립하는 몇 줄이 된 뒤로는 표가 원천이다(spec 2026-10-13 §4.1).
`flags` 에 없는 키는 켜짐 -- 가장 넓은 그래프가 가장 많은 위반을 드러낸다.
"""

from collections.abc import Mapping

from neos.workflow.topology import GraphTopology
from neos.workflow.wiring import resolve_wiring, topology_of


def static_topology(*, flags: Mapping[str, bool] | None = None) -> GraphTopology:
    return topology_of(resolve_wiring(flags))

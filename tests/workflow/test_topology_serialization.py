"""토폴로지 JSON 왕복 -- 해시가 보존되면 무손실이다.

필드를 손으로 나열해 비교하지 않는 이유는 그 목록이 `GraphTopology` 에 필드가
늘어나는 순간 낡기 때문이다. `topology_hash` 는 논리적 정체성을 재므로, 해시가
같으면 그래프로서 같다.
"""

import pytest

from neos.workflow.graph_design_ledger import topology_hash
from neos.workflow.topology import (
    GRAPH_ENTRY_WRITES,
    GraphTopology,
    TopologyPayloadError,
    topology_from_payload,
    topology_to_payload,
)

_TOPOLOGY = GraphTopology(
    nodes=("query_classifier", "response_generator"),
    edges=(
        ("__start__", "query_classifier"),
        ("query_classifier", "response_generator"),
        ("response_generator", "__end__"),
    ),
    loop_bounds={"query_classifier": 3},
    initial_writes=GRAPH_ENTRY_WRITES,
)


def test_the_round_trip_preserves_the_hash():
    restored = topology_from_payload(topology_to_payload(_TOPOLOGY))

    assert topology_hash(restored) == topology_hash(_TOPOLOGY)


def test_the_payload_survives_json():
    import json

    restored = topology_from_payload(json.loads(json.dumps(topology_to_payload(_TOPOLOGY))))

    assert topology_hash(restored) == topology_hash(_TOPOLOGY)


def test_tuples_come_back_as_tuples():
    """JSON 은 list 만 안다. 되돌려 놓지 않으면 `GraphTopology` 가
    hashable 하지 않게 되고 frozen dataclass 의 의미가 깨진다."""
    restored = topology_from_payload(topology_to_payload(_TOPOLOGY))

    assert isinstance(restored.nodes, tuple)
    assert all(isinstance(edge, tuple) for edge in restored.edges)


def test_a_payload_missing_nodes_is_rejected():
    with pytest.raises(TopologyPayloadError):
        topology_from_payload({"edges": []})


def test_a_malformed_edge_is_rejected():
    """간선이 2-튜플이 아니면 그래프를 지을 수 없다. 여기서 막지 않으면
    `build_ephemeral_workflow` 안에서 알아보기 어려운 모양으로 터진다."""
    with pytest.raises(TopologyPayloadError):
        topology_from_payload({"nodes": ["a"], "edges": [["a"]]})

import pytest

# graph.py 를 임포트해야 그 안의 노드 메서드에 붙은 @node_contract 데코레이터가
# 실행되어 NODE_CONTRACTS 가 채워진다. neos/workflow/__init__.py 는 무거운 graph
# 의존성을 일부러 지연 로딩하므로(contracts/enums/state 만 임포트해서는 그래프
# 모듈이 로드되지 않는다), 여기서 명시적으로 임포트해 부작용을 일으킨다.
import neos.workflow.graph  # noqa: F401
from neos.workflow.contracts import (  # noqa: F401 (NodeContract는 공개 인터페이스 문서화용)
    NODE_CONTRACTS,
    NodeContract,
    state_keys_read,
)
from neos.workflow.enums import WorkflowNode
from neos.workflow.state import AgentState


PILOT_NODES = (
    WorkflowNode.QUERY_CLS.value,
    WorkflowNode.SEARCH_ORCHESTRATOR.value,
    WorkflowNode.RESULT_INTEGRATOR.value,
)


def test_pilot_nodes_declare_contracts() -> None:
    for name in PILOT_NODES:
        assert name in NODE_CONTRACTS, f"{name} 에 계약 선언이 없다"


@pytest.mark.parametrize("name", PILOT_NODES)
def test_declared_keys_exist_on_agent_state(name: str) -> None:
    """오타난 키를 선언하면 검증기가 허구를 검사하게 된다."""
    contract = NODE_CONTRACTS[name]
    fields = set(AgentState.__annotations__)
    unknown = (contract.reads | contract.writes | contract.requires) - fields
    assert unknown == set(), f"{name}: AgentState 에 없는 키 {sorted(unknown)}"


@pytest.mark.parametrize("name", PILOT_NODES)
def test_requires_is_a_subset_of_reads(name: str) -> None:
    """요구하는데 읽지 않는 키는 선언이 잘못된 것이다."""
    contract = NODE_CONTRACTS[name]
    assert contract.requires <= contract.reads


@pytest.mark.parametrize("name", PILOT_NODES)
def test_declared_reads_cover_what_the_source_actually_reads(name: str) -> None:
    """선언하지 않고 읽는 키가 있으면 검증기가 그 의존을 못 본다.

    그 방향의 드리프트가 정확히 위험하다 -- 검증기는 선언된 것만 검사하므로,
    선언 밖에서 읽는 키는 순서가 틀려도 통과하고 노드는 빈 값으로 조용히 돈다.
    """
    contract = NODE_CONTRACTS[name]
    actual = state_keys_read(contract.handler)
    undeclared = actual - contract.reads
    assert undeclared == set(), f"{name}: 선언되지 않은 읽기 {sorted(undeclared)}"

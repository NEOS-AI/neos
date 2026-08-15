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


def _graph_node_names() -> tuple[str, ...]:
    """graph.py 가 add_node 로 등록하는 노드 이름을 소스에서 뽑는다."""
    import ast
    from pathlib import Path

    import neos.workflow.graph as graph_module

    source = Path(graph_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: set[str] = set()
    for item in ast.walk(tree):
        if (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "add_node"
            and item.args
            and isinstance(item.args[0], ast.Attribute)
            and item.args[0].attr == "value"
        ):
            names.add(item.args[0].value.attr)
    return tuple(sorted(names))


def test_every_graph_node_declares_a_contract() -> None:
    """계약 없는 노드가 하나라도 있으면 검증기는 그 노드의 의존을 못 본다."""
    declared = {
        member.name for member in WorkflowNode if member.value in NODE_CONTRACTS
    }
    missing = set(_graph_node_names()) - declared
    assert missing == set(), f"계약 미선언 노드: {sorted(missing)}"


ALL_NODES = tuple(NODE_CONTRACTS)


def test_pilot_nodes_declare_contracts() -> None:
    for name in ALL_NODES:
        assert name in NODE_CONTRACTS, f"{name} 에 계약 선언이 없다"


@pytest.mark.parametrize("name", ALL_NODES)
def test_declared_keys_exist_on_agent_state(name: str) -> None:
    """오타난 키를 선언하면 검증기가 허구를 검사하게 된다."""
    contract = NODE_CONTRACTS[name]
    fields = set(AgentState.__annotations__)
    unknown = (contract.reads | contract.writes | contract.requires) - fields
    assert unknown == set(), f"{name}: AgentState 에 없는 키 {sorted(unknown)}"


@pytest.mark.parametrize("name", ALL_NODES)
def test_requires_is_a_subset_of_reads(name: str) -> None:
    """요구하는데 읽지 않는 키는 선언이 잘못된 것이다."""
    contract = NODE_CONTRACTS[name]
    assert contract.requires <= contract.reads


@pytest.mark.parametrize("name", ALL_NODES)
def test_declared_reads_cover_what_the_source_actually_reads(name: str) -> None:
    """선언하지 않고 읽는 키가 있으면 검증기가 그 의존을 못 본다.

    그 방향의 드리프트가 정확히 위험하다 -- 검증기는 선언된 것만 검사하므로,
    선언 밖에서 읽는 키는 순서가 틀려도 통과하고 노드는 빈 값으로 조용히 돈다.
    """
    contract = NODE_CONTRACTS[name]
    actual = state_keys_read(contract.handler)
    undeclared = actual - contract.reads
    assert undeclared == set(), f"{name}: 선언되지 않은 읽기 {sorted(undeclared)}"


@pytest.mark.parametrize("name", ALL_NODES)
def test_a_contract_the_extractor_cannot_reach_is_marked_as_hand_curated(
    name: str,
) -> None:
    """reads 중 추출기가 소스에서 확인하지 못하는 키가 하나라도 있으면, 그 계약의
    드리프트 가드는 그 키에 대해서는 **작동하지 않는다.** 조용히 통과시키지 말고
    손으로 큐레이션했다고 명시하게 한다.

    Task 1 리뷰가 변조 테스트로 증명한 구멍이다 -- reads 를 빈 집합으로 바꿔도
    통과했다. 처음 이 테스트는 `reads` 전체가 안 보일 때만(완전 실명) 걸렸는데,
    그러면 9개 중 4개만 보여도 통과해 나머지 5개가 미검증인 채로 숨었다
    (Task 2 fix round 1, 코드 리뷰가 잡아냄). 그래서 부분 실명 -- `reads` 의
    일부만 추출기 시야 밖에 있는 경우 -- 도 걸리도록 `reads - state_keys_read(...)`
    가 비어 있는지로 판정한다.
    """
    contract = NODE_CONTRACTS[name]
    unverified = contract.reads - state_keys_read(contract.handler)
    if unverified:
        assert contract.hand_curated, (
            f"{name}: 추출기가 다음 read를 소스에서 확인하지 못했다: "
            f"{sorted(unverified)}. 그 키들에는 드리프트 가드가 공허하므로 "
            f"hand_curated=True 로 명시하고 근거를 주석에 남길 것"
        )

from neos.workflow.contracts import NODE_CONTRACTS
from neos.workflow.topology import validate_topology
from neos.workflow.topology_export import static_topology


def test_the_static_graph_satisfies_its_own_contracts() -> None:
    """손으로 쓴 배선이 자기 계약을 만족하는지 증명한다.

    실패하면 검증기 버그이거나, 계약 선언이 틀렸거나, **정적 그래프에 실제 순서
    버그가 있는 것**이다. 셋 다 고칠 가치가 있다.
    """
    violations = validate_topology(static_topology(), contracts=NODE_CONTRACTS)
    assert violations == (), "\n".join(
        f"{v.rule} @ {v.node}: {v.detail}" for v in violations
    )

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
    state_keys_written,
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


@pytest.mark.parametrize("name", ALL_NODES)
def test_declared_writes_cover_what_the_source_actually_writes(name: str) -> None:
    """선언하지 않고 쓰는 키가 있으면 검증기가 그 키를 하류에 보장하지 못한다.

    `_guaranteed_keys`(topology.py)는 `writes` 만 보고 START 에서 각 노드에
    이르는 모든 경로에서 어떤 키가 이미 쓰였는지 계산한다 -- 소스가 실제로
    쓰는 키를 `writes` 에 선언하지 않으면, 그 키가 실제로는 있는데도 이
    검증기 눈에는 보장되지 않는 것으로 남는다. `state_keys_read` 짝인
    `state_keys_written` 은 위임 체인은 따라가지 않지만(더 보수적이다),
    `return {"x": ...}` 형태의 리터럴 dict 반환과 `state["x"] = ...` 대입은
    본다 -- 그 범위 안에서 조용히 빠뜨린 선언은 여기서 잡는다.
    """
    contract = NODE_CONTRACTS[name]
    actual = state_keys_written(contract.handler)
    undeclared = actual - contract.writes
    assert undeclared == set(), f"{name}: 선언되지 않은 쓰기 {sorted(undeclared)}"


@pytest.mark.parametrize("name", ALL_NODES)
def test_a_contract_whose_writes_the_extractor_cannot_verify_is_marked_hand_curated(
    name: str,
) -> None:
    """writes 중 추출기가 소스에서 확인하지 못하는 키가 하나라도 있으면, `writes` 가
    선언한 만큼 실제로 쓰이는지에 대한 드리프트 가드는 그 키에 대해서는
    **작동하지 않는다.** `hand_curated` 가 reads 쪽의 이 구멍을 명시하는 것과
    똑같이, `writes_hand_curated` 가 writes 쪽을 명시해야 한다.

    이 저장소의 노드 30개 중 16개는 한 줄 위임(`return await
    self.<attr>.<method>(state)`)이다 -- `state_keys_written` 은 위임 체인을
    따라가지 않으므로(이번 라운드는 인라인 구현만 커버) 그런 노드는 선언한
    writes 를 소스에서 전혀 확인할 수 없고, 예외 없이 `writes_hand_curated`
    가 True 여야 한다.
    """
    contract = NODE_CONTRACTS[name]
    unverified = contract.writes - state_keys_written(contract.handler)
    if unverified:
        assert contract.writes_hand_curated, (
            f"{name}: 추출기가 다음 write를 소스에서 확인하지 못했다: "
            f"{sorted(unverified)}. 그 키들에는 드리프트 가드가 공허하므로 "
            f"writes_hand_curated=True 로 명시하고 근거를 주석에 남길 것"
        )


@pytest.mark.parametrize("name", ALL_NODES)
def test_a_writes_contract_the_extractor_can_verify_is_not_marked_hand_curated(
    name: str,
) -> None:
    """반대 방향도 고정한다 -- 낡은 면제는 조용히 가드를 끈다.

    `writes_hand_curated=True` 는 "이 노드의 writes 는 기계가 못 본다" 는
    **주장**이고, 그 주장이 참인 동안 위 테스트는 그 노드를 검사하지 않는다.
    주장이 낡으면(추출기가 좋아지거나 노드가 단순해지면) 실제로는 검사할 수
    있는 노드가 계속 면제된 채로 남고, 그 사이에 생긴 드리프트는 아무도
    잡지 못한다.

    §14.4 를 좁히면서 실제로 그 상태가 됐다 -- 위임 체인 확장 뒤 13개 노드의
    플래그가 한꺼번에 낡았다. 한 방향만 고정하면 그런 순간이 조용히 지나간다.
    """
    contract = NODE_CONTRACTS[name]
    unverified = contract.writes - state_keys_written(contract.handler)
    if not unverified:
        assert not contract.writes_hand_curated, (
            f"{name}: 추출기가 선언된 writes 를 전부 확인할 수 있는데 "
            f"writes_hand_curated=True 로 면제돼 있다. 면제를 지우면 이 노드가 "
            f"드리프트 가드 안으로 들어온다"
        )


# --- requires 의 기계 검증 (§14.4 의 0/30) -----------------------------------
#
# `requires` 는 세 필드 중 유일하게 기계 검증이 **0개**였다 -- `requires ⊆ reads`
# 만 강제되고 나머지는 전부 사람 판단이었다. 그런데 `_guaranteed_keys` 는 바로
# 이 필드로 `unsatisfied_requires` 규칙 전체를 계산한다: 가장 덜 검증되는 필드가
# 가장 많이 쓰인다.
#
# 위험 방향이 `reads`·`writes` 와 또 다르다. `requires` 는 **과소 선언이
# 위험**하다 -- 필요한 키를 안 적으면 검증기가 그 키의 경로 보장을 아예 검사하지
# 않고, 그 노드는 빈 값을 읽거나(조용한 저하) KeyError 로 죽는다.
#
# 기계가 증명할 수 있는 것은 그 하한이다: `state["k"]` 로 읽는 키(없으면 즉시
# KeyError)는 셋 중 하나여야 한다 -- requires 로 선언됐거나, 자기가 먼저 썼거나,
# 그래프 호출자가 진입 시 채워 주거나. 셋 다 아니면 그것은 판단이 아니라 결함이다.
#
# `requires` 가 무엇을 **의미**하는지(= "있기만 하면 되는가, 의미 있는 값이어야
# 하는가")까지는 기계가 못 답한다. 그 부분은 여전히 사람 판단이고, 아래 두 표를
# 구별하는 테스트가 그 경계를 못박는다.

import ast as _ast
import inspect as _inspect
import textwrap as _textwrap

from neos.workflow.contracts import state_keys_hard_read
from neos.workflow.graph import MultiAgentWorkflow
from neos.workflow.topology import GRAPH_ENTRY_WRITES


def _entry_initialized_keys() -> frozenset[str]:
    """`_create_initial_state` 가 실제로 채우는 키를 소스에서 뽑는다.

    손으로 적은 목록을 두지 않는 이유는 이 저장소가 CA12 에서 이미 치른
    대가다 -- 같은 사실을 적은 표가 둘이면 언젠가 한쪽만 고쳐진다.
    """
    source = _textwrap.dedent(
        _inspect.getsource(MultiAgentWorkflow._create_initial_state)
    )
    keys: set[str] = set()
    for item in _ast.walk(_ast.parse(source)):
        if (
            isinstance(item, _ast.Call)
            and isinstance(item.func, _ast.Name)
            and item.func.id == "AgentState"
        ):
            keys.update(kw.arg for kw in item.keywords if kw.arg)
    return frozenset(keys)


ENTRY_INITIALIZED = _entry_initialized_keys()


@pytest.mark.parametrize("name", ALL_NODES)
def test_a_key_read_without_a_default_is_required_written_or_present_at_entry(
    name: str,
) -> None:
    """`state["k"]` 는 없으면 KeyError 다 -- 그 위험이 어디선가 덮여야 한다.

    세 가지가 덮을 수 있다: `requires` 선언(검증기가 경로 보장을 검사한다),
    같은 핸들러가 먼저 쓴 것(`research_continuation` 이 40번 줄에서 쓰고 57번
    줄에서 읽는 형태), 그래프 호출자의 진입 초기화. 어느 것도 아니면 그 키는
    **어떤 경로에서는 없을 수 있는데 기본값 없이 읽히는** 키다.
    """
    contract = NODE_CONTRACTS[name]
    conditional = frozenset().union(
        *contract.requires_unless.values(), frozenset()
    )
    covered = (
        contract.requires
        | conditional
        | state_keys_written(contract.handler)
        | ENTRY_INITIALIZED
    )
    uncovered = state_keys_hard_read(contract.handler) - covered
    assert uncovered == set(), (
        f"{name}: {sorted(uncovered)} 를 `state[...]` 로 기본값 없이 읽는데 "
        "requires 에도 없고, 자기가 쓰지도 않고, 진입 초기화도 아니다 -- "
        "그 경로로 들어오면 KeyError 다"
    )


def test_the_entry_table_and_the_guarantee_table_answer_different_questions() -> None:
    """진입 초기화 목록과 `GRAPH_ENTRY_WRITES` 는 **다른 질문의 답**이다.

    `_create_initial_state` 는 58개를 채우지만 `GRAPH_ENTRY_WRITES` 는 4개만
    선언한다. 이 격차는 결함이 아니라 의도다 -- 나머지는 `[]`/`None` 로
    초기화되는 빈 누적 필드라 **존재하지만 의미가 없다.**

    두 질문을 구별한다:
    - 진입 초기화: "키가 있는가" -> KeyError 위험을 덮는다 (위 테스트)
    - `GRAPH_ENTRY_WRITES`: "의미 있는 값이 있는가" -> 조용한 저하를 덮는다

    이 테스트가 막는 것은 다음 사람이 "격차를 메우는" 것이다. `GRAPH_ENTRY_WRITES`
    를 진입 초기화 전체로 넓히면 `analysis_results=[]` 가 "보장됨" 이 되고,
    §14.0 이 이 저장소의 관통 주제로 적은 "조용히 빈 산출물" 을 검증기가 더는
    잡지 못한다 -- G1-a 가 겨눈 실패가 통째로 사라진다.
    """
    assert GRAPH_ENTRY_WRITES < ENTRY_INITIALIZED, (
        "GRAPH_ENTRY_WRITES 는 진입 초기화의 진부분집합이어야 한다"
    )
    empty_accumulators = {"analysis_results", "generation_results", "search_results"}
    assert empty_accumulators <= ENTRY_INITIALIZED, (
        "누적 필드는 진입에서 초기화된다 -- 그래서 KeyError 는 안 난다"
    )
    assert not (empty_accumulators & GRAPH_ENTRY_WRITES), (
        "빈 누적 필드를 GRAPH_ENTRY_WRITES 에 넣으면 검증기가 '보장됨' 으로 읽어 "
        "조용한 저하를 더는 잡지 못한다"
    )


def test_the_hard_read_guard_actually_fires_when_nothing_covers_the_key() -> None:
    """위 가드가 **구조적으로 죽어 있지 않은지**를 고정한다.

    실측(2026-09-05): 지금 이 저장소에서 위 파라미터 테스트는 31개 노드 전부에
    대해 즉시 통과하고, 그 이유는 `requires` 가 잘 선언돼서가 아니라
    **`_create_initial_state` 가 58개 키를 전부 채우기 때문**이다. 즉 오늘
    그 가드에서 `requires` 항은 공허하다.

    공허한 가드는 §14.4 가 "검증기가 있다는 사실만으로 안심하게 된다" 고 적은
    바로 그 상태다. 그래서 가드가 **덮이지 않은 키를 실제로 잡는다**는 것을
    여기서 따로 증명한다 -- 앞으로 `AgentState` 에 진입 초기화 없는 키가 생기고
    누군가 그것을 `state["k"]` 로 읽으면 위 테스트가 빨개진다.
    """

    class _Node:
        def handler(self, state):
            # 진입 초기화에도 없고, 자기가 쓰지도 않고, 선언도 안 한 키.
            return state["a_key_nobody_initializes"]

    hard = state_keys_hard_read(_Node.handler)
    assert hard == {"a_key_nobody_initializes"}
    assert not (hard & ENTRY_INITIALIZED), (
        "이 테스트가 성립하려면 그 키가 진입 초기화에 없어야 한다"
    )


def test_a_defaulted_read_is_not_counted_as_a_hard_read() -> None:
    """`state.get("k")` 는 없어도 죽지 않는다 -- 하드 리드가 아니다.

    이 구별이 무너지면 가드가 `.get()` 경로까지 requires 선언을 요구하게 되고,
    그러면 `requires` 가 `reads` 와 같은 것이 되어 두 필드를 나눈 이유가
    사라진다.
    """

    class _Node:
        def handler(self, state):
            state["written"] = 1
            return state.get("soft"), state["hard"]

    assert state_keys_hard_read(_Node.handler) == {"hard"}

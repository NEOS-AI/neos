"""이번 호출이 실제로 쓰는 그래프를 값 하나로 묶는다.

`execute_workflow` 가 그래프를 `self.graph` 에서 읽던 것을 이 값으로
바꾸는 이유는 `graph.py:376-383` 이 이미 적어 뒀다: `MultiAgentWorkflow` 는
오래 살고 요청들이 공유하는 객체라, 질의 하나에 종속된 값을 인스턴스
속성에 얹으면 동시 요청 두 개가 서로의 그래프를 실행한다.

이 모듈은 `graph.py` 를 직접 임포트하지 않는다 -- `compiled: Any` 로
충분해서 `MultiAgentWorkflow` 의 타입이 필요 없다. 다만 `topology_export`
가 모듈 스코프에서 `graph.py` 를 임포트하므로(그 안에서 싱글턴을
인스턴스화한다) 전이 의존은 실제로 존재한다: 이 모듈을 임포트하면
`MultiAgentWorkflow` 도 함께 만들어진다. 이 모듈을 `graph.py` 와 무관한
것으로 읽지 말 것. 다음 태스크가 `graph.py` 에 `from .execution_graph
import ...` 를 추가하면 `graph.py → execution_graph → topology_export →
graph.py` 순환이 생기지만, 이는 깨진 채로 남는 순환이 아니다:
`topology_export` 는 `graph_module` 을 함수 본문 안에서만 쓰고(모듈
로드 시점에는 쓰지 않는다) 파이썬은 `sys.modules` 에 이미 등록된
부분 초기화 모듈을 `from package import submodule` 로 해석하므로
ImportError 없이 통과한다.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from neos.config.settings import settings
from neos.workflow.graph_design_ledger import topology_hash
from neos.workflow.topology_export import _FLAG_ATTR_TO_KEY, static_topology

# `topology_export` 의 플래그 키를 공개 표면으로 다시 내보낸다. 본체가
# `_FLAG_ATTR_TO_KEY` 를 그대로 쓰는 것은 매핑을 두 벌 유지하지 않기
# 위해서고, 이 상수는 **테스트와 바깥 호출자가 private 이름을 임포트하지
# 않게** 하기 위한 것이다.
STATIC_FLAG_KEYS: frozenset[str] = frozenset(_FLAG_ATTR_TO_KEY.values())


@dataclass(frozen=True, slots=True)
class ExecutionGraph:
    """이번 호출이 실행할 그래프와, 그것을 서술하는 데 필요한 전부.

    `nodes` 가 진행 추적의 유일한 근거다(G2-b) -- 손으로 나열한 목록을
    쓰지 않는 이유는 그 목록이 이 그래프를 서술한다는 보장이 없기 때문이다.
    `source` 를 싣는 이유는 로그가 "이 run 이 설계된 것인가" 를 추측하지
    않게 하기 위해서다.
    """

    compiled: Any
    nodes: tuple[str, ...]
    topology_hash: str
    source: Literal["static", "designed"]


def current_static_flags() -> dict[str, bool]:
    """실행 시점 `settings` 를 `topology_export` 의 플래그 키로 옮긴다.

    매핑을 손으로 다시 쓰지 않고 `_FLAG_ATTR_TO_KEY` 를 재사용한다 -- 키가
    하나라도 빠지면 `static_topology` 가 그 자리를 기본값('켬')으로 조용히
    채우고, 실제로 꺼진 기능이 켜진 것으로 계산된 해시가 나온다.
    """

    return {
        key: bool(getattr(settings, attr))
        for attr, key in _FLAG_ATTR_TO_KEY.items()
    }


@lru_cache(maxsize=32)
def _static_topology_facts(flags_items: tuple[tuple[str, bool], ...]) -> tuple[tuple[str, ...], str]:
    """`static_topology` 는 `inspect.getsource` + `ast.parse` 를 돈다 --
    요청마다 하면 안 된다. 플래그 조합은 5비트라 상한이 32개이고, 배포 중
    플래그가 바뀌지 않으므로 실질 1회다. `lru_cache` 를 쓰려고 인자를
    해시 가능한 튜플로 받는다."""

    topology = static_topology(flags=dict(flags_items))
    return topology.nodes, topology_hash(topology)


def static_execution_graph(
    *, compiled: Any, flags: Mapping[str, bool]
) -> ExecutionGraph:
    """정적 그래프를 `ExecutionGraph` 로 감싼다.

    `flags` 를 명시적으로 받는 이유: `static_topology()` 의 기본값은 "전부
    켬" 이고 그것은 **회귀 가드의 의도**("배포 설정과 무관하게 항상 같은
    토폴로지를 검증한다")에 맞춰진 것이다. G2-e 의 의도는 정반대다 -- 그
    run 이 **실제로 쓴** 그래프를 식별해야 조인이 성립한다. 같은 함수를
    다른 의도로 쓰므로 인자를 생략하지 않는다.
    """

    nodes, digest = _static_topology_facts(tuple(sorted(flags.items())))
    return ExecutionGraph(
        compiled=compiled, nodes=nodes, topology_hash=digest, source="static"
    )

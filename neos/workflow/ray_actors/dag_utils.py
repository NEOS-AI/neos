"""DAG 의존성 처리 유틸리티.

RecursiveTaskNode의 metadata["depends_on"] 필드를 파싱하여
동일 레벨에서 병렬 실행 가능한 태스크 그룹을 반환한다.

현재 orchestrator는 depends_on을 무시하고 순차 실행하지만,
이 모듈을 통해 독립 sibling 태스크를 병렬화할 수 있다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Set

if TYPE_CHECKING:
    from neos.workflow.recursive.models import RecursiveTaskNode


def build_execution_levels(subtasks: List["RecursiveTaskNode"]) -> List[List[int]]:
    """subtasks의 depends_on DAG를 레벨별 실행 그룹으로 변환.

    동일 레벨 내 태스크는 의존성이 없으므로 병렬 실행 가능.
    이전 레벨이 모두 완료된 후 다음 레벨을 실행한다.

    Args:
        subtasks: RecursiveTaskNode 리스트. 각 노드의
            metadata["depends_on"]은 0-based 인덱스 리스트.

    Returns:
        레벨별 인덱스 그룹 리스트.
        예: [[0, 1], [2]] → T0·T1 병렬 실행 후 T2 실행.

    Raises:
        ValueError: 순환 의존성 감지 시.

    Examples:
        >>> T = lambda dep: node_with_depends_on(dep)
        >>> build_execution_levels([T([]), T([]), T([0, 1])])
        [[0, 1], [2]]
        >>> build_execution_levels([T([]), T([0]), T([1])])
        [[0], [1], [2]]
    """
    if not subtasks:
        return []

    n = len(subtasks)
    levels: List[int] = [-1] * n

    def _get_level(idx: int, visiting: Set[int]) -> int:
        if idx in visiting:
            raise ValueError(
                f"순환 의존성 감지: subtask 인덱스 {idx}에서 순환 참조 발생"
            )
        if levels[idx] >= 0:
            return levels[idx]

        deps_raw = subtasks[idx].metadata.get("depends_on", [])
        # LLM이 ["0", "1"] 형태의 문자열로 반환할 수 있으므로 int 변환
        deps = [int(d) for d in deps_raw]

        if not deps:
            levels[idx] = 0
            return 0

        visiting = visiting | {idx}  # 불변 복사 (스택 간 오염 방지)
        max_dep_level = max(_get_level(d, visiting) for d in deps)
        levels[idx] = max_dep_level + 1
        return levels[idx]

    for i in range(n):
        _get_level(i, set())

    max_level = max(levels)
    return [[i for i, lv in enumerate(levels) if lv == level] for level in range(max_level + 1)]

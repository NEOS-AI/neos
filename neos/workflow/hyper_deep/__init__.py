"""HyperDeep Recursive Agent 패키지.

ROMA(Recursive Open Meta-Agent) 컴포넌트를 재사용하되,
leaf 노드 실행을 HyperDeepResearchAgent로 교체하여
구조적 분해 + 심층 리서치를 결합합니다.
"""

from .executor import HyperDeepExecutor

__all__ = ["HyperDeepExecutor"]

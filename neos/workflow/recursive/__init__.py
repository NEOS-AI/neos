"""
ROMA: Recursive Open Meta-Agent

NEOS의 재귀적 에이전트 워크플로우 모듈.
복잡한 멀티-호프 질문을 계층적으로 분해·실행·통합하는 ROMA 패턴을 구현합니다.

컴포넌트:
- models: RecursiveTaskNode, TaskAtomicity 데이터 모델
- atomizer: 태스크 원자성 판별 (LLM 기반)
- planner: non-atomic 태스크 하위 태스크 분해
- executor: atomic 태스크 실행 (기존 에이전트 활용)
- aggregator: 하위 태스크 결과 계층별 통합
- verifier: 최종 결과 충족도 검증
- orchestrator: ROMA 메인 실행 엔진 (Python 재귀 방식)
"""

from neos.workflow.recursive.models import RecursiveTaskNode, TaskAtomicity
from neos.workflow.recursive.orchestrator import RecursiveOrchestrator

__all__ = [
    "RecursiveTaskNode",
    "TaskAtomicity",
    "RecursiveOrchestrator",
]

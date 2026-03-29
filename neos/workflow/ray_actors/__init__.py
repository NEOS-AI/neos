"""Ray 기반 분산 병렬 실행 패키지.

RAY_ENABLED=true 시 독립 sibling subtask를 별도 Ray 프로세스에서 병렬 실행.
Ray 미설치 환경 보호를 위해 실제 import는 사용처에서 수행(lazy).

공개 API:
- RayExecutorPool: HyperDeepWorkerActor 풀 관리자
- HyperDeepWorkerActor: 독립 프로세스에서 HyperDeepResearchAgent를 실행하는 Ray Actor
- build_execution_levels: depends_on DAG → 레벨별 실행 그룹 변환
"""

__all__ = [
    "RayExecutorPool",
    "HyperDeepWorkerActor",
    "build_execution_levels",
]

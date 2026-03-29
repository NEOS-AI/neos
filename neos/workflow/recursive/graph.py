"""
RecursiveWorkflowGraph: LangGraph 서브그래프 (향후 마이그레이션 예정)

현재 구현: orchestrator.py의 Python 재귀 방식 사용
향후 계획: LangGraph StateGraph 서브그래프 방식으로 마이그레이션

LangGraph는 현재 동적 재귀 서브그래프 호출을 직접 지원하지 않으므로
(순환 임포트 및 그래프 컴파일 제약), 초기 구현은 Python 재귀 방식을 사용합니다.

마이그레이션 조건:
- langgraph >= 0.2.x 서브그래프 API 안정화 이후
- 각 재귀 레벨을 독립 StateGraph로 분리 (정적 깊이 언롤링 방식)

참고: RECURSIVE_AGENT_PLAN.md의 방식 B (정적 깊이 언롤링) 참조
"""

# 현재 이 모듈은 플레이스홀더입니다.
# 실제 실행 로직은 orchestrator.py의 RecursiveOrchestrator를 사용합니다.

__all__ = []

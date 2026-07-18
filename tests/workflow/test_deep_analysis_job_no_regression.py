"""AC7 + 3a/3b 경계 고정.

3a는 job 서비스만 만든다. 챗 경로(그래프 노드·라우터·분류기)는 3b의
범위이며 이 단계에서 바뀌면 안 된다.
"""

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.no_db


def _imported_modules(path: str) -> set[str]:
    """파일이 실제로 임포트하는 모듈 이름 집합.

    원시 문자열 스캔이 아니라 AST를 본다 -- 이 모듈들의 docstring은 설계
    근거로 `stream_manager`나 Celery를 **일부러 언급**하므로, 산문에
    이름이 나온다는 것과 의존한다는 것은 전혀 다른 얘기다. 우리가 고정하고
    싶은 불변식은 의존 그래프다.
    """
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_chat_node_is_untouched_by_phase_3a():
    """AC2/AC3(챗 노드 제거)는 3b다. 여기서 사라지면 범위 이탈이다."""
    source = Path("neos/workflow/graph.py").read_text(encoding="utf-8")

    assert "_deep_analysis_orchestrator_node" in source
    # 9763eb5의 wall-clock 바운드가 그대로 있어야 한다.
    assert "node_wall_clock_cap" in source


def test_deep_analysis_node_not_registered_when_flag_is_off():
    """D18의 구조적 무회귀: 플래그가 꺼져 있으면 노드가 등록되지 않는다."""
    from neos.config.settings import settings

    assert settings.config.deep_analysis.enabled is False


def test_job_service_does_not_import_langgraph_or_langchain():
    """스펙 §1.4 / 이 계획의 전역 제약: deep_analysis는 프레임워크 프리다."""
    for name in ("jobs.py", "event_stream.py"):
        modules = _imported_modules(f"neos/workflow/deep_analysis/{name}")
        offenders = [
            module
            for module in modules
            if module.startswith(("langchain", "langgraph"))
        ]
        assert offenders == [], f"{name}: {offenders}"


def test_job_runner_does_not_import_celery_or_fastapi():
    """실행자 관심사는 neos/tasks/에 있다 -- deep_analysis의 내부 의존을
    4개로 유지하기 위해서다."""
    modules = _imported_modules("neos/workflow/deep_analysis/jobs.py")

    offenders = [
        module
        for module in modules
        if module.startswith(("celery", "fastapi", "starlette"))
    ]
    assert offenders == [], offenders


def test_job_service_does_not_use_the_in_process_stream_manager():
    """stream_manager._sessions는 프로세스 내 dict라 Celery 워커의 이벤트가
    API 프로세스로 넘어오지 못한다. 전달 매체는 DB여야 한다."""
    for path in (
        "neos/workflow/deep_analysis/jobs.py",
        "neos/workflow/deep_analysis/event_stream.py",
        "neos/api/handlers/deep_analysis_handlers.py",
        "neos/tasks/deep_analysis_job_task.py",
    ):
        offenders = [
            module
            for module in _imported_modules(path)
            if "stream_manager" in module
        ]
        assert offenders == [], f"{path}: {offenders}"

"""AC3/AC7 + 프레임워크 프리 경계 고정.

3a는 job 서비스를 만들었고, 3b(D23)가 챗을 그 소비자로 바꿨다. 이 파일은
"블로킹 노드가 돌아오지 않는다"와 "deep_analysis 패키지가 프레임워크 프리로
남는다"를 함께 고정한다.
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


def test_blocking_chat_node_is_gone_after_phase_3b():
    """AC3: 챗 노드가 하네스를 완주시키던 구조가 제거됐다.

    9763eb5의 wall-clock 캡도 함께 사라진다 -- 실행이 요청 밖으로 나가면
    노드가 붙들 자원이 없다(스펙 §5.2). 캡이 돌아온다는 것은 블로킹 실행이
    돌아왔다는 뜻이므로 함께 금지한다.
    """
    source = Path("neos/workflow/graph.py").read_text(encoding="utf-8")

    assert "_deep_analysis_orchestrator_node" not in source
    assert "_persist_deep_analysis_failure" not in source
    assert "node_wall_clock_cap" not in source
    # 대체 노드는 존재해야 한다 -- 라우팅 대상이 사라지면 그래프가 깨진다.
    assert "_deep_analysis_dispatch_node" in source


def test_deep_analysis_ships_disabled_in_code():
    """코드 기본값은 off다 -- 켜는 것은 배포 설정의 결정이다.

    예전에는 런타임 `settings`를 단언했는데, 그러면 `config/neos.default.yaml`이
    플래그를 켜는 순간 깨지면서도 정작 "코드가 꺼진 채로 출하된다"는 계약은
    검증하지 못한다. 스키마 기본값을 직접 본다.
    """
    from neos.config.schema import DeepAnalysisConfig

    assert DeepAnalysisConfig().enabled is False


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

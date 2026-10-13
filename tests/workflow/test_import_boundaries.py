"""채팅 그래프와 langgraph 를 import 하면 안 되는 패키지 (spec 2026-10-13 §5).

dots(트랙 Q)·Jev·코딩 루프·심층분석 루프는 채팅 워크플로 바깥에 있다. 이 경계가
지켜져야 런타임을 갈아도 그쪽이 영향을 받지 않는다. 런타임 import 가 아니라 소스를
AST 로 읽는다 -- 함수 안의 지연 import 도 잡기 위해서다.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

_ROOT = Path(__file__).resolve().parents[2]
_GUARDED = (
    "neos/coding",
    "neos/workflow/deep_analysis",
    "neos/standing",
    "neos/jev",
    "neos/subagent",
)
_FORBIDDEN = (
    "langgraph",
    "neos.workflow.graph",
    "neos.workflow.runtime",
    "neos.workflow.wiring",
)


def _imported_names(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            for alias in node.names:
                yield f"{node.module}.{alias.name}"


def _is_forbidden(name: str) -> bool:
    return any(name == banned or name.startswith(banned + ".") for banned in _FORBIDDEN)


@pytest.mark.parametrize("package", _GUARDED)
def test_package_does_not_import_the_chat_graph(package: str) -> None:
    offenders = sorted(
        {
            f"{path.relative_to(_ROOT)}: {name}"
            for path in (_ROOT / package).rglob("*.py")
            for name in _imported_names(path)
            if _is_forbidden(name)
        }
    )
    assert not offenders, offenders


@pytest.mark.parametrize(
    "source",
    [
        "from neos.workflow.graph import multi_agent_workflow\n",
        "from neos.workflow import graph\n",
        "import langgraph.graph\n",
        "def f():\n    from neos.workflow.runtime.runner import WorkflowRunner\n",
    ],
)
def test_the_guard_sees_each_import_form(tmp_path: Path, source: str) -> None:
    """가드가 공허하지 않음을 보인다 -- 네 가지 import 모양을 다 잡아야 한다."""
    sample = tmp_path / "sample.py"
    sample.write_text(source, encoding="utf-8")
    assert any(_is_forbidden(name) for name in _imported_names(sample))


def test_every_guarded_package_exists() -> None:
    """경로가 옮겨지면 rglob 이 빈 목록을 돌려 가드가 조용히 꺼진다."""
    for package in _GUARDED:
        assert any((_ROOT / package).rglob("*.py")), package

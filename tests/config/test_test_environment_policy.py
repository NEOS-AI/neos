"""Contracts for deterministic process-wide pytest defaults."""

import os
import pathlib
import subprocess
import sys

import pytest

# 파일과 워크플로 YAML 만 읽는다. DB 는 필요 없고, `quality` 잡에는 postgres
# 서비스가 없다 -- 표시하지 않으면 autouse 정리 픽스처가 연결을 시도한다.
pytestmark = pytest.mark.no_db


def _run_bootstrap(code: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_pytest_bootstrap_disables_remote_litellm_cost_map():
    result = _run_bootstrap(
        "import os, runpy; "
        "runpy.run_path('tests/conftest.py'); "
        "assert os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] == 'True'"
    )

    assert result.returncode == 0, result.stderr


def test_pytest_bootstrap_preserves_explicit_litellm_cost_map_setting():
    result = _run_bootstrap(
        "import os, runpy; "
        "os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'False'; "
        "runpy.run_path('tests/conftest.py'); "
        "assert os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] == 'False'"
    )

    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# CI 가 무엇을 도는가 (S5)
# ---------------------------------------------------------------------------

_WORKFLOW = pathlib.Path(".github/workflows/backend-ci.yml")


def _ci_pytest_invocations() -> list[list[str]]:
    """워크플로가 **테스트를 실행하는** pytest 호출들.

    YAML 로 파싱해 `run:` 문자열만 본다. 처음에는 파일 텍스트를 평탄화해
    `pytest` 를 찾았는데, **YAML 주석의 산문이 인자로 딸려 들어왔다** --
    주석에 적힌 `tests/` 한 토큰이 모든 파일을 "커버됨" 으로 만들어 이 가드가
    통과만 하는 껍데기가 됐다. 파서가 주석을 지우게 하는 쪽이 확실하다.

    `--collect-only` 는 제외한다 -- 수집은 임포트가 깨지지 않았다는 것만
    말하고 단언을 하나도 돌리지 않는다. 커버리지로 세면 CI 가 실제로는
    돌리지 않는 파일을 "커버됨" 으로 기록하게 된다.
    """
    import yaml

    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    invocations: list[list[str]] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            run = step.get("run")
            if not run or "pytest" not in run:
                continue
            tokens = run.split()
            args = tokens[tokens.index("pytest") + 1 :]
            if "--collect-only" in args:
                continue
            invocations.append(args)
    return invocations


def _covered(path: pathlib.Path, args: list[str]) -> bool:
    ignores = [a.split("=", 1)[1] for a in args if a.startswith("--ignore=")]
    if any(str(path).startswith(ig.rstrip("/") + "/") for ig in ignores):
        return False
    targets = [a for a in args if a.startswith("tests") and not a.startswith("-")]
    return any(
        path == pathlib.Path(t) or str(path).startswith(t.rstrip("/") + "/")
        for t in targets
    )


def test_ci_workflow_covers_every_test_file():
    """CI 가 도는 집합이 `tests/` 전부여야 한다 -- S5 의 전제.

    2026-08-12 실측: CI 는 `tests/workflow` 와 `tests/api` 만 돌고 있었고,
    그것은 수집된 2,518건 중 1,192건(47%)이다. **1,326건이 한 번도 CI 에서
    돈 적이 없었고**, 그중 3건은 개발 기계의 `.env` 에 실제 API 키가 있을
    때만 통과하는 상태였다 -- CI 에 넣었다면 곧바로 빨간불이었다.

    이 테스트가 없으면 같은 격차가 조용히 되돌아온다. 새 최상위 테스트
    디렉터리를 추가하고 워크플로를 잊는 것만으로 충분하기 때문이다.
    """
    on_disk = {
        p
        for p in pathlib.Path("tests").rglob("test_*.py")
        if "__pycache__" not in p.parts
    }
    assert on_disk, "tests/ 에서 테스트 파일을 하나도 못 찾았다"

    invocations = _ci_pytest_invocations()
    assert invocations, f"{_WORKFLOW} 에서 실행형 pytest 호출을 못 찾았다"

    uncovered = sorted(
        str(p)
        for p in on_disk
        if not any(_covered(p, args) for args in invocations)
    )

    assert not uncovered, (
        f"{len(uncovered)}개 테스트 파일이 CI 에서 한 번도 돌지 않는다. "
        f"{_WORKFLOW} 에 넣거나, 왜 제외하는지 여기 적어라:\n  "
        + "\n  ".join(uncovered)
    )


# ---------------------------------------------------------------------------
# 프론트 CI 도 같은 질문을 받는다 (감사 §7 #1 · 로드맵 §5.3)
#
# 위 가드는 `tests/` 만 본다. 그래서 2026-09-02 까지 `web/tests/source/` 의
# 35파일 199건이 **CI 에서 한 번도 돌지 않는데도** 전부 초록이었다.
#
# 그 공백은 트랙 C 를 정확히 절반만 무력화했다. FE6·FE9 는 어휘 분기를 잡으려고
# 백엔드·프론트 테스트가 **같은 fixture 파일**을 읽게 만들었는데, CI 에서
# 빨개질 수 있는 쪽이 백엔드뿐이면 "한쪽만 고치면 반대쪽이 빨개진다" 는 보증이
# 성립하지 않는다.
#
# 📌 **이 가드가 왜 pytest 에 있는가.** `pnpm test:source` 안에 두면 프론트 CI
# 잡이 사라지는 순간 가드도 함께 사라진다 -- 자기 자신을 못 지킨다. pytest 는
# 백엔드 워크플로가 확실히 돌리므로 여기가 유일하게 안전한 자리다.
# ---------------------------------------------------------------------------

_FRONTEND_WORKFLOW = pathlib.Path(".github/workflows/frontend-ci.yml")

#: 프론트 잡이 반드시 돌려야 하는 것. 테스트만 돌리고 타입체크를 빼면
#: `tsc --noEmit` 이 잡던 계약 어긋남이 CI 밖에 남는다.
_REQUIRED_FRONTEND_COMMANDS = ("pnpm test:source", "tsc --noEmit")


def _frontend_workflow():
    import yaml

    assert _FRONTEND_WORKFLOW.exists(), (
        f"{_FRONTEND_WORKFLOW} 가 없다. 프론트 단위 테스트와 타입체크가 CI 에서 "
        "돌지 않으면 공유 fixture(FE6·FE9)의 프론트 절반은 사람이 손으로 "
        "돌릴 때만 검증된다."
    )
    return yaml.safe_load(_FRONTEND_WORKFLOW.read_text(encoding="utf-8"))


def _frontend_run_steps() -> list[str]:
    """프론트 워크플로가 실제로 실행하는 셸 명령들.

    YAML 로 파싱해 `run:` 만 본다 -- 파일 텍스트를 훑으면 **주석의 산문이 명령
    으로 딸려 들어온다.** `_ci_pytest_invocations` 가 그 함정을 이미 한 번
    밟았고(주석 속 `tests/` 한 토큰이 모든 파일을 커버됨으로 만들었다), 이
    파일 아래쪽 워크플로에는 "pnpm test:source 를 돌리지 않는다" 같은 문장을
    적을 이유가 충분히 있다.
    """
    workflow = _frontend_workflow()
    steps: list[str] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            run = step.get("run")
            if run:
                steps.append(run)
    return steps


def test_frontend_ci_runs_the_source_suite_and_typecheck():
    commands = _frontend_run_steps()
    assert commands, f"{_FRONTEND_WORKFLOW} 에서 `run:` 스텝을 못 찾았다"

    missing = [
        required
        for required in _REQUIRED_FRONTEND_COMMANDS
        if not any(required in command for command in commands)
    ]
    assert not missing, (
        f"{_FRONTEND_WORKFLOW} 가 {missing} 를 돌리지 않는다 -- "
        "프론트 회귀를 잡을 수단이 다시 0 이 된다."
    )


def test_frontend_ci_has_no_paths_filter():
    """`paths:` 로 좁히면 공유 fixture 시나리오에서 가드가 꺼진다.

    `web/tests/source/deep-analysis-{progress,degradation}.test.ts` 는 저장소
    **루트**의 `tests/fixtures/deep_analysis_*.json` 을 읽는다. 백엔드만
    고치면서 그 fixture 를 바꾼 커밋은 `web/` 를 하나도 건드리지 않으므로,
    `paths: [web/**]` 가 있으면 **정확히 그때** 프론트 검증이 안 돈다 --
    두 언어를 잇는 가드가 필요한 유일한 순간이다.

    좁히고 싶어지면 fixture 경로를 함께 적어야 하는데, 그 목록은 새 fixture 가
    생길 때마다 조용히 낡는다. 필터를 아예 두지 않는 편이 싸고 정직하다.
    """
    workflow = _frontend_workflow()
    triggers = workflow.get(True) or workflow.get("on") or {}
    for event, config in triggers.items():
        if not isinstance(config, dict):
            continue
        for key in ("paths", "paths-ignore"):
            assert key not in config, (
                f"{_FRONTEND_WORKFLOW} 의 `on.{event}` 에 `{key}` 가 있다. "
                "프론트 테스트는 저장소 루트의 공유 fixture 를 읽으므로 "
                "`web/**` 로 좁히면 백엔드-단독 fixture 변경에서 안 돈다 -- "
                "가드가 가장 필요한 순간이다."
            )


def test_frontend_ci_covers_every_source_test_file():
    """`web/tests/source/` 의 파일 전부가 실행되는 glob 안에 있는가.

    `package.json` 의 `test:source` 가 `tests/source/**/*.test.ts` 를 넘긴다.
    누군가 그것을 파일 목록으로 바꾸면(백엔드 CI 가 ruff 에서 실제로 겪은 일이다
    -- 네 파일만 검사하는 목록이 조용히 낡았다) 새 테스트가 CI 밖에 남는다.
    """
    import json

    package_json = pathlib.Path("web/package.json")
    scripts = json.loads(package_json.read_text(encoding="utf-8"))["scripts"]
    command = scripts.get("test:source", "")
    assert command, "web/package.json 에 test:source 스크립트가 없다"

    on_disk = sorted(pathlib.Path("web/tests/source").glob("*.test.ts"))
    assert on_disk, "web/tests/source 에서 테스트 파일을 하나도 못 찾았다"

    # glob 하나로 전부 도는 것이 현재 형태다. 목록으로 바뀌면 파일마다 확인한다.
    if "tests/source/**/*.test.ts" in command:
        return

    uncovered = [str(p) for p in on_disk if p.name not in command]
    assert not uncovered, (
        f"{len(uncovered)}개 프론트 테스트 파일이 `test:source` 밖에 있다:\n  "
        + "\n  ".join(uncovered)
    )

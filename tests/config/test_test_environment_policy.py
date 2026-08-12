"""Contracts for deterministic process-wide pytest defaults."""

import os
import pathlib
import subprocess
import sys


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

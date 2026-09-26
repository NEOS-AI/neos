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

#: 프론트 잡이 반드시 돌려야 하는 것.
#:
#: `typecheck:tests` 가 따로 있는 이유: 루트 `tsconfig.json` 이
#: `**/*.test.ts(x)` 를 `exclude` 하므로 `tsc --noEmit` 은 **테스트 파일을 한
#: 건도 보지 않는다.** 2026-09-02 에 처음 돌려 보니 오류 셋이 숨어 있었고 그중
#: 둘이 `deep-analysis-reader.test.ts` 였다. 둘은 서로를 대신하지 못한다.
#: `pnpm build` 가 있는 이유: 앞의 셋이 **원리적으로 못 잡는** 것이 있다.
#: dev 에 `export const dynamic`(`cacheComponents` 와 비호환)과 `server-only`
#: 위반이 남아 있었는데 셋 다 초록이었다 -- 둘 다 번들러 경계의 문제라 타입에도
#: 단위 테스트에도 걸리지 않는다. 그리고 CI 가 build 를 안 돌려서, 배포할 수
#: 없는 상태가 알려지지 않은 채였다(2026-09-03, §5.8).
_REQUIRED_FRONTEND_COMMANDS = (
    "pnpm lint",
    "pnpm test:source",
    "tsc --noEmit",
    "pnpm typecheck:tests",
    "pnpm build",
)

_RUFF_KERNEL_DIRS = (
    "neos/workflow/deep_analysis",
    "neos/coding",
    "neos/subagent",
    "neos/fsi",
    "neos/univer",
    "neos/config",
    "neos/learn",
    "neos/jev",
    "tests/workflow/deep_analysis",
    "tests/coding",
    "tests/subagent",
    "tests/fsi",
    "tests/univer",
    "tests/k_skill",
    "tests/security_audit",
    "tests/learn",
    "tests/jev",
    "tests/config",
    "tests/conftest.py",
)


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


def test_backend_ci_checks_catalog_fallback_is_fresh():
    """YAML 과 커밋된 FE 폴백이 어긋나면 피커가 두 시계를 갖는다.

    프론트 CI 는 Neos Python 환경이 없으므로 이 가드는 백엔드 워크플로의
    quality 잡에 둔다. 주석에 스크립트 이름을 적는 것만으로는 부족하다 —
    실제 `run:` 이 생성 후 `git diff --exit-code` 를 돌려야 한다.
    """
    import yaml

    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    quality_runs = [
        step.get("run") or ""
        for step in ((workflow.get("jobs") or {}).get("quality") or {}).get("steps") or []
    ]
    matching = [
        run
        for run in quality_runs
        if "generate_catalog_fallback.py" in run
        and "git diff --exit-code" in run
        and "web/lib/ai/catalog.generated.ts" in run
    ]
    assert matching, (
        f"{_WORKFLOW} quality 잡이 catalog.generated.ts 신선도 검사를 "
        "돌리지 않는다. YAML 만 바꾸고 생성된 폴백을 안 고치면 산다."
    )


def test_ci_quality_runs_ruff_on_kernel_dirs():
    """quality 잡의 Ruff 가 커널 디렉터리를 디렉터리 단위로 도는가.

    파일 목록은 새 파일이 생길 때 조용히 낡는다. 여기 적힌 경로는
    현재 0건인 표면이고, 워크플로 `run:` 에 그대로 있어야 한다.
    """
    import yaml

    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    quality_runs = [
        step.get("run") or ""
        for step in ((workflow.get("jobs") or {}).get("quality") or {}).get("steps") or []
    ]
    ruff_runs = [run for run in quality_runs if "ruff check" in run]
    assert ruff_runs, f"{_WORKFLOW} quality 잡이 ruff check 를 돌리지 않는다"
    blob = "\n".join(ruff_runs)
    missing = [path for path in _RUFF_KERNEL_DIRS if path not in blob]
    assert not missing, (
        f"{_WORKFLOW} Ruff 대상에서 빠졌다: {missing}. "
        "디렉터리를 워크플로에 넣거나 _RUFF_KERNEL_DIRS 를 고쳐라."
    )


def test_frontend_lint_script_uses_locked_biome():
    import json

    scripts = json.loads(pathlib.Path("web/package.json").read_text(encoding="utf-8"))[
        "scripts"
    ]
    command = scripts.get("lint", "")
    assert "biome check" in command, (
        f"web/package.json lint 가 잠긴 biome 이 아니다: {command!r}"
    )
    assert "@latest" not in command, (
        "lint 가 npx @latest 를 쓰면 CI 가 매 실행마다 다른 규칙을 가져온다"
    )


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


def _test_source_command() -> str:
    import json

    package_json = pathlib.Path("web/package.json")
    scripts = json.loads(package_json.read_text(encoding="utf-8"))["scripts"]
    command = scripts.get("test:source", "")
    assert command, "web/package.json 에 test:source 스크립트가 없다"
    return command


def test_frontend_ci_covers_every_source_test_file():
    """`web/tests/source/` 의 파일 전부가 실행되는 glob 안에 있는가.

    누군가 `test:source` 를 파일 목록으로 바꾸면(백엔드 CI 가 ruff 에서 실제로
    겪은 일이다 -- 네 파일만 검사하는 목록이 조용히 낡았다) 새 테스트가 CI 밖에
    남는다.

    🔴 **이 가드는 한 번 운으로 통과했다.** 확장자마다 glob 을 하나씩 넘기게
    바뀌었을 때(`*.test.ts` 와 `*.test.tsx`), 옛 판은 "옛 glob 문자열이 명령에
    들어 있는가" 만 보고 그냥 통과했다 -- **새로 생긴 `.tsx` 두 개를 세지도
    않은 채로.** 지금은 확장자별로 glob 의 존재를 요구한다.
    """
    command = _test_source_command()

    for suffix in ("ts", "tsx"):
        on_disk = sorted(pathlib.Path("web/tests/source").glob(f"*.test.{suffix}"))
        if not on_disk:
            continue
        glob = f"tests/source/**/*.test.{suffix}"
        if glob in command:
            continue
        uncovered = [str(p) for p in on_disk if p.name not in command]
        assert not uncovered, (
            f"{len(uncovered)}개 프론트 테스트 파일이 `test:source` 밖에 "
            f"있다(`{glob}` 도 없다):\n  " + "\n  ".join(uncovered)
        )


#: 프론트 테스트 파일이 살 수 있는 곳과, 그것을 실제로 돌리는 러너.
#: 여기 없는 곳의 `*.test.ts(x)` 는 아무도 돌리지 않는다.
_FRONTEND_TEST_HOMES = {
    "web/tests/source": "pnpm test:source (tsx --test)",
    "web/tests/e2e": "playwright (testMatch: /e2e\\/.*.test.ts/)",
}


def test_no_orphan_frontend_test_files():
    """어느 러너도 집지 않는 `*.test.ts(x)` 가 있는가.

    2026-09-02 실측: `web/lib/ai/models.test.ts` 가 정확히 그랬다. `test:source`
    의 glob(`tests/source/**`) 밖이라 실행되지 않았고, 루트 tsconfig 가
    `**/*.test.ts` 를 `exclude` 해서 타입체크도 되지 않았다. 그래서 존재하지
    않는 모듈(`@/tests/prompts/utils`)을 임포트한 채 **아무 신호 없이** 남아
    있었다 -- Vercel 템플릿 잔재였고, 테스트도 아니었다(모의 모델 픽스처).

    §5 의 FE3 과 같은 종류다: 아무도 돌리지 않는 파일은 다음 사람에게
    "여기 커버리지가 있다" 는 거짓 신호를 준다.
    """
    web = pathlib.Path("web")
    homes = tuple(pathlib.Path(home) for home in _FRONTEND_TEST_HOMES)

    orphans = sorted(
        str(path)
        for suffix in ("ts", "tsx")
        for path in web.rglob(f"*.test.{suffix}")
        if "node_modules" not in path.parts
        and not any(home in path.parents for home in homes)
    )

    assert not orphans, (
        f"{len(orphans)}개 테스트 파일을 아무 러너도 집지 않는다:\n  "
        + "\n  ".join(orphans)
        + "\n둘 중 하나로 옮기거나(각각 "
        + " · ".join(f"{k} → {v}" for k, v in _FRONTEND_TEST_HOMES.items())
        + ") 지울 것."
    )

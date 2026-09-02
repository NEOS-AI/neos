"""원장 이벤트 어휘가 정본 fixture 와 정확히 일치하는가.

`test_ledger_degradations.py` 와 같은 규율이고 겨누는 대상만 다르다. 저쪽은
**어떤 이벤트가 강등인가**를 두 언어에 걸쳐 고정하고, 이쪽은 **어떤 이벤트가
존재하는가**를 고정한다 -- 그리고 프론트 테스트가 같은 fixture 를 읽어 각
kind 에 화면 문구가 있는지 본다.

## 왜 소스를 훑는가

이 저장소가 실제로 치른 실패는 "백엔드가 이벤트를 늘렸는데 프론트 라벨이
따라오지 않는 것"이다(로드맵 §5.2 FE1 -- 8종이 한꺼번에 침묵했다). 목록을
손으로 적어 두면 그 실패를 그대로 반복한다: 새 `ledger.log(...)` 한 줄은
어떤 테스트도 빨갛게 만들지 못한다.

그래서 목록의 출처를 사람이 아니라 **소스 자체**로 둔다. AST 로 훑으므로
문자열 검색과 달리 호출 형태를 구별하고, 무엇보다 **읽지 못한 호출부를 조용히
넘기지 않는다** -- 해석할 수 없는 kind 인자를 만나면 그 자리를 이름으로 짚어
실패한다. 스캐너가 덜 검사하는 것이 이 테스트의 유일한 실패 모드이므로,
그 실패 모드를 시끄럽게 만드는 것이 설계의 핵심이다.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

FIXTURE_PATH = (
    _REPO_ROOT / "tests" / "fixtures" / "deep_analysis_event_kinds.json"
)

#: 훑을 파일. 원장에 쓰는 코드는 하네스 패키지와 job 통합 계층 둘뿐이다.
_SOURCE_ROOTS = (
    _REPO_ROOT / "neos" / "workflow" / "deep_analysis",
    _REPO_ROOT / "neos" / "tasks" / "deep_analysis_job_task.py",
)

#: 호출 이름 -> kind 가 놓이는 위치 인자 번호.
#:
#: `log` 은 `Ledger.log(kind, qid, payload)`, `_persist_event` 는 TokenBudget 가
#: `persist` 콜백으로 같은 곳에 도달하는 경로, `_log_lifecycle` 은 jobs.py 가
#: `job_*` 를 쓰는 경로다.
_EVENT_SINKS = {"log": 0, "_persist_event": 0, "_log_lifecycle": 2}


def _source_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in _SOURCE_ROOTS:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
        else:
            files.append(root)
    return files


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """모듈 최상위의 `NAME = "리터럴"` 만 모은다.

    `MANIFEST_KIND` · `JOB_STARTED` 처럼 kind 를 상수로 둔 자리를 풀기 위한
    것이다. 한 파일 안에서만 찾지 않고 훑는 파일 전체의 상수를 합쳐 쓴다 --
    `service.py` 가 `manifest.py` 의 상수를 import 해서 쓰기 때문이다.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (
            isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value.value
    return constants


def _enclosing_parameters(tree: ast.Module) -> dict[ast.AST, frozenset[str]]:
    """각 노드가 속한 함수의 파라미터 이름 집합.

    kind 인자가 **그 함수의 파라미터**면 그 호출부는 전달자(forwarder)다 --
    실제 kind 는 호출하는 쪽에 있고 거기서 따로 잡힌다. 전달자 목록을 손으로
    적어 두면(파일명·줄번호) 코드가 움직일 때마다 낡으므로, 구조에서 판정한다.
    """
    scopes: dict[ast.AST, frozenset[str]] = {}

    def walk(node: ast.AST, params: frozenset[str]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            params = frozenset(
                arg.arg
                for arg in (
                    *args.posonlyargs,
                    *args.args,
                    *args.kwonlyargs,
                    *([args.vararg] if args.vararg else []),
                    *([args.kwarg] if args.kwarg else []),
                )
            )
        scopes[node] = params
        for child in ast.iter_child_nodes(node):
            walk(child, params)

    walk(tree, frozenset())
    return scopes


def _resolve_kind(
    node: ast.expr,
    constants: dict[str, str],
    parameters: frozenset[str],
) -> tuple[set[str], str | None]:
    """kind 표현식을 문자열 집합으로 푼다.

    @returns (풀린 kind 집합, 못 푼 이유). 이유가 있으면 호출자가 실패시킨다.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}, None
    if isinstance(node, ast.IfExp):
        # jobs.py 의 `JOB_RESUMED if resume else JOB_STARTED` -- 두 갈래 다 산다.
        left, why_left = _resolve_kind(node.body, constants, parameters)
        right, why_right = _resolve_kind(node.orelse, constants, parameters)
        return left | right, why_left or why_right
    if isinstance(node, ast.Name):
        if node.id in parameters:
            return set(), None  # 전달자 -- 실제 kind 는 호출하는 쪽에 있다
        if node.id in constants:
            return {constants[node.id]}, None
        return set(), f"이름 {node.id!r} 를 풀지 못했다"
    return set(), f"{type(node).__name__} 표현식을 풀지 못했다"


def discover_ledger_event_kinds() -> tuple[set[str], list[str]]:
    """소스에서 원장에 도달하는 kind 를 모은다.

    @returns (kind 집합, 해석하지 못한 호출부 설명 목록)
    """
    trees: dict[pathlib.Path, ast.Module] = {
        path: ast.parse(path.read_text(encoding="utf-8"))
        for path in _source_files()
    }

    constants: dict[str, str] = {}
    for tree in trees.values():
        constants.update(_module_string_constants(tree))

    kinds: set[str] = set()
    unresolved: list[str] = []

    for path, tree in trees.items():
        scopes = _enclosing_parameters(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            else:
                continue
            index = _EVENT_SINKS.get(name)
            if index is None:
                continue

            where = f"{path.relative_to(_REPO_ROOT)}:{node.lineno} ({name})"
            if len(node.args) <= index:
                unresolved.append(f"{where} -- 위치 인자가 모자란다")
                continue

            resolved, why = _resolve_kind(
                node.args[index], constants, scopes.get(node, frozenset())
            )
            kinds |= resolved
            if why:
                unresolved.append(f"{where} -- {why}")

    return kinds, unresolved


_FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["kinds"]
CANONICAL_KINDS = {entry["kind"] for entry in _FIXTURE}
LABELED_KINDS = {
    entry["kind"] for entry in _FIXTURE if entry["labeled"] is True
}


def test_fixture_lists_every_kind_the_ledger_actually_writes():
    """새 이벤트도, 사라진 이벤트도 여기서 잡힌다.

    한쪽만 걸면 절반만 잡힌다: 누락만 보면 낡은 항목이 남아 프론트가 없는
    이벤트에 라벨을 유지하고(실제로 `recovered` 가 그랬다), 잔재만 보면 새
    이벤트가 조용히 라벨 없이 배포된다.
    """
    discovered, _ = discover_ledger_event_kinds()

    missing = discovered - CANONICAL_KINDS
    stale = CANONICAL_KINDS - discovered
    assert not missing, (
        "원장에 쓰이는데 fixture 에 없는 kind: "
        f"{sorted(missing)} -- fixture 에 추가하고, `labeled: false` 로 둔다면 "
        "사유를 함께 적을 것. 라벨을 붙인다면 "
        "`web/lib/deep-analysis/progress.ts` 의 `activityLabel()` 도 같은 "
        "변경에 넣는다(로드맵 §3.2 짝 규칙)."
    )
    assert not stale, (
        f"fixture 에 있는데 원장에 쓰이지 않는 kind: {sorted(stale)} -- "
        "삭제됐다면 fixture 와 프론트 라벨에서 함께 빼고, `_emit` 전용이 "
        "됐다면 job 경로에서는 발행되지 않으므로 프론트에 도달하지 않는다."
    )


def test_scanner_reads_every_event_sink_call_site():
    """스캐너가 못 읽은 호출부는 조용히 넘어가지 않는다.

    이 테스트가 없으면 위 테스트는 **스캐너가 아무것도 못 읽어도 통과한다**
    (`discovered` 가 비면 `missing` 도 빈다). 대조 테스트 자체가 덜 검사할 수
    있다는 것이 FE6 에서 배운 것이고, 여기서는 그 구멍이 이 모양이다.
    """
    _, unresolved = discover_ledger_event_kinds()
    assert not unresolved, (
        "kind 를 읽지 못한 호출부가 있다:\n  "
        + "\n  ".join(unresolved)
        + "\n호출 형태를 바꿨다면 `_resolve_kind` 를 함께 넓힐 것."
    )


def test_scanner_finds_the_kinds_that_hide_behind_indirection():
    """리터럴 검색이 놓치는 세 형태를 실제로 잡는지 본다.

    이 셋은 전부 `grep '\\.log("'` 이 못 찾는다: `run_manifest` 는 다른 모듈의
    상수, `job_started` 는 삼항식, `llm_truncated` 는 TokenBudget 의
    `_persist_event` 를 거친다. 스캐너의 세 갈래가 각각 살아 있는지 고정한다.
    """
    discovered, _ = discover_ledger_event_kinds()
    assert {"run_manifest", "job_started", "llm_truncated"} <= discovered


@pytest.mark.parametrize(
    "entry", _FIXTURE, ids=[entry["kind"] for entry in _FIXTURE]
)
def test_unlabeled_kinds_carry_a_reason(entry):
    """라벨의 부재는 사고가 아니라 판단이어야 한다.

    `labeled: false` 는 "화면에 안 띄우기로 했다"는 뜻이고, 그 판단의 근거가
    없으면 다음 사람은 그것이 결정인지 누락인지 구별할 수 없다 -- FE1 이
    남긴 상태가 정확히 그것이었다.
    """
    if entry["labeled"] is False:
        assert entry.get("reason"), f"{entry['kind']} 에 면제 사유가 없다"
    else:
        assert "reason" not in entry, (
            f"{entry['kind']} 는 라벨이 있는데 면제 사유가 붙어 있다"
        )

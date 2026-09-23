"""코딩 원장 이벤트 어휘가 정본 fixture 와 정확히 일치하는가.

`tests/workflow/deep_analysis/test_event_kinds.py` 와 같은 규율이고, 겨누는
스트림만 다르다. 저쪽은 DA 원장을, 이쪽은 코딩 원장(`coding_events`)을 본다.

## 왜 이 테스트가 생겼나

로드맵 §12.8 ①: Jev 판정 이벤트는 코딩 원장에 쌓이는데 그 스트림에는 짝
규칙이 없었다. 그래서 `jev_risk_scored` 만이 아니라 `model.refused`(K6)와
`subagent.*`(K3)까지 프론트 리듀서의 `return base` 로 조용히 사라지고 있었다.
새 `append(event_type=...)` 한 줄이 어떤 테스트도 빨갛게 만들지 못했기 때문이다.

## 무엇을 싱크로 보는가

코딩 원장에 닿는 길은 세 갈래다.

1. `event_type=` 키워드를 받는 호출 -- `append` · `_append_event_in_session` ·
   `commit_model_checkpoint` 등. 이름을 나열하지 않고 **키워드로** 잡는다:
   싱크 함수가 새로 생겨도 키워드는 같다.
2. `CodingEvent(type="...")` 직접 생성 -- `workspace_edit_repository` 가 그렇다.
3. 서브에이전트 런타임의 `emit("subagent.*")` 중 부모 싱크(`_PARENT_SINK_EVENTS`)를
   통과하는 것.

그리고 한 곳은 kind 를 **값으로** 넘긴다: durable 루프가 Jev 게이트의 결정
payload 에서 `kind` 를 꺼내 쓴다. 그 값의 출처는 `neos/jev/gate.py` 의
`{"kind": ...}` 리터럴이고, 그것도 훑는다.

못 푼 호출부는 조용히 넘어가지 않는다 -- 이 테스트의 유일한 실패 모드는
스캐너가 덜 읽는 것이다.
"""

from __future__ import annotations

import ast
import json
import pathlib

from neos.coding.domain.approvals import ApprovalStatus
from neos.coding.domain.phases import CodingRunStatus
from neos.coding.runtime import _PARENT_SINK_EVENTS

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "coding_event_kinds.json"

_CODING_ROOT = _REPO_ROOT / "neos" / "coding"
_SUBAGENT_RUNTIME = _REPO_ROOT / "neos" / "subagent" / "runtime.py"
_JEV_GATE = _REPO_ROOT / "neos" / "jev" / "gate.py"

#: f-string kind 의 접두사 -> 실제로 그 자리를 지나는 값.
#:
#: 값의 출처는 enum 이지만 enum 전부가 지나가지는 않는다(`_commit_terminal_run`
#: 은 종결 상태로만 불린다). 그래서 목록을 적되, 아래 테스트가 각 값이 enum 에
#: 실제로 있는지 확인한다 -- 이름이 바뀌면 여기가 빨개진다.
_TEMPLATED = {
    "run.": frozenset({"completed", "failed", "cancelled"}),
    "approval.": frozenset({"approved", "denied", "expired", "invalidated"}),
}

#: kind 를 지역 변수로 넘기는 자리 -> 그 값의 출처. 지금은 하나다.
_INDIRECT = {("neos/coding/loop/durable.py", "kind"): "jev_gate"}


def _module_string_constants(trees) -> dict[str, str]:
    constants: dict[str, str] = {}
    for tree in trees:
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = node.value.value
    return constants


def _enclosing_parameters(tree: ast.Module) -> dict[ast.AST, frozenset[str]]:
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


def _templated_prefix(node: ast.JoinedStr) -> str | None:
    """`f"run.{status.value}"` 모양만 받는다: 리터럴 접두사 + 값 하나."""
    if (
        len(node.values) == 2
        and isinstance(node.values[0], ast.Constant)
        and isinstance(node.values[1], ast.FormattedValue)
    ):
        return str(node.values[0].value)
    return None


def _jev_gate_kinds() -> set[str]:
    """게이트가 결정 payload 에 싣는 `{"kind": ...}` 값들."""
    tree = ast.parse(_JEV_GATE.read_text(encoding="utf-8"))
    constants = _module_string_constants([tree])
    kinds: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value == "kind"):
                continue
            if isinstance(value, ast.Name) and value.id in constants:
                kinds.add(constants[value.id])
            elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                kinds.add(value.value)
    return kinds


def _subagent_emitted_kinds() -> set[str]:
    tree = ast.parse(_SUBAGENT_RUNTIME.read_text(encoding="utf-8"))
    kinds: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "emit"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            kinds.add(node.args[0].value)
    return kinds


def discover_coding_event_kinds() -> tuple[set[str], list[str]]:
    """소스에서 코딩 원장에 도달하는 kind 를 모은다.

    @returns (kind 집합, 해석하지 못한 호출부 설명 목록)
    """
    files = sorted(_CODING_ROOT.rglob("*.py"))
    trees = {
        path: ast.parse(path.read_text(encoding="utf-8")) for path in files
    }
    constants = _module_string_constants(trees.values())
    kinds: set[str] = set()
    unresolved: list[str] = []

    for path, tree in trees.items():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        scopes = _enclosing_parameters(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", None)
            )
            for keyword in node.keywords:
                is_sink = keyword.arg == "event_type" or (
                    keyword.arg == "type" and func_name == "CodingEvent"
                )
                if not is_sink:
                    continue
                where = f"{rel}:{node.lineno} ({func_name})"
                value = keyword.value
                # `"tool.completed" if pending else "model.completed"` -- both run.
                branches = [value]
                while any(isinstance(b, ast.IfExp) for b in branches):
                    branches = [
                        part
                        for b in branches
                        for part in (
                            (b.body, b.orelse) if isinstance(b, ast.IfExp) else (b,)
                        )
                    ]
                if len(branches) > 1:
                    if all(
                        isinstance(b, ast.Constant) and isinstance(b.value, str)
                        for b in branches
                    ):
                        kinds |= {b.value for b in branches}
                    else:
                        unresolved.append(f"{where} -- 조건식 갈래에 리터럴이 아닌 것이 있다")
                    continue
                # `str(record["type"])` -- a rehydration wrapped in a cast.
                if (
                    isinstance(value, ast.Call)
                    and getattr(value.func, "id", None) == "str"
                    and len(value.args) == 1
                ):
                    value = value.args[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    kinds.add(value.value)
                elif isinstance(value, ast.JoinedStr):
                    prefix = _templated_prefix(value)
                    if prefix in _TEMPLATED:
                        kinds |= {prefix + suffix for suffix in _TEMPLATED[prefix]}
                    else:
                        unresolved.append(f"{where} -- 모르는 f-string 접두사 {prefix!r}")
                elif isinstance(value, ast.Name):
                    if value.id in scopes.get(node, frozenset()):
                        continue  # 전달자 -- 실제 kind 는 호출하는 쪽에 있다
                    if value.id in constants:
                        kinds.add(constants[value.id])
                    elif _INDIRECT.get((rel, value.id)) == "jev_gate":
                        kinds |= _jev_gate_kinds()
                    else:
                        unresolved.append(f"{where} -- 이름 {value.id!r} 를 풀지 못했다")
                elif func_name == "CodingEvent" and isinstance(
                    value, (ast.Subscript, ast.Attribute)
                ):
                    # 행이나 다른 이벤트에서 읽어 되살리는 자리다. 새 kind 를
                    # 쓰지 않는다 -- 쓰는 자리는 위의 리터럴이 따로 잡는다.
                    continue
                else:
                    unresolved.append(
                        f"{where} -- {type(value).__name__} 표현식을 풀지 못했다"
                    )

    kinds |= _subagent_emitted_kinds() & _PARENT_SINK_EVENTS
    return kinds, unresolved


_FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["kinds"]
CANONICAL_KINDS = {entry["kind"] for entry in _FIXTURE}


def test_fixture_lists_every_kind_the_coding_ledger_actually_writes():
    """새 이벤트도, 사라진 이벤트도 여기서 잡힌다."""
    discovered, _ = discover_coding_event_kinds()

    missing = discovered - CANONICAL_KINDS
    stale = CANONICAL_KINDS - discovered
    assert not missing, (
        f"코딩 원장에 쓰이는데 fixture 에 없는 kind: {sorted(missing)} -- "
        "fixture 에 추가하고 sample 을 붙일 것. 투영한다면 "
        "`web/features/coding/stream/projection-reducer.ts` 도 같은 변경에 넣고, "
        "면제한다면 `projected: false` 와 사유를 적는다."
    )
    assert not stale, (
        f"fixture 에 있는데 코딩 원장에 쓰이지 않는 kind: {sorted(stale)} -- "
        "삭제됐다면 fixture 와 프론트 처리에서 함께 뺀다."
    )


def test_scanner_reads_every_sink_call_site():
    """위 테스트는 스캐너가 아무것도 못 읽어도 통과한다 -- 그래서 이것이 있다."""
    discovered, unresolved = discover_coding_event_kinds()
    assert not unresolved, "스캐너가 풀지 못한 호출부:\n" + "\n".join(unresolved)
    # 하한: 스캐너가 대부분을 놓치면 위의 `missing` 이 조용히 빈다.
    assert len(discovered) > 30, sorted(discovered)


def test_every_parent_sink_event_is_really_emitted():
    """허용 목록에만 있고 아무도 내지 않는 이름은 낡은 면제와 같다."""
    assert _PARENT_SINK_EVENTS <= _subagent_emitted_kinds()


def test_templated_suffixes_are_real_enum_values():
    run_values = {status.value for status in CodingRunStatus}
    approval_values = {status.value for status in ApprovalStatus}
    assert _TEMPLATED["run."] <= run_values
    assert _TEMPLATED["approval."] <= approval_values


def test_indirect_site_still_forwards_the_gate_kinds():
    """durable 루프가 kind 를 값으로 넘기는 자리가 사라지거나 이름이 바뀌면
    `_INDIRECT` 가 낡은 면제가 된다. 양방향으로 고정한다."""
    durable = _REPO_ROOT / "neos" / "coding" / "loop" / "durable.py"
    tree = ast.parse(durable.read_text(encoding="utf-8"))
    forwards = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and any(
            kw.arg == "event_type"
            and isinstance(kw.value, ast.Name)
            and kw.value.id == "kind"
            for kw in node.keywords
        )
    ]
    assert len(forwards) == 1
    assert _jev_gate_kinds() == {"jev_risk_scored", "jev_unavailable"}


def test_exemptions_carry_a_reason_and_every_kind_a_sample():
    for entry in _FIXTURE:
        assert isinstance(entry.get("sample"), dict), entry["kind"]
        if entry["projected"] is False:
            assert entry.get("reason"), f"{entry['kind']} 면제에 사유가 없다"
        else:
            assert "reason" not in entry, (
                f"{entry['kind']} 는 투영되는데 사유가 남아 있다 -- 낡은 면제다"
            )

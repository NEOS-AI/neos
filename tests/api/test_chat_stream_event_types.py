"""챗 SSE 이벤트 어휘가 정본 fixture 와 정확히 일치하는가.

DA 원장(`deep_analysis_event_kinds.json`)·코딩 원장(`coding_event_kinds.json`)과
같은 규율이고, 겨누는 스트림만 다르다 -- 이쪽은 `POST /chat/.../messages/stream`
이 흘리는 OpenResponses + `neos:*` 이벤트다.

## 왜 이 테스트가 생겼나

세 스트림 중 이것만 짝 규칙이 없었다. 그래서 `response.reasoning.delta`/`.done`
은 백엔드가 줄곧 보냈고 `message.tsx` 도 그릴 줄 알았는데 **훅이 받지 않아**
사고 과정이 조용히 버려지고 있었다(프론트 가드는 재수출조차 안 돼 있었다).

## 무엇을 발행으로 보는가

이 스트림의 이벤트는 전부 `neos/api/models/open_responses.py` 의 `*Event`
Pydantic 클래스이고, `type` 은 그 클래스의 `Literal` 기본값이다. 그러니 문자열을
grep 하면 안 잡힌다(실제로 `neos:inline_viz` 를 발행 안 한다고 오판했다).
`neos/` 전체를 AST 로 훑어 **인스턴스화되는** 클래스의 `type` 을 모은다.
정의만 있고 아무도 만들지 않는 클래스는 발행이 아니다.
"""

from __future__ import annotations

import ast
import json
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "chat_stream_event_types.json"
_MODELS = _REPO_ROOT / "neos" / "api" / "models" / "open_responses.py"


def _event_class_types() -> dict[str, str]:
    tree = ast.parse(_MODELS.read_text())
    types: dict[str, str] = {}
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name.endswith("Event")):
            continue
        for statement in node.body:
            if (
                isinstance(statement, ast.AnnAssign)
                and getattr(statement.target, "id", None) == "type"
                and isinstance(statement.value, ast.Constant)
            ):
                types[node.name] = statement.value.value
    return types


def _emitted_types() -> set[str]:
    by_class = _event_class_types()
    emitted: set[str] = set()
    for path in (_REPO_ROOT / "neos").rglob("*.py"):
        if path == _MODELS or "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name in by_class:
                emitted.add(by_class[name])
    return emitted


def _fixture() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text())["types"]


def test_the_scanner_sees_the_stream():
    # 스캐너가 덜 읽으면 아래 일치 단언이 공허해진다. 확실히 발행되는 것을 먼저 본다.
    emitted = _emitted_types()
    assert {"response.output_text.delta", "neos:harness", "neos:inline_viz"} <= emitted


def test_fixture_matches_the_emitted_vocabulary_exactly():
    listed = [entry["type"] for entry in _fixture()]

    assert len(listed) == len(set(listed)), "fixture 에 중복 type 이 있다"
    assert set(listed) == _emitted_types()


def test_unhandled_types_carry_a_reason():
    for entry in _fixture():
        if entry["handled"] is False:
            assert entry.get("reason", "").strip(), entry["type"]

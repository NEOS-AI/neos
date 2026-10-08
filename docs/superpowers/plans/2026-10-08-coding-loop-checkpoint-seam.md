# 코딩 루프 체크포인트 이음매 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 테스트가 `DurableCodingLoop` 의 private 멤버(의존성 재할당 70, `_restore(…, None)` 40, `_dump_state` 22)와 다른 테스트 모듈(36개 파일)에 기대지 않게 한다 — 행동 변경 없이.

**Architecture:** 체크포인트 첫 상태·인코딩을 루프 밖의 순수 함수(`neos/coding/loop/checkpoint.py`)로 공개하고 루프의 private 메서드는 그것에 위임만 한다. 공용 테스트 부품은 `tests/coding/loop/support.py` 로 옮기고, `harness()` 는 생성자 인자를 전부 넘기며 `Harness.rebuilt()` 가 "같은 저장소 위의 새 루프"를 만든다.

**Tech Stack:** Python 3.12, pytest(asyncio), uv, ruff.

**Spec:** `docs/superpowers/specs/2026-10-08-coding-loop-checkpoint-seam-design.md`

## Global Constraints

- 순수 리팩터링: 프로덕션 행동 변경 없음.
- 체크포인트 `loop_state` 형식은 키·순서·값까지 그대로다(저장된 체크포인트가 그대로 재개되어야 한다).
- 기존 테스트의 단언(assert)은 바꾸지 않는다. 준비(arrange) 단계만 바뀐다. 단언까지 바뀌어야 하면 멈추고 보고한다.
- 범위 밖(③, C 로): 체크포인트로부터의 `_restore(INPUT, checkpoint)` 25곳, `loop._advance_detached_children = spy` 3곳, 그 밖의 행동 메서드 직접 호출.
- 브랜치: `refactor/coding-loop-checkpoint-seam`(dev 기준). 커밋 메시지에 Co-Authored-By 트레일러를 넣지 않는다.
- 검증은 개수가 아니라 테스트 **이름**으로 한다. `-o addopts=""` 를 쓰지 않는다(importlib 모드가 지워져 수백 개가 조용히 빠진다).

## Review Focus

1. **이전 형식으로 저장된 체크포인트의 재개** — `encode_state` 는 옛 `_dump_state` 와 키·값이 같아야 한다. → Task 1 의 과도기 동등성 테스트가 옛 구현과 직접 대조한다.
2. **명령으로 시작한 입력(`/clear` 등)의 인코딩** — `current_instruction` 은 명령이 아니라 대화의 작업 시드로 남아야 한다. → Task 1 `test_encode_state_keeps_the_task_seed_when_the_input_is_a_command`.
3. **작업 공간 편집이 있는 입력** — 첫 상태에 편집 요약이 실려야 하고, 체크포인트 재개 시 다시 붙는 현재 행동은 그대로여야 한다. → Task 1 `test_initial_state_carries_workspace_edits` + 과도기 대조에 편집 입력 포함.
4. **`rebuilt()` 뒤의 재개** — 새 루프가 같은 repository 의 체크포인트를 읽고, 남은 모델 턴을 이어 받아야 한다. → Task 2 `test_rebuilt_shares_the_repository_and_the_model_queue`.
5. **체크포인트에서 시작한 런과 새로 시작한 런의 동등성** — 같은 턴이면 커밋되는 `loop_state` 가 같아야 한다. → Task 4 `test_starting_from_the_encoded_initial_state_matches_a_fresh_start`.

---

## 공통: 경로와 명령

```bash
cd /Users/ywsung/Desktop/neos
SCRATCH=/private/tmp/claude-501/-Users-ywsung-Desktop-neos/e0c087a5-a605-4076-907b-fff347dac9f4/scratchpad/seam
DEPS='\bloop\._(clock|tools|user_rules|config|asks|metrics|device_bridge|secrets|model|subagents|browser)\s*=[^=]'
```

---

### Task 0: 기준선

**Files:** 없음(스크래치패드에만 쓴다).

- [ ] **Step 1: 테스트 이름 목록을 뽑는다**

```bash
mkdir -p $SCRATCH
uv run pytest tests/coding tests/standing --collect-only -qq | grep '::' | sort > $SCRATCH/names_before.txt
wc -l $SCRATCH/names_before.txt
```
Expected: 3390 근처(2026-10-08 기준 `tests/coding tests/standing` 수집 3390).

- [ ] **Step 2: 전체 실행 결과를 이름으로 저장한다**

```bash
uv run pytest tests/coding tests/standing -q -rA -p no:randomly > $SCRATCH/run_before.txt 2>&1; tail -3 $SCRATCH/run_before.txt
grep -E '^(PASSED|FAILED|ERROR|XPASS|XFAIL) ' $SCRATCH/run_before.txt | sort > $SCRATCH/outcomes_before.txt
grep -E '^(FAILED|ERROR) ' $SCRATCH/outcomes_before.txt || echo "no failures"
```
`-p no:randomly` 가 "unrecognized" 로 실패하면 그 옵션만 빼고 다시 돌린다. 원래 실패하는 테스트가 있으면 이름을 기록해 둔다(메모: `[modal]` 관리형 비밀 잘린 꼬리 테스트는 단독으로도 흔들린다). DB 가 필요한 테스트가 수집·실행 오류를 내면 그것도 기준선의 일부로 기록하고, 이후 대조에서 같은 이름이 같은 결과인지만 본다.

- [ ] **Step 3: 지표 기준선을 기록한다**

```bash
{
echo "deps $(grep -rnE "$DEPS" tests | wc -l)"
echo "restore_none $(python3 - <<'EOF'
import re,pathlib
n=0
for p in pathlib.Path("tests").rglob("*.py"):
    n+=len(re.findall(r"\w+\.loop\._restore\(\s*[^,()]+,\s*None\s*,?\s*\)",p.read_text()))
print(n)
EOF
)"
echo "dump $(grep -rnE '\._dump_state\(' tests | wc -l)"
echo "importers $(grep -rlE 'from tests\.coding\.loop\.test_anthropic_loop import' tests | wc -l)"
echo "spies $(grep -rnE '\bloop\._advance_detached_children\s*=' tests | wc -l)"
} | tee $SCRATCH/metrics_before.txt
```
Expected: `deps 70`, `restore_none 40`, `dump 22`, `importers 36`, `spies 3`. 다르면 dev 가 움직인 것이다 — 숫자를 이 계획 대신 이 기록으로 삼고 진행한다.

---

### Task 1: 공개 체크포인트 이음매

**Files:**
- Create: `neos/coding/loop/checkpoint.py`
- Modify: `neos/coding/loop/_durable/checkpoint.py` (`_restore` 의 None 분기, `_cleared_transcript`, `_task_seed_text`/`_is_task_seed`/`_with_workspace_edits` 제거, `_dump_state`)
- Modify: `neos/coding/loop/__init__.py`
- Test: `tests/coding/loop/test_checkpoint_seam.py` (create)

**Interfaces:**
- Produces:
  - `neos.coding.loop.initial_state(input: LoopInput) -> AgentLoopState`
  - `neos.coding.loop.encode_state(input: LoopInput, state: AgentLoopState) -> dict[str, Any]`
  - `neos.coding.loop.AgentLoopState` (재수출)
  - 모듈 private: `neos.coding.loop.checkpoint._CLEARED_NOTICE`, `_with_workspace_edits(transcript, edits)`, `_task_seed_text(transcript, input) -> str`, `_is_task_seed(text) -> bool`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/coding/loop/test_checkpoint_seam.py`:

```python
"""The checkpoint seam: a run's first state and its stored form, without a loop."""

import json
from dataclasses import replace

import pytest

from neos.coding.loop import encode_state, initial_state
from neos.coding.loop.base import LoopInput, WorkspaceEditContext
from neos.coding.model.base import CanonicalMessage, TextContent

pytestmark = pytest.mark.no_db

INPUT = LoopInput("ct_1", "cr_1", "Fix it")
EDITED = LoopInput(
    "ct_1",
    "cr_1",
    "Fix it",
    workspace_edits=(WorkspaceEditContext("cwe_1", "src/app.py", "13"),),
)


def _texts(state) -> list[str]:
    return [
        item.text
        for message in state.transcript
        for item in message.content
        if isinstance(item, TextContent)
    ]


def test_initial_state_starts_from_the_instruction() -> None:
    state = initial_state(INPUT)

    assert _texts(state) == ["Fix it"]
    assert state.transcript[0].role == "user"
    assert state.turn_count == 0
    assert state.tool_count == 0
    assert not state.has_pending_tool
    assert state.transcript_digest


def test_initial_state_carries_workspace_edits() -> None:
    texts = _texts(initial_state(EDITED))

    assert texts[0] == "Fix it"
    assert any("src/app.py @ revision 13" in text for text in texts[1:])


def test_encode_state_is_the_stored_json_form() -> None:
    encoded = encode_state(INPUT, initial_state(INPUT))

    assert json.loads(json.dumps(encoded)) == encoded
    assert encoded["current_instruction"] == "Fix it"
    assert encoded["transcript"][0]["role"] == "user"
    assert encoded["transcript"][0]["content"] == [{"type": "text", "text": "Fix it"}]


def test_encode_state_keeps_the_task_seed_when_the_input_is_a_command() -> None:
    command = LoopInput("ct_1", "cr_1", "/clear")

    encoded = encode_state(command, initial_state(INPUT))

    assert encoded["current_instruction"] == "Fix it"


def test_encode_state_changes_with_the_state() -> None:
    state = initial_state(INPUT)
    later = replace(
        state,
        transcript=state.transcript + (CanonicalMessage("user", (TextContent("more"),)),),
        turn_count=2,
    )

    encoded = encode_state(INPUT, later)

    assert encoded["turn_count"] == 2
    assert [m["content"][0]["text"] for m in encoded["transcript"]] == ["Fix it", "more"]
```

`encoded["transcript"][0]` 의 키 이름이 `role` 이 아니면 `neos/coding/loop/_durable/codec.py:104` `_message_to_mapping` 을 보고 그 키로 맞춘다(형식을 바꾸지 말 것).

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/coding/loop/test_checkpoint_seam.py -q`
Expected: FAIL — `ImportError: cannot import name 'encode_state' from 'neos.coding.loop'`

- [ ] **Step 3: 공개 모듈을 만든다 (믹스인은 아직 그대로)**

`neos/coding/loop/checkpoint.py`:

```python
"""A run's first state and its stored form, seen from outside the loop.

`loop_state` is a persisted format: it is stored on every model and tool step
and resumed across deploys. These two functions are its public seam -- the
loop delegates to them, so callers that build or read a state go through the
same code a run does. What a *restore* does with a stored state (apply edits,
run a queued command) still belongs to the loop.
"""

from __future__ import annotations

from typing import Any

from neos.coding.loop.base import LoopInput
from neos.coding.loop._durable.children import _sync_active_children
from neos.coding.loop._durable.codec import _dump_loop_state, _transcript_digest
from neos.coding.loop._durable.state import AgentLoopState
from neos.coding.loop._durable.transcript import _append_user_text
from neos.coding.model.base import CanonicalMessage, TextContent

__all__ = ["encode_state", "initial_state"]

_CLEARED_NOTICE = "Conversation context was cleared."


def initial_state(input: LoopInput) -> AgentLoopState:
    """The state a run starts from when it has no checkpoint."""
    transcript = _with_workspace_edits(
        (CanonicalMessage("user", (TextContent(input.instruction),)),),
        input.workspace_edits,
    )
    return AgentLoopState(
        transcript=transcript,
        turn_count=0,
        tool_count=0,
        consecutive_tool_errors=0,
        pending_tool_calls=(),
        pending_tool_index=0,
        transcript_digest=_transcript_digest(transcript),
    )


def encode_state(input: LoopInput, state: AgentLoopState) -> dict[str, Any]:
    """`state` as the `loop_state` mapping a checkpoint stores."""
    state = _sync_active_children(state, state.active_children)
    current = (input.instruction or "").strip()
    if not _is_task_seed(current):
        current = _task_seed_text(state.transcript, input) or current
    return _dump_loop_state(state, current_instruction=current)


def _with_workspace_edits(transcript, edits):
    if not edits:
        return transcript
    summary = ", ".join(
        f"{edit.path} @ revision {edit.resulting_revision}"
        for edit in edits
    )
    return _append_user_text(
        transcript,
        "The user directly edited these workspace files. "
        "Treat the listed revisions as authoritative and read "
        f"files before changing them: {summary}",
    )


def _task_seed_text(transcript, input: LoopInput) -> str:
    for message in transcript or ():
        if getattr(message, "role", None) != "user":
            continue
        for item in getattr(message, "content", ()):
            text = getattr(item, "text", None)
            if not isinstance(text, str):
                continue
            candidate = text.strip()
            if _is_task_seed(candidate):
                return candidate
    fallback = (input.instruction or "").strip()
    if _is_task_seed(fallback):
        return fallback
    return ""


def _is_task_seed(text: str) -> bool:
    from neos.coding.commands.interpret import interpret_coding_command
    from neos.coding.commands.types import CommandDisposition

    if not text or text == _CLEARED_NOTICE:
        return False
    return (
        interpret_coding_command(text).disposition is CommandDisposition.CHAT
    )
```

이 세 헬퍼의 본문은 `neos/coding/loop/_durable/checkpoint.py` 의 `_with_workspace_edits`(246행), `_task_seed_text`(218행), `_is_task_seed`(235행)를 **글자 그대로** 옮긴 것이다 — 옮기기 전에 그 파일과 diff 로 대조한다.

`neos/coding/loop/__init__.py` 에 더한다:

```python
from neos.coding.loop._durable.state import AgentLoopState
from neos.coding.loop.checkpoint import encode_state, initial_state
```
그리고 `__all__` 에 `"AgentLoopState"`, `"encode_state"`, `"initial_state"` 를 알파벳 위치에 넣는다. 이 import 는 기존 `from neos.coding.loop.durable import ...` **뒤에** 둔다(순환 import 를 피한다).

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/coding/loop/test_checkpoint_seam.py -q`
Expected: 5 passed

- [ ] **Step 5: 과도기 대조 테스트 — 새 함수가 옛 믹스인과 같은지**

`tests/coding/loop/test_checkpoint_seam.py` 끝에 **임시로** 더한다(Step 8 에서 지운다):

```python
def _old_loop():
    from neos.coding.loop import AnthropicCodingLoop, AnthropicLoopConfig
    from neos.coding.tools.registry import CodingToolRegistry

    return AnthropicCodingLoop(
        model=None,
        tools=CodingToolRegistry.default(),
        executor=None,
        bindings=None,
        config=AnthropicLoopConfig(model="claude-test", system="code"),
    )


@pytest.mark.parametrize(
    "input",
    [INPUT, EDITED, LoopInput("ct_1", "cr_1", "/clear"), LoopInput("ct_1", "cr_1", "")],
)
def test_TRANSITIONAL_seam_matches_the_old_mixin(input) -> None:
    loop = _old_loop()
    assert initial_state(input) == loop._restore(input, None)
    for state in (initial_state(INPUT), initial_state(input), initial_state(EDITED)):
        assert encode_state(input, state) == loop._dump_state(input, state)
```

Run: `uv run pytest tests/coding/loop/test_checkpoint_seam.py -q`
Expected: 9 passed. 실패하면 옮긴 본문이 원본과 다른 것이다 — 원본과 diff 한다.

- [ ] **Step 6: 믹스인이 공개 함수에 위임하게 바꾼다**

`neos/coding/loop/_durable/checkpoint.py`:

1. import 에 더한다:
```python
from neos.coding.loop.checkpoint import (
    _CLEARED_NOTICE,
    _task_seed_text,
    _with_workspace_edits,
    encode_state,
    initial_state,
)
```
2. 모듈의 `_CLEARED_NOTICE = "Conversation context was cleared."` 정의를 지운다.
3. `_restore` 의 None 분기를 바꾼다:
```python
    def _restore(self, input, checkpoint):
        if checkpoint is None:
            return initial_state(input)
        raw = checkpoint.loop_state
        transcript = _with_workspace_edits(
            tuple(_message_from_mapping(item) for item in raw.get("transcript", [])),
            input.workspace_edits,
        )
```
(그 아래는 그대로.)
4. `_cleared_transcript` 의 `seed = self._task_seed_text(transcript, input)` 를 `seed = _task_seed_text(transcript, input)` 로.
5. staticmethod `_task_seed_text`, `_is_task_seed`, `_with_workspace_edits` 를 지운다.
6. `_dump_state` 를 바꾼다:
```python
    def _dump_state(self, input, state):
        return encode_state(input, state)
```
7. 더 쓰이지 않는 import(`_dump_loop_state`, 필요하면 `TextContent` 등)를 지운다: `uv run ruff check neos/coding/loop/_durable/checkpoint.py neos/coding/loop/checkpoint.py`.

- [ ] **Step 7: 사본이 남지 않았는지 이름으로 확인하고, 과도기 테스트와 루프 테스트를 돌린다**

```bash
grep -rnE "_task_seed_text|_is_task_seed|_with_workspace_edits|_CLEARED_NOTICE" neos
```
Expected: 정의는 `neos/coding/loop/checkpoint.py` 에만, `neos/coding/loop/_durable/checkpoint.py` 에는 import 와 모듈 함수 호출만(`self.`·`CheckpointMixin.` 접두 없음).

Run: `uv run pytest tests/coding/loop -q`
Expected: 기준선과 같은 실패 집합(대개 0) + 새 테스트 9 passed.

- [ ] **Step 8: 과도기 대조 테스트를 지운다**

`_old_loop` 와 `test_TRANSITIONAL_seam_matches_the_old_mixin` 을 지운다(위임 뒤에는 동어반복이고 private 을 겨눈다).
Run: `uv run pytest tests/coding/loop/test_checkpoint_seam.py -q` → 5 passed

- [ ] **Step 9: 커밋**

```bash
git add neos/coding/loop/checkpoint.py neos/coding/loop/_durable/checkpoint.py neos/coding/loop/__init__.py tests/coding/loop/test_checkpoint_seam.py
git commit -m "refactor(coding): expose initial_state/encode_state as the loop checkpoint seam"
```

---

### Task 2: 테스트 지원 모듈과 import 이주

**Files:**
- Create: `tests/coding/loop/support.py`
- Modify: `tests/coding/loop/test_anthropic_loop.py` (헬퍼 정의 제거, support 에서 import)
- Modify: `test_anthropic_loop` 에서 import 하는 36개 파일(목록은 Step 5 의 grep 이 정본)
- Test: `tests/coding/loop/test_support_harness.py` (create)

**Interfaces:**
- Consumes: `neos.coding.loop.encode_state` (Task 1)
- Produces (`tests.coding.loop.support`):
  - `NOW`, `LEASE`, `INPUT`, `Model`, `Events`, `Executor`, `Bindings`, `Session`, `DecisionHook`(옛 `_DecisionHook`)
  - `tool_call(call_id="toolu_1", name="write_file.v1", input=None)`, `completed(input_tokens=5, output_tokens=3)`
  - `async collect(h, checkpoint=None) -> list[CodingEvent]`
  - `harness(turns=(), *, model=None, tools=None, completed_tools=None, executor=None, config=None, audit=None, bindings=None, clock=lambda: NOW, approval_evaluator=..., hooks=None, subagents=None, command_allowlist=frozenset({"git"}), metrics=None, monitor=None, envelope=None, jev=None, user_rules=None, secrets=None, browser=None, device_bridge=None, asks=None) -> Harness`
  - `Harness` 필드: `loop, repository, events, model, executor, bindings, deps, loop_kwargs: dict`; 프로퍼티 `config`; 메서드 `rebuilt(**overrides) -> Harness`
  - `checkpoint_for(state, *, input=INPUT, checkpoint_id="cc_test") -> CodingCheckpoint`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/coding/loop/test_support_harness.py`:

```python
"""The shared loop harness: constructor pass-through and `rebuilt`."""

from dataclasses import replace

import pytest

from neos.coding.loop import initial_state
from neos.coding.model.base import ModelCompleted, ModelUsage
from tests.coding.loop.support import (
    INPUT,
    NOW,
    checkpoint_for,
    collect,
    completed,
    harness,
    tool_call,
)

pytestmark = pytest.mark.no_db


def test_harness_passes_constructor_arguments_through() -> None:
    later = lambda: NOW  # noqa: E731
    rules = object()
    h = harness([], clock=later, user_rules=rules)

    assert h.loop_kwargs["clock"] is later
    assert h.loop_kwargs["user_rules"] is rules
    assert h.config.model == "claude-test"


def test_harness_uses_a_given_model_instead_of_turns() -> None:
    class Custom:
        async def stream(self, request):
            yield ModelCompleted("end_turn", ModelUsage(1, 1))

    model = Custom()
    h = harness(model=model)

    assert h.model is model
    assert h.loop_kwargs["model"] is model


@pytest.mark.asyncio
async def test_rebuilt_shares_the_repository_and_the_model_queue() -> None:
    h = harness([[tool_call(), completed()], [ModelCompleted("end_turn", ModelUsage(1, 1))]])
    await collect(h)
    parked = h.repository.checkpoints[-1]

    again = h.rebuilt(config=replace(h.config, max_turns=h.config.max_turns))

    assert again.loop is not h.loop
    assert again.repository is h.repository
    assert again.model is h.model
    assert again.deps is h.deps
    assert again.config == h.config
    await collect(again, parked)
    assert len(h.repository.checkpoints) > 1


def test_rebuilt_rejects_an_unknown_dependency() -> None:
    with pytest.raises(TypeError):
        harness([]).rebuilt(not_a_dependency=1)


def test_checkpoint_for_encodes_the_state() -> None:
    checkpoint = checkpoint_for(initial_state(INPUT))

    assert checkpoint.loop_state["current_instruction"] == "Fix it"
    assert checkpoint.checkpoint_id == "cc_test"
```

`max_turns` 가 `AnthropicLoopConfig` 의 필드가 아니면 `neos/coding/loop/_durable/state.py:41` `CodingLoopConfig` 의 아무 int 필드 이름으로 바꾼다(값은 그대로 다시 넣는다 — "같은 설정으로 다시 짓기"가 요점이다).

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/coding/loop/test_support_harness.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.coding.loop.support'`

- [ ] **Step 3: `support.py` 를 만든다**

`tests/coding/loop/support.py` 를 만들고, `tests/coding/loop/test_anthropic_loop.py` 의 55–209행(`NOW` … `collect`)과 1493–1508행(`_DecisionHook`)을 **옮긴다**(복사 아님). 그 위에 이 파일이 쓰는 import 를 둔다. 그 다음 아래와 같이 고친다.

`_DecisionHook` → `DecisionHook`(이제 모듈의 공개 부품이다).

`Harness` 와 `harness()` 를 이것으로 바꾼다:

```python
@dataclass
class Harness:
    loop: AnthropicCodingLoop
    repository: InMemoryCodingRunRepository
    events: Events
    model: Any
    executor: Executor
    bindings: Bindings
    deps: LoopDependencies
    #: What the loop was built with -- tests read these instead of the loop's fields.
    loop_kwargs: dict[str, Any] = field(default_factory=dict)

    @property
    def config(self) -> AnthropicLoopConfig:
        return self.loop_kwargs["config"]

    def rebuilt(self, **overrides: Any) -> "Harness":
        """A new loop over the same repository, events and lease.

        A worker that resumes a stored checkpoint under a new deploy is a new
        loop instance; this is that. It is also how a test plugs in a
        dependency that needs this harness's own objects (its repository).
        """
        # TODO(사용자): 무엇을 공유하고 무엇을 새로 지을지 — Step 4 참조.
        raise NotImplementedError


def harness(
    turns=(),
    *,
    model=None,
    tools=None,
    completed_tools=None,
    executor=None,
    config=None,
    audit=None,
    bindings=None,
    clock=lambda: NOW,
    approval_evaluator=lambda _call: ApprovalPolicyOutcome.ALLOW,
    hooks=None,
    subagents=None,
    command_allowlist=frozenset({"git"}),
    metrics=None,
    monitor=None,
    envelope=None,
    jev=None,
    user_rules=None,
    secrets=None,
    browser=None,
    device_bridge=None,
    asks=None,
):
    repository = InMemoryCodingRunRepository(completed_tools=completed_tools)
    repository.execution_leases["ct_1"] = LEASE
    run = CodingRun("cr_1", "ct_1", 1, CodingRunStatus.RUNNING, None, NOW)
    repository.active_run = run
    repository.created_runs = [run]
    repository.task_statuses["ct_1"] = "running"
    events = Events()
    loop_kwargs = dict(
        model=model if model is not None else Model(turns),
        tools=tools
        if tools is not None
        else CodingToolRegistry.default(command_allowlist=frozenset(command_allowlist)),
        executor=executor or Executor(),
        bindings=bindings or Bindings(),
        config=config or AnthropicLoopConfig(model="claude-test", system="code"),
        audit=audit,
        clock=clock,
        approval_evaluator=approval_evaluator,
        hooks=hooks,
        subagents=subagents,
        metrics=metrics,
        monitor=monitor,
        envelope=envelope,
        jev=jev,
        user_rules=user_rules,
        secrets=secrets,
        browser=browser,
        device_bridge=device_bridge,
        asks=asks,
    )
    loop = AnthropicCodingLoop(**loop_kwargs)
    deps = LoopDependencies(repository=repository, events=events, lease=LEASE)
    return Harness(
        loop,
        repository,
        events,
        loop_kwargs["model"],
        loop_kwargs["executor"],
        loop_kwargs["bindings"],
        deps,
        loop_kwargs,
    )


def checkpoint_for(state, *, input=INPUT, checkpoint_id="cc_test") -> CodingCheckpoint:
    """A stored checkpoint that holds `state` -- the way a test starts a run at state X."""
    return CodingCheckpoint(
        checkpoint_id, "ct_1", "cr_1", 1, encode_state(input, state), "1", NOW
    )
```

새로 넘기는 키워드(`metrics`, `jev`, `user_rules`, `secrets`, `browser`, `device_bridge`, `asks`)는 모두 생성자 기본값이 `None` 이라(`neos/coding/loop/durable.py:103-125`) 넘기지 않던 때와 같다.

- [ ] **Step 4: `rebuilt()` 본문 (사용자 기여 지점)**

결정할 것: 새 루프가 옛 Harness 의 무엇을 **공유**하고 무엇을 **새로** 지을지. 이 계획의 기준 구현(사용자가 다르게 정하면 그것을 따른다):

```python
        kwargs = {**self.loop_kwargs, **overrides}
        return replace(
            self,
            loop=AnthropicCodingLoop(**kwargs),
            model=kwargs["model"],
            executor=kwargs["executor"],
            bindings=kwargs["bindings"],
            loop_kwargs=kwargs,
        )
```
근거: 루프는 생성자 밖에서 인스턴스 필드를 쓰지 않는다 — 새 인스턴스로 바꿔도 잃는 상태가 없다. `repository`·`events`·`deps` 는 "저장된 것"이라 공유한다. 덮지 않은 의존성(모델의 남은 턴 큐 포함)도 공유한다 — 옛 테스트는 같은 인스턴스에서 설정만 바꿨으므로, 공유해야 단언이 그대로다. 모르는 키워드는 생성자가 `TypeError` 로 거절한다.

Run: `uv run pytest tests/coding/loop/test_support_harness.py -q` → 5 passed

- [ ] **Step 5: `test_anthropic_loop.py` 가 support 를 쓰게 하고, 36개 파일의 import 를 바꾼다**

```bash
grep -rlE 'from tests\.coding\.loop\.test_anthropic_loop import' tests > $SCRATCH/importers.txt
wc -l < $SCRATCH/importers.txt   # 36
xargs sed -i '' 's/from tests\.coding\.loop\.test_anthropic_loop import/from tests.coding.loop.support import/' < $SCRATCH/importers.txt
perl -pi -e 's/\b_DecisionHook\b/DecisionHook/g' tests/coding/loop/test_durable_contracts.py
```
(macOS `sed` 는 `\b` 를 모른다 — 단어 경계가 필요한 치환은 `perl` 로 한다.)

`test_anthropic_loop.py` 는 옮긴 정의 자리에 `from tests.coding.loop.support import (Bindings, DecisionHook, Events, Executor, INPUT, LEASE, Model, NOW, Session, collect, completed, harness, tool_call)` 중 **그 파일이 쓰는 것만** 넣고, `_DecisionHook` 사용처를 `DecisionHook` 으로 바꾼다.

support 를 거쳐 도메인 타입을 가져오던 곳을 바로잡는다:
```bash
uv run python - <<'EOF'
import ast, pathlib
SUPPORT = {"NOW","LEASE","INPUT","Model","Events","Executor","Bindings","Session","DecisionHook",
           "tool_call","completed","collect","harness","Harness","checkpoint_for"}
for p in pathlib.Path("tests").rglob("*.py"):
    for n in ast.walk(ast.parse(p.read_text())):
        if isinstance(n, ast.ImportFrom) and n.module == "tests.coding.loop.support":
            bad = [a.name for a in n.names if a.name not in SUPPORT]
            if bad: print(p, n.lineno, bad)
EOF
```
나온 이름(예: `test_mcp_pinned.py` 의 `ModelCompleted`, `ModelUsage`)은 원래 모듈(`neos.coding.model.base`)에서 import 하도록 고친다.

- [ ] **Step 6: 정리하고 확인한다**

```bash
uv run ruff check --fix --select F401 tests/coding/loop/test_anthropic_loop.py tests/coding/loop/support.py
uv run ruff check tests/coding tests/standing
grep -rlE 'from tests\.coding\.loop\.test_anthropic_loop import' tests | wc -l   # 0
uv run pytest tests/coding tests/standing --collect-only -qq | grep '::' | sort > $SCRATCH/names_t2.txt
diff $SCRATCH/names_before.txt $SCRATCH/names_t2.txt
```
Expected: ruff 깨끗, importers 0, diff 는 **새 테스트 이름만 추가**(`test_checkpoint_seam.py` 5개, `test_support_harness.py` 5개), 사라진 이름 없음.

Run: `uv run pytest $(cat $SCRATCH/importers.txt) tests/coding/loop/test_anthropic_loop.py tests/coding/loop/test_support_harness.py -q`
Expected: 기준선에서 이 파일들의 실패 집합과 같음.

- [ ] **Step 7: 커밋**

```bash
git add tests/coding/loop/support.py tests/coding/loop/test_support_harness.py tests/coding/loop/test_anthropic_loop.py $(cat $SCRATCH/importers.txt)
git commit -m "test(coding): move the shared loop harness out of a test module into support"
```

---

### Task 3: 의존성 재할당 70곳을 생성자 인자·`rebuilt()` 로

**Files (재할당 수, 2026-10-08):**
`tests/coding/loop/test_spawn_subagent.py`(32) · `test_secret_broker_loop.py`(6) · `test_device_bridge_loop.py`(5) · `test_device_bridge_commands_loop.py`(5) · `tests/coding/connectors/test_mcp_gate.py`(4) · `test_ask_delivery_in_the_loop.py`(3) · `tests/coding/connectors/test_mcp_pinned.py`(3) · `test_device_bridge_writes_loop.py`(2) · `test_agent_browser_loop.py`(2) · `test_user_rules_loop.py`(1) · `test_usage_window.py`(1) · `test_durable_contracts.py`(1) · `test_ask_wait_in_the_loop.py`(1) · `test_ask_answer_roundtrip.py`(1) · `test_anthropic_loop.py`(1) · `tests/standing/test_ask_expiry.py`(1) · `tests/standing/test_ask_counter.py`(1). 정본 목록은 `grep -rnE "$DEPS" tests`.

**Interfaces:**
- Consumes: `harness(...)` 키워드, `Harness.rebuilt(**overrides)`, `Harness.config` (Task 2)

**규칙 — 각 재할당을 셋 중 하나로 바꾼다:**

(R1) 값이 `h` 없이 만들어지고, 그 사이에 런이 없다 → `harness(...)` 키워드로.
```python
# before
clock = TickableClock()
h = harness(_two_spawn_turns(), config=_flag_on(subagent_max_active=2), subagents=runtime)
h.loop._clock = clock
# after
clock = TickableClock()
h = harness(_two_spawn_turns(), config=_flag_on(subagent_max_active=2), subagents=runtime, clock=clock)
```
`h.loop._tools = X` → `tools=X`, `_user_rules`→`user_rules=`, `_secrets`→`secrets=`, `_metrics`→`metrics=`, `_device_bridge`→`device_bridge=`, `_browser`→`browser=`, `_subagents`→`subagents=`. 값을 만드는 줄이 `harness(...)` 아래에 있으면, 그 줄이 `h` 를 쓰지 않는 한 위로 올린다.

(R2) `h.loop._model = X` → `harness(..., model=X)`. 그 뒤에 `h.model = X` 가 따로 있으면 지운다(`harness` 가 `h.model` 을 채운다). 예 — `test_anthropic_loop.py:870-872`:
```python
# before
h = harness([[TextDelta("unused"), completed()]])
h.model = GatedModel()
h.loop._model = h.model
# after
h = harness(model=GatedModel())
```

(R3) 값이 `h` 의 객체를 쓰거나(`h.repository.asks`), `await` 가 필요하거나, **런 뒤에** 바뀐다(`_config` 7곳 전부: `test_spawn_subagent.py` 494·705·1385·1435·1633·1795·1979행 근처) → `h = h.rebuilt(...)`.
```python
# before
h.loop._asks = AgentAsks(store=h.repository.asks, destination=find)
# after
h = h.rebuilt(asks=AgentAsks(store=h.repository.asks, destination=find))

# before (런 사이)
parked = await _park_two(h, clock)
h.loop._config = replace(h.loop._config, subagent_enabled=False)
await collect(h, parked)
# after
parked = await _park_two(h, clock)
h = h.rebuilt(config=replace(h.config, subagent_enabled=False))
await collect(h, parked)
```
`h.loop._config` 를 **읽는** 곳(`replace(h.loop._config, ...)` 등)은 `h.config` 로.

주의: (R3) 를 헬퍼 함수 안에서 하면(예: `_loop()` 가 `h` 를 돌려준다) 재바인딩한 `h` 를 돌려주는지 확인한다. 런 사이 재바인딩 뒤에 옛 `h.loop` 를 붙잡고 있는 변수(예: 앞서 만든 `service`)가 있으면 그 변수도 새 `h` 로 다시 만든다 — 그런 곳이 나오면 단언을 고치지 말고 기록하여 보고한다.

- [ ] **Step 1: 파일 하나(`test_spawn_subagent.py`)에 규칙을 적용한다**

R1(`_clock` 20곳, `_metrics` 5곳) → R3(`_config` 7곳) 순서로. 편집 뒤:
```bash
grep -nE "$DEPS" tests/coding/loop/test_spawn_subagent.py   # 0
uv run pytest tests/coding/loop/test_spawn_subagent.py -q
```
Expected: 기준선의 이 파일 결과와 같음.

- [ ] **Step 2: 커밋**

```bash
git add tests/coding/loop/test_spawn_subagent.py
git commit -m "test(coding): spawn tests build the loop with its clock and config instead of patching them"
```

- [ ] **Step 3: 나머지 16개 파일에 규칙을 적용한다**

각 파일의 `_loop()` 팩토리(`test_mcp_gate.py:289`, `test_mcp_pinned.py:514`, `test_user_rules_loop.py:32`, `test_secret_broker_loop.py:61`, `test_device_bridge_loop.py:66`, `test_device_bridge_commands_loop.py:56`, `test_agent_browser_loop.py:30`)는 재할당을 `harness(...)` 키워드로 옮기기만 한다 — 팩토리들을 합치지 않는다. `port._registry` 처럼 `h` 와 무관한 값은 R1, `await _vault()` 는 R1 로 위에서 `await` 해 둘 수 있으면 R1, 아니면 R3.

```bash
grep -rnE "$DEPS" tests | wc -l   # 0
```

- [ ] **Step 4: 실행하고 커밋한다**

Run: `uv run pytest tests/coding/loop tests/coding/connectors tests/coding/monitor tests/standing -q`
Expected: 기준선의 같은 이름 집합과 같은 결과.

```bash
uv run ruff check tests/coding tests/standing
git add -u tests
git commit -m "test(coding): pass loop dependencies through the harness, never by reassignment"
```

---

### Task 4: `_restore(…, None)`·`_dump_state` 를 공개 이음매로, 그리고 런 수준 동등성

**Files:**
- Modify: `_restore(…, None)`/`_dump_state` 를 쓰는 파일 — `test_durable_contracts.py`, `test_compact_followup.py`, `test_spawn_subagent.py`, `test_command_restore.py`, `test_anthropic_loop.py`, `test_usage_window.py` 등(정본은 Step 1 의 출력)
- Test: `tests/coding/loop/test_checkpoint_seam.py` (런 수준 테스트 추가)

**Interfaces:**
- Consumes: `initial_state`, `encode_state` (Task 1), `harness`, `collect`, `checkpoint_for`, `tool_call`, `completed`, `INPUT` (Task 2)

- [ ] **Step 1: 런 수준 동등성 테스트를 쓴다 (지금도 통과해야 한다 — 이음매가 실제 경로임을 고정한다)**

`tests/coding/loop/test_checkpoint_seam.py` 끝에 더한다:

```python
@pytest.mark.asyncio
async def test_starting_from_the_encoded_initial_state_matches_a_fresh_start() -> None:
    from tests.coding.loop.support import checkpoint_for, collect, completed, harness, tool_call

    fresh = harness([[tool_call(), completed()]])
    seeded = harness([[tool_call(), completed()]])

    await collect(fresh)
    await collect(seeded, checkpoint_for(initial_state(INPUT)))

    assert [c.loop_state for c in seeded.repository.checkpoints] == [
        c.loop_state for c in fresh.repository.checkpoints
    ]
    assert len(seeded.model.requests) == len(fresh.model.requests) == 1
```

Run: `uv run pytest tests/coding/loop/test_checkpoint_seam.py -q` → 6 passed.
(2026-10-08 스크래치 탐침으로 현재 코드에서 같음을 확인했다 — 체크포인트 2개씩, 요청 1개씩.) 실패하면 **멈추고 보고한다** — 체크포인트 재개 경로가 첫 시작과 다르게 동작한다는 뜻이고, 이 리팩터링의 전제를 다시 봐야 한다.

- [ ] **Step 2: 호출을 기계적으로 바꾼다**

```bash
uv run python - <<'EOF'
import re, pathlib
R = re.compile(r"\b\w+\.loop\._restore\(\s*([^,()]+?),\s*None\s*,?\s*\)", re.S)
D = re.compile(r"\b\w+\.loop\._dump_state\(")
for p in pathlib.Path("tests").rglob("*.py"):
    s = p.read_text()
    t = D.sub("encode_state(", R.sub(r"initial_state(\1)", s))
    if t != s:
        p.write_text(t)
        print(p)
EOF
```
출력된 각 파일에 `from neos.coding.loop import encode_state, initial_state` 중 쓰는 것을 import 한다. 여러 줄에 걸친 호출(`h.loop._restore(\n    INPUT, None\n)`)도 이 정규식이 잡는다(`re.S`). 파일별 `_checkpoint()` 헬퍼(`test_compact_followup.py:24`, `test_command_restore.py:13`)는 속만 이렇게 바뀌고 모양·`checkpoint_id` 는 그대로다.

- [ ] **Step 3: 확인한다**

```bash
uv run ruff check tests/coding tests/standing
uv run python - <<'EOF'
import re, pathlib
n = sum(len(re.findall(r"\w+\.loop\._restore\(\s*[^,()]+,\s*None\s*,?\s*\)", p.read_text())) for p in pathlib.Path("tests").rglob("*.py"))
print("restore_none", n)
EOF
grep -rnE '\._dump_state\(' tests | wc -l     # 0
grep -rnE '\._restore\(' tests/coding | grep -v ', None' | wc -l   # 25 (C 로 남는다)
```
Expected: `restore_none 0`, dump 0, 체크포인트로부터의 restore 25.

Run: `uv run pytest tests/coding/loop -q`
Expected: 기준선과 같은 결과 + 새 테스트.

- [ ] **Step 4: 커밋**

```bash
git add -u tests && git add tests/coding/loop/test_checkpoint_seam.py
git commit -m "test(coding): start loop tests from initial_state/encode_state instead of loop privates"
```

---

### Task 5: 최종 검증

**Files:** 없음(필요하면 spec 의 상태 줄).

- [ ] **Step 1: 이름 대조**

```bash
uv run pytest tests/coding tests/standing --collect-only -qq | grep '::' | sort > $SCRATCH/names_after.txt
comm -23 $SCRATCH/names_before.txt $SCRATCH/names_after.txt   # 사라진 이름: 비어야 한다
comm -13 $SCRATCH/names_before.txt $SCRATCH/names_after.txt   # 새 이름: 새 테스트 11개만
```

- [ ] **Step 2: 결과 대조**

```bash
uv run pytest tests/coding tests/standing -q -rA -p no:randomly > $SCRATCH/run_after.txt 2>&1; tail -3 $SCRATCH/run_after.txt
grep -E '^(PASSED|FAILED|ERROR|XPASS|XFAIL) ' $SCRATCH/run_after.txt | sort > $SCRATCH/outcomes_after.txt
comm -13 <(grep -E '^(FAILED|ERROR) ' $SCRATCH/outcomes_before.txt) <(grep -E '^(FAILED|ERROR) ' $SCRATCH/outcomes_after.txt)
```
Expected: 새로 실패한 이름 없음. 하나뿐이고 그것이 알려진 흔들리는 테스트(`[modal]` 잘린 꼬리)면 그 파일만 다시 돌려 확인한다.

- [ ] **Step 3: 지표**

Task 0 Step 3 의 블록을 다시 돌려 `$SCRATCH/metrics_after.txt` 로 저장하고 대조한다.
Expected: `deps 0`, `restore_none 0`, `dump 0`, `importers 0`, `spies 3`(그대로).

- [ ] **Step 4: CI 의 Ruff 명령 그대로**

```bash
uv run --frozen ruff check neos/workflow/deep_analysis neos/coding neos/subagent neos/fsi neos/univer neos/config neos/learn neos/jev tests/workflow/deep_analysis tests/coding tests/subagent tests/fsi tests/univer tests/k_skill tests/security_audit tests/learn tests/jev tests/config tests/conftest.py
```
Expected: `All checks passed!` (`tests/standing` 은 CI 목록에 없지만 Task 3·4 에서 이미 확인했다.)

- [ ] **Step 5: spec 상태를 고치고 커밋**

`docs/superpowers/specs/2026-10-08-coding-loop-checkpoint-seam-design.md` 의 `- 상태: 설계 승인 대기` 를 `- 상태: 구현 완료(2026-10-08) — 지표는 계획 Task 5 대로` 로.

```bash
git add docs/superpowers/specs/2026-10-08-coding-loop-checkpoint-seam-design.md docs/superpowers/plans/2026-10-08-coding-loop-checkpoint-seam.md
git commit -m "docs(spec): coding loop checkpoint seam landed"
```

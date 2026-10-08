# 코딩 루프 컴포넌트(도구 카탈로그·컴팩션·사용량·체크포인트 복원) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `DurableCodingLoop` 의 믹스인 둘(`ToolCatalogMixin`, `CompactionMixin`)과 사용량 메서드·체크포인트 복원을 독립 컴포넌트·공개 함수로 꺼내, 테스트가 루프의 private 멤버 대신 그것을 직접 짓고 부르게 한다 — 행동 변경 없이.

**Architecture:** 의존 사슬 순서로 꺼낸다 — `ToolCatalog`(도구·설정) → 사용량 함수(설정) → `Compactor`(설정·훅·모델·카탈로그) → `restore_state`(카탈로그·컴팩터). 각 단계에서 메서드 본문은 글자 그대로 옮기고(`self.` 대상만 바뀐다) 루프 안 호출부를 컴포넌트로 돌린 뒤, 그 개념의 테스트를 옮긴다. 테스트 하네스는 루프와 같은 생성자로 컴포넌트를 짓는다.

**Tech Stack:** Python 3.12, pytest(asyncio), uv, ruff.

**Spec:** `docs/superpowers/specs/2026-10-08-coding-loop-components-design.md` (§3.5b 의 판정 포함)

## Global Constraints

- 순수 리팩터링: 체크포인트 형식, 모델 요청, 이벤트, 예외를 바꾸지 않는다. 옮기는 본문은 글자 그대로.
- 범위: `neos/coding/loop/` 와 그 테스트. 같은 이름의 메서드가 다른 클래스(`bindings.py`, `guest.py`, `managed_driver.py`, `workspace_service.py` 의 `_restore`·`_digest`)에도 있다 — **건드리지 않는다.** grep 은 `neos/coding/loop` 로 좁힌다.
- 범위 밖: `ModelTurnMixin`·`ToolExecutionMixin`·`SubagentSpawnMixin`·`SpawnClaimsMixin`·`TurnTransitionsMixin` 의 구조(호출부만 바뀐다), `_advance_detached_children` 스파이, `_guard_thinking_prefix`·`_after_result`·`_price_child_usage` 등 남는 테스트 접근.
- 공개 이름은 옛 이름에서 밑줄만 뗀다(예외: `_tool_definitions` → `ToolCatalog.definitions`, `_revealed_from_transcript` → `ToolCatalog.revealed_from`, `_tool_allowed_by_skills` → `ToolCatalog.allowed_by_skills`).
- 컴포넌트의 기본값은 컴포넌트 안에 산다(`Compactor(hooks=None)` → `NullCodingHooks()`), 루프와 하네스가 같은 생성자를 쓴다. 루프에 컴포넌트를 내놓는 공개 속성은 두지 않는다.
- 단언 규칙: 기댓값·의미는 바꾸지 않는다. 대상 식은 같은 값을 돌려주는 공개 인터페이스로 옮길 수 있고, 하나하나 보고한다. 기댓값까지 바뀌어야 하면 멈추고 보고한다.
- 검증은 테스트 **이름**으로. `-p no:randomly`, `-o addopts=""` 금지. 결과 줄은 `^(PASSED|FAILED|ERROR|XPASS|XFAIL) \S+::` 로만.
- 브랜치 `refactor/coding-loop-components`(B 브랜치 7c4d4869 위). 커밋 메시지에 Co-Authored-By 금지.
- 알려진 흔들림: `tests/coding/sandbox/test_managed_secret_channel.py::test_a_truncated_tail_of_the_value_is_scrubbed_on_managed_output[modal]` — 그것만 실패하면 그 파일을 3번 다시 돌려 기록한다.

## Review Focus

1. **하네스가 지은 컴포넌트와 루프 것이 갈라진다** — 같은 입력에서 같은 결과. → Task 4 `test_the_harness_components_match_the_loop_run`.
2. **`/compact` 대기 명령이 복원 중에 컴팩터를 거친다** — 복원 결과 대화가 지금과 같아야 한다. → `test_command_restore.py`(옮긴 뒤에도 같은 단언) + Task 4 과도기 대조.
3. **훅 기본값** — 훅 없이 지은 컴팩터가 `None` 을 부르지 않는다. → Task 3 `test_a_compactor_without_hooks_uses_the_null_hooks`.
4. **도구 정의 필터(단계·드러냄·스킬·서브에이전트 off)** — 카탈로그로 옮긴 뒤 같은 목록. → Task 1 과도기 대조.
5. **사용량 창 계산** — `transcript_token_limit` 이 context window 유무 모두에서 같은 값. → Task 2 테스트.

---

## 공통

```bash
cd /Users/ywsung/Desktop/neos
SCRATCH=<controller 가 dispatch 때 준다>
L=neos/coding/loop
```
과도기 대조 테스트(각 Task 의 `test_*_transition.py`)는 옮기기 **전**에 통과해야 하고(옛 믹스인 대 새 컴포넌트), 위임 뒤 지운다 — A·B 와 같은 방식.

---

### Task 0: 기준선 (controller)

- [ ] 이름·결과: `tests/coding tests/standing` 수집 이름과 `-rA` 이름별 결과를 `$SCRATCH` 에.
- [ ] 지표(`$SCRATCH/metrics_before.txt`):
```bash
echo "compaction $(grep -rnoE '\bloop\.(_compact_after_prompt_too_long|_compact|_maybe_llm_compact|_compact_with_hook|_over_budget|_compaction_request|_estimated_tokens|_digest)\b' tests | wc -l)"   # 25
echo "catalog $(grep -rnoE '\bloop\._tool_definitions\b' tests | wc -l)"                                   # 8
echo "usage $(grep -rnoE '\bloop\.(_check_usage_budgets|_price_tokens|_transcript_token_limit|_parent_headroom_chars)\b' tests | wc -l)"   # 8
echo "aliases $(grep -rnoE '\bloop\.(_shrink_old_tool_results|_expand_artifact_refs|_maybe_ref_latest_tool_result)\b' tests | wc -l)"   # 8
echo "restore_cp $(grep -rnoE '\bloop\._restore\(' tests | wc -l)"                                          # 25
echo "mixins $(grep -rhE '^class \w+Mixin' neos/coding/loop/_durable | wc -l)"                             # 8
echo "dump_state_src $(grep -rnoE 'self\._dump_state\(' neos/coding/loop | wc -l)"                        # 7
```

---

### Task 1: `ToolCatalog`

**Files:**
- Modify: `neos/coding/loop/_durable/tool_catalog.py` (믹스인 → 클래스), `neos/coding/loop/durable.py` (기반 클래스 목록에서 `ToolCatalogMixin` 제거, `__init__` 에서 `self._catalog`), 호출부: `_durable/model_turn.py`(`_tool_definitions` 1), `_durable/tools.py`(`_tool_allowed_by_skills` 3), `_durable/transitions.py`(`_announce_reveals` 2, `_revealed_from_transcript` 1), `_durable/checkpoint.py`(`_revealed_from_transcript` 1), `_durable/compaction.py`(`_revealed_from_transcript` 2), `neos/coding/loop/__init__.py`
- Modify: `tests/coding/loop/support.py` (`Harness.catalog()`)
- Modify tests: `loop._tool_definitions` 를 쓰는 곳(8곳: `test_compact_followup.py` 등 — `grep -rn 'loop\._tool_definitions' tests` 가 정본)
- Test: `tests/coding/loop/test_tool_catalog_transition.py` (과도기, Step 5 에서 삭제)

**Interfaces:**
- Produces: `neos.coding.loop.ToolCatalog(tools, config)` with `definitions(state)`, `allowed_by_skills(name, state) -> bool` (staticmethod 유지), `revealed_from(transcript) -> frozenset[str]`, `announce_reveals(transcript, before, after)`; private `_registry_tool_names()`, `_union_skill_allowed_tools(...)`. Loop field `self._catalog`.
- Produces: `Harness.catalog() -> ToolCatalog` = `ToolCatalog(self.loop_kwargs["tools"], self.config)`.

- [ ] **Step 1: 클래스를 사본으로 만든다(믹스인은 그대로 둔다)**

`tool_catalog.py` 에 믹스인 아래 새 클래스를 둔다. 본문은 믹스인 메서드에서 글자 그대로 복사하고 이름만 바꾼다:
```python
class ToolCatalog:
    """Which tools the model sees this step, and which a transcript has revealed.

    Built from the registry and the loop config; holds no state of its own.
    """

    def __init__(self, tools, config) -> None:
        self._tools = tools
        self._config = config

    @staticmethod
    def allowed_by_skills(name: str, state: AgentLoopState) -> bool: <_tool_allowed_by_skills 본문>
    def definitions(self, state: AgentLoopState): <_tool_definitions 본문, self._tool_allowed_by_skills → self.allowed_by_skills>
    def _registry_tool_names(self) -> frozenset[str]: <그대로>
    def _union_skill_allowed_tools(self, ...): <그대로>
    def revealed_from(self, transcript) -> frozenset[str]: <_revealed_from_transcript 본문>
    def announce_reveals(self, transcript, before, after): <_announce_reveals 본문>
```
본문이 `self._tools`·`self._config` 외의 루프 필드를 읽으면 멈추고 보고한다(2026-10-09 grep: 둘뿐).

- [ ] **Step 2: 과도기 대조**

`tests/coding/loop/test_tool_catalog_transition.py`: 같은 하네스 루프로 (가) `h.loop._tool_definitions(state)` 와 (나) `ToolCatalog(h.loop_kwargs["tools"], h.config).definitions(state)` 의 도구 이름 목록·순서가 같은지 — 상태 변주: 기본, `phase` 를 바꾼 상태, `revealed_tools` 가 있는 상태, 스킬 허용 목록이 있는 상태(`AgentLoopState` 필드를 읽고 고른다), `subagent_enabled=False` 설정. `revealed_from` 도 `search_tools.v1` 를 쓴 대화 하나로 대조한다. 통과해야 한다.

- [ ] **Step 3: 루프가 카탈로그를 쓴다**

- `durable.py`: 기반 목록에서 `ToolCatalogMixin` 제거, `from ... tool_catalog import ToolCatalog`, `__init__` 에서 `self._config`·`self._tools` 를 정한 뒤 `self._catalog = ToolCatalog(tools, config)`.
- 호출부 치환(위 Files 목록): `self._tool_definitions(` → `self._catalog.definitions(`, `self._tool_allowed_by_skills(` → `self._catalog.allowed_by_skills(`, `self._revealed_from_transcript(` → `self._catalog.revealed_from(`, `self._announce_reveals(` → `self._catalog.announce_reveals(`.
- `ToolCatalogMixin` 클래스를 지운다.
- `__init__.py`: `ToolCatalog` 를 재수출(`__all__` 포함).
- `grep -rnE "_tool_definitions|_tool_allowed_by_skills|_revealed_from_transcript|_announce_reveals|ToolCatalogMixin" neos/coding/loop` → 0줄.
- Step 2 의 과도기 테스트는 지운 믹스인 메서드를 부르므로 이제 깨진다 — 지운다(옮김의 동등성은 Step 2 의 통과가 증거다).

- [ ] **Step 4: 하네스와 테스트**

`support.py`:
```python
    def catalog(self) -> ToolCatalog:
        """The tool catalog this harness's loop was built with."""
        return ToolCatalog(self.loop_kwargs["tools"], self.config)
```
테스트 치환: `h.loop._tool_definitions(X)` → `h.catalog().definitions(X)` (8곳).

- [ ] **Step 5: 확인·커밋**

```bash
grep -rnoE '\bloop\._tool_definitions\b' tests | wc -l     # 0
uv run pytest tests/coding/loop tests/coding/connectors -q -p no:randomly
uv run ruff check neos/coding/loop tests/coding
git add -A neos/coding/loop tests/coding
git commit -m "refactor(coding): the tool catalog is a component the loop holds, not a mixin"
```

---

### Task 2: 사용량·창 함수

**Files:**
- Modify: `neos/coding/loop/_durable/usage.py` (함수 2개 추가), `neos/coding/loop/durable.py` (메서드 4개 삭제, 호출부), `_durable/model_turn.py`(`_check_usage_budgets` 3), `_durable/spawn.py`(`_parent_headroom_chars` 1), `_durable/compaction.py`(`_transcript_token_limit` 1), `neos/coding/loop/__init__.py`
- Modify tests: `loop._check_usage_budgets`·`_price_tokens`·`_transcript_token_limit`·`_parent_headroom_chars` (8곳)
- Test: `tests/coding/loop/test_usage_functions.py` (create)

**Interfaces:**
- Produces (`usage.py`, 재수출): `price_tokens(config, input_tokens, output_tokens, *, cache_read_tokens=0, cache_write_tokens=0) -> int`(있음), `check_usage_budgets(config, state) -> None`(있음), `transcript_token_limit(config) -> int`(신규, `DurableCodingLoop._transcript_token_limit` 본문), `parent_headroom_chars(config, state) -> int`(신규, `_parent_headroom_chars` 본문, `self._transcript_token_limit()` → `transcript_token_limit(config)`).

- [ ] **Step 1: 실패하는 테스트**

`tests/coding/loop/test_usage_functions.py`:
```python
"""Usage and window arithmetic: pure functions of the loop config."""

from dataclasses import replace

import pytest

from neos.coding.loop import AnthropicLoopConfig, parent_headroom_chars, transcript_token_limit
from neos.coding.loop import initial_state
from tests.coding.loop.support import INPUT

pytestmark = pytest.mark.no_db

BASE = AnthropicLoopConfig(model="claude-test", system="code")


def test_without_a_context_window_the_transcript_cap_is_the_configured_one() -> None:
    config = replace(BASE, context_window=None, max_transcript_tokens=12_345)

    assert transcript_token_limit(config) == 12_345


def test_with_a_context_window_the_cap_is_the_usable_window() -> None:
    config = replace(BASE, context_window=40_000, max_output_tokens=8_192, max_transcript_tokens=80_000)

    assert transcript_token_limit(config) < 40_000


def test_parent_headroom_is_four_chars_per_remaining_token() -> None:
    config = replace(BASE, context_window=None, max_transcript_tokens=1_000)
    state = replace(initial_state(INPUT), last_prompt_tokens=400)

    assert parent_headroom_chars(config, state) == 600 * 4


def test_headroom_never_goes_negative() -> None:
    config = replace(BASE, context_window=None, max_transcript_tokens=100)
    state = replace(initial_state(INPUT), last_prompt_tokens=10_000)

    assert parent_headroom_chars(config, state) == 0
```
`AnthropicLoopConfig` 의 필드 이름(`context_window`, `max_output_tokens`, `max_transcript_tokens`, `input_limit`, `thinking_budget`)을 `_durable/state.py` 의 `CodingLoopConfig` 와 대조하고 다르면 맞춘다. 두 번째 테스트의 기댓값은 `usable_window_tokens` 를 읽고 정확한 값으로 바꿔도 된다(새 테스트다).

Run → FAIL (`ImportError: cannot import name 'parent_headroom_chars'`).

- [ ] **Step 2: 함수로 옮긴다**

`usage.py` 끝에 `transcript_token_limit(config)` 와 `parent_headroom_chars(config, state)` — `durable.py` 의 두 메서드 본문을 글자 그대로(`self._config` → `config`). `usable_window_tokens` 등 필요한 import 를 옮긴다.
`durable.py`: `_price_tokens`, `_check_usage_budgets`, `_transcript_token_limit`, `_parent_headroom_chars` 메서드를 지운다. 호출부: `self._check_usage_budgets(state)` → `check_usage_budgets(self._config, state)` (durable 1, model_turn 3), `self._transcript_token_limit()` → `transcript_token_limit(self._config)` (durable 1, compaction 1), `self._parent_headroom_chars(state)` → `parent_headroom_chars(self._config, state)` (spawn 1). `_price_tokens` 는 루프 안 호출이 0 이다(2026-10-09) — 지운다.
`__init__.py`: 네 함수를 재수출.
`grep -rnE "_price_tokens|_check_usage_budgets|_transcript_token_limit|_parent_headroom_chars" neos/coding/loop` → 0줄.

- [ ] **Step 3: 테스트 치환**

`h.loop._check_usage_budgets(s)` → `check_usage_budgets(h.config, s)`; `h.loop._price_tokens(a, b, **kw)` → `price_tokens(h.config, a, b, **kw)`; `h.loop._transcript_token_limit()` → `transcript_token_limit(h.config)`; `h.loop._parent_headroom_chars(s)` → `parent_headroom_chars(h.config, s)`. 하네스가 아닌 루프(`loop = AnthropicCodingLoop(...)` 를 직접 지은 테스트)면 그 테스트가 넘긴 `config` 를 쓴다.

- [ ] **Step 4: 확인·커밋**

```bash
grep -rnoE '\bloop\.(_check_usage_budgets|_price_tokens|_transcript_token_limit|_parent_headroom_chars)\b' tests | wc -l   # 0
uv run pytest tests/coding/loop tests/standing -q -p no:randomly
uv run ruff check neos/coding/loop tests/coding tests/standing
git add -A neos/coding/loop tests/coding tests/standing
git commit -m "refactor(coding): usage and window limits are functions of the config, not loop methods"
```

---

### Task 3: `Compactor`

**Files:**
- Modify: `neos/coding/loop/_durable/compaction.py` (믹스인 → 클래스), `durable.py`(기반 목록·`__init__`), 호출부: `_durable/model_turn.py`(`_compact_after_prompt_too_long` 1, `_head_drop_after_prompt_too_long` 1, `_digest` 1), `_durable/transitions.py`(`_compact_with_hook` 2, `_digest` 1, `_maybe_ref_latest_tool_result` 1), `_durable/checkpoint.py`(`_compact_command` 의 `loop._compact` 1, `_digest` 1), `neos/coding/loop/__init__.py`
- Modify: `tests/coding/loop/support.py` (`Harness.compactor()`)
- Modify tests: 컴팩션 25곳 + 별칭 8곳 (지표 명령이 정본)
- Test: `tests/coding/loop/test_compactor.py` (create), `tests/coding/loop/test_compactor_transition.py` (과도기)

**Interfaces:**
- Consumes: `ToolCatalog`(Task 1), `transcript_token_limit`(Task 2).
- Produces: `neos.coding.loop.Compactor(*, config, hooks=None, model, catalog)` with public `compact_after_prompt_too_long(state)` (async), `head_drop_after_prompt_too_long(state)`, `compact_with_hook(...)` (async), `compact(transcript, *, force=False, bodies=None)`, `over_budget(transcript) -> bool`, `require_transcript_fit(transcript)`, `maybe_llm_compact(state, transcript)` (async), `compaction_request(prompt) -> tuple[ModelRequest, bool]`; private `_over_bytes`, `_recent_read_preview`, `_recent_read_paths`. Loop field `self._compactor`.
- Produces (재수출): `transcript_digest`(= `codec._transcript_digest`), `estimated_tokens`(= `codec._estimated_tokens`), `shrink_old_tool_results`, `expand_artifact_refs`, `maybe_ref_latest_tool_result`(= `artifact_refs` 의 같은 이름 private 함수).
- Produces: `Harness.compactor() -> Compactor` = `Compactor(config=self.config, hooks=self.loop_kwargs["hooks"], model=self.loop_kwargs["model"], catalog=self.catalog())`.

- [ ] **Step 1: 클래스를 사본으로 만든다**

믹스인 아래:
```python
class Compactor:
    """Keeps a transcript inside its window: mechanical compaction, the head
    drop after `prompt_too_long`, and the optional LLM summary.

    Holds the config, hooks, model and tool catalog it was built with; no
    state of its own.
    """

    def __init__(self, *, config, hooks=None, model, catalog) -> None:
        self._config = config
        self._hooks = hooks if hooks is not None else NullCodingHooks()
        self._model = model
        self._catalog = catalog
```
메서드: 믹스인의 각 메서드 본문을 글자 그대로, 이름은 공개 목록대로(밑줄 제거), 내부 호출도 새 이름으로(`self._compact(` → `self.compact(`, `self._over_budget(` → `self.over_budget(` …). 그 밖의 치환: `self._revealed_from_transcript(` → `self._catalog.revealed_from(`, `self._transcript_token_limit()` → `transcript_token_limit(self._config)`, `self._digest(` → `_transcript_digest(`, `self._estimated_tokens(` → `_estimated_tokens(`, 별칭 `self._shrink_old_tool_results(` 등 → `artifact_refs._shrink_old_tool_results(` 등. `NullCodingHooks` 는 루프가 쓰는 그것을 import 한다(`durable.py` 의 import 를 보고 같은 경로).
루프가 `hooks or NullCodingHooks()` 를 쓰는지 확인한다 — 컴팩터의 `hooks if hooks is not None else` 와 의미가 다르면(예: 거짓 같은 훅 객체) 루프와 같은 식(`hooks or NullCodingHooks()`)을 쓴다.

- [ ] **Step 2: 과도기 대조**

`tests/coding/loop/test_compactor_transition.py`: 하네스 루프의 옛 믹스인 메서드와 새 `Compactor(config=h.config, hooks=<루프의 self._hooks 와 같은 객체>, model=h.model, catalog=h.catalog())` 를 같은 입력으로 — `compact`(긴 대화, `force=True`, `bodies` 있음/없음), `over_budget`(짧은/긴), `head_drop_after_prompt_too_long`(접두 턴이 있는 상태), `compact_after_prompt_too_long`(훅 없음; 결과 상태의 `transcript`·`compacted_bodies`·`revealed_tools`·`prompt_compact_retries` 비교), `compaction_request("summarize")`(요청의 `limits.effort`·메시지). 기존 테스트(`test_compact_followup.py`, `test_durable_contracts.py` 의 컴팩션 테스트)가 쓰는 입력 빌더를 재사용한다. 통과해야 한다.

- [ ] **Step 3: 루프가 컴팩터를 쓴다**

- `durable.py`: 기반 목록에서 `CompactionMixin` 제거; `__init__` 에서 `self._catalog` 다음에 `self._compactor = Compactor(config=config, hooks=self._hooks, model=model, catalog=self._catalog)`.
- 호출부: `self._compact_after_prompt_too_long(` → `self._compactor.compact_after_prompt_too_long(`, `self._head_drop_after_prompt_too_long(` → `self._compactor.head_drop_after_prompt_too_long(`, `self._compact_with_hook(` → `self._compactor.compact_with_hook(`, `_compact_command` 의 `loop._compact(` → `loop._compactor.compact(`, `self._digest(` → `_transcript_digest(`(model_turn·transitions·checkpoint), `self._maybe_ref_latest_tool_result(` → `artifact_refs._maybe_ref_latest_tool_result(`(transitions).
- `CompactionMixin` 을 지운다(모듈 함수 `extract_preserved_summary`·`_drop_oldest_prefix_turn`·`_split_head` 는 남는다).
- `__init__.py`: `Compactor`, `extract_preserved_summary`, `transcript_digest`, `estimated_tokens`, `shrink_old_tool_results`, `expand_artifact_refs`, `maybe_ref_latest_tool_result` 재수출(밑줄 없는 이름으로 — `from ...codec import _transcript_digest as transcript_digest` 형태).
- `grep -rnE "CompactionMixin|self\._(compact|compact_after_prompt_too_long|head_drop_after_prompt_too_long|compact_with_hook|maybe_llm_compact|compaction_request|over_budget|over_bytes|require_transcript_fit|recent_read_paths|recent_read_preview|digest|estimated_tokens|shrink_old_tool_results|expand_artifact_refs|maybe_ref_latest_tool_result|drop_oldest_prefix_turn|serialized_bytes|compact_ref_path)\b" neos/coding/loop` → 0줄(컴팩터 클래스 안의 `self.compact(` 등 공개 이름 호출은 해당 없음).
- 과도기 테스트를 지운다.

- [ ] **Step 4: 하네스·새 테스트·테스트 치환**

`support.py`:
```python
    def compactor(self) -> Compactor:
        """The compactor this harness's loop was built with."""
        return Compactor(
            config=self.config,
            hooks=self.loop_kwargs["hooks"],
            model=self.loop_kwargs["model"],
            catalog=self.catalog(),
        )
```
`tests/coding/loop/test_compactor.py`:
```python
"""The compactor as a component: built on its own, same defaults as the loop's."""

import pytest

from neos.coding.loop import Compactor, ToolCatalog, initial_state
from neos.coding.loop.hooks import NullCodingHooks
from tests.coding.loop.support import INPUT, harness

pytestmark = pytest.mark.no_db


def test_a_compactor_without_hooks_uses_the_null_hooks() -> None:
    h = harness([])
    compactor = Compactor(config=h.config, model=h.model, catalog=ToolCatalog(h.loop_kwargs["tools"], h.config))

    assert isinstance(compactor._hooks, NullCodingHooks)


@pytest.mark.asyncio
async def test_a_compactor_without_hooks_still_compacts_after_prompt_too_long() -> None:
    h = harness([])
    state = initial_state(INPUT)

    after = await h.compactor().compact_after_prompt_too_long(state)

    assert after.prompt_compact_retries == state.prompt_compact_retries + 1
```
(`NullCodingHooks` 의 import 경로는 루프가 쓰는 것과 같게. 첫 테스트가 `_hooks` 를 읽는 것은 컴포넌트 자신의 기본값을 고정하는 단위 테스트라 허용한다 — 보고서에 적는다.)
테스트 치환: `h.loop._compact_after_prompt_too_long(` → `h.compactor().compact_after_prompt_too_long(`, `h.loop._compact(` → `h.compactor().compact(`, `h.loop._compact_with_hook(` → `h.compactor().compact_with_hook(`, `h.loop._maybe_llm_compact(` → `h.compactor().maybe_llm_compact(`, `h.loop._compaction_request(` → `h.compactor().compaction_request(`, `h.loop._over_budget(` → `h.compactor().over_budget(`, `h.loop._estimated_tokens(` → `estimated_tokens(`, `h.loop._digest(` → `transcript_digest(`, `h.loop._shrink_old_tool_results(` → `shrink_old_tool_results(`, `h.loop._expand_artifact_refs(` → `expand_artifact_refs(`, `h.loop._maybe_ref_latest_tool_result(` → `maybe_ref_latest_tool_result(`. 한 테스트 안에서 같은 컴팩터를 여러 번 쓰면 `compactor = h.compactor()` 로 한 번 짓는다. `from neos.coding.loop._durable.compaction import extract_preserved_summary` 같은 private 경로 import 는 `from neos.coding.loop import ...` 로.

- [ ] **Step 5: 확인·커밋**

```bash
grep -rnoE '\bloop\.(_compact_after_prompt_too_long|_compact|_maybe_llm_compact|_compact_with_hook|_over_budget|_compaction_request|_estimated_tokens|_digest)\b' tests | wc -l   # 0
grep -rnoE '\bloop\.(_shrink_old_tool_results|_expand_artifact_refs|_maybe_ref_latest_tool_result)\b' tests | wc -l   # 0
uv run pytest tests/coding tests/standing -q -p no:randomly
uv run ruff check neos/coding tests/coding tests/standing
git add -A neos/coding/loop tests/coding tests/standing
git commit -m "refactor(coding): compaction is a Compactor component; its primitives are public functions"
```

---

### Task 4: `restore_state` — 이음매의 디코드 쪽, 그리고 `_dump_state` 제거

**Files:**
- Modify: `neos/coding/loop/checkpoint.py` (공개 `restore_state` + 대기 명령 처리기 이주), `neos/coding/loop/_durable/checkpoint.py` (`_restore` 위임, 처리기·`_apply_pending_command`·`_cleared_transcript`·`_dump_state` 제거), `durable.py`(`_dump_state` 1), `_durable/tools.py`(`_dump_state` 6), `neos/coding/loop/__init__.py`
- Modify: `tests/coding/loop/support.py` (`Harness.restore()`)
- Modify tests: `loop._restore(` 25곳
- Test: `tests/coding/loop/test_checkpoint_seam.py` (런 수준 고정 테스트 추가), `tests/coding/loop/test_restore_transition.py`(과도기)

**Interfaces:**
- Consumes: `ToolCatalog.revealed_from`, `Compactor.compact` (Tasks 1, 3).
- Produces: `neos.coding.loop.restore_state(input, checkpoint, *, catalog, compactor) -> AgentLoopState`; `Harness.restore(checkpoint, *, input=INPUT) -> AgentLoopState`.

- [ ] **Step 1: `restore_state` 를 사본으로**

`neos/coding/loop/checkpoint.py` 에 더한다(`__all__` 에 `restore_state`). 본문은 `CheckpointMixin._restore` 의 체크포인트 분기(옛 `_restore` 의 `raw = checkpoint.loop_state` 부터 `return _sync_active_children(...)` 까지)를 글자 그대로, 치환: `self._revealed_from_transcript(` → `catalog.revealed_from(`, `self._digest(` → `_transcript_digest(`, `self._apply_pending_command(input, state, text)` → 모듈 함수 `_apply_pending_command(input, state, text, compactor=compactor)`.
같은 모듈로 옮긴다(글자 그대로): `_note`, `_compact_command`, `_clear_command`, `_cost_command`, `_PENDING_COMMANDS`, `_apply_pending_command`(메서드 → 함수), `_cleared_transcript`(메서드 → 함수). 처리기 시그니처의 `loop` 인자는 `compactor` 로: `_compact_command(compactor, input, state, decision)` 안의 `loop._compactor.compact(` → `compactor.compact(`; `_clear_command` 의 `loop._cleared_transcript(` → `_cleared_transcript(`. 타입 주석용 `ToolCatalog`·`Compactor` import 는 `if TYPE_CHECKING:` 안에 둔다(런타임 순환 방지). `_message_from_mapping`·`_state_from_mapping`·`_sync_active_children` 등 필요한 import 를 더한다.
`_durable/checkpoint.py` 는 아직 그대로(사본 단계).

- [ ] **Step 2: 과도기 대조**

`tests/coding/loop/test_restore_transition.py`: 옛 `h.loop._restore(INPUT, ckpt)` 와 새 `restore_state(INPUT, ckpt, catalog=h.catalog(), compactor=h.compactor())` 가 같은 `AgentLoopState` 를 내는지(`==`) — 체크포인트 변주: 대기 명령 없음, `/compact keep plan`, `/clear`, `/cost`, `/plan auth flow`, `/not-real`, 열린 도구 호출이 있는 상태의 대기 명령(적용되지 않아야 함), 작업 공간 편집이 있는 입력, 드러난 도구가 있는 대화, 활성 자식이 있는 상태. `test_command_restore.py` 의 `_checkpoint(h, instruction, **overrides)` 와 `test_spawn_subagent.py` 의 체크포인트 빌더를 재사용한다. 통과해야 한다.

- [ ] **Step 3: 루프가 위임하고, `_dump_state` 를 없앤다**

- `_durable/checkpoint.py`:
```python
    def _restore(self, input, checkpoint):
        if checkpoint is None:
            return initial_state(input)
        return restore_state(
            input, checkpoint, catalog=self._catalog, compactor=self._compactor
        )
```
  처리기들·`_apply_pending_command`·`_cleared_transcript`·`_dump_state` 를 지운다. 더 쓰이지 않는 import(`_CLEARED_NOTICE`, `_task_seed_text`, `_with_workspace_edits`, `encode_state` 등)를 지운다 — 이제 그 private 헬퍼를 쓰는 곳은 `checkpoint.py` 안뿐이다(**A 의 Minor 3 해소** — `grep -rn "_task_seed_text\|_with_workspace_edits\|_CLEARED_NOTICE" neos` 가 `neos/coding/loop/checkpoint.py` 만 보여야 한다).
- `self._dump_state(input, state)` 7곳(`durable.py` 1, `_durable/tools.py` 6) → `encode_state(input, state)` (import 추가). **A 의 Minor 4 해소.** `grep -rnoE 'self\._dump_state\(' neos/coding/loop` → 0.
- `__init__.py`: `restore_state` 재수출.
- 과도기 테스트를 지운다.

- [ ] **Step 4: 하네스·고정 테스트·테스트 치환**

`support.py`:
```python
    def restore(self, checkpoint, *, input=INPUT) -> AgentLoopState:
        """The state this harness's loop would resume `checkpoint` into."""
        return restore_state(input, checkpoint, catalog=self.catalog(), compactor=self.compactor())
```
`tests/coding/loop/test_checkpoint_seam.py` 끝에(spec §4.3 — 하네스 컴포넌트와 루프 런의 동등성):
```python
@pytest.mark.asyncio
async def test_the_harness_components_match_the_loop_run() -> None:
    """A step resumed by the loop and a step started from `h.restore(...)` commit the same state,
    and the tools the catalog lists are the tools the model was offered."""
    first = harness([[tool_call(), completed()], [ModelCompleted("end_turn", ModelUsage(1, 1))]])
    await collect(first)
    parked = first.repository.checkpoints[-1]

    resumed = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    await collect(resumed, parked)

    seeded = harness([[ModelCompleted("end_turn", ModelUsage(1, 1))]])
    await collect(seeded, checkpoint_for(seeded.restore(parked)))

    assert [c.loop_state for c in seeded.repository.checkpoints] == [
        c.loop_state for c in resumed.repository.checkpoints
    ]
    offered = {tool.name for tool in resumed.model.requests[0].tools}
    listed = {tool.name for tool in resumed.catalog().definitions(resumed.restore(parked))}
    assert offered == listed
```
`ModelRequest` 의 도구 목록 필드 이름(`tools` 인지)을 `neos/coding/model/base.py` 에서 확인하고 맞춘다. 첫 단언이 같지 않으면 **멈추고 보고한다** — 단 차이가 "복원을 두 번 적용"(재개 런은 `parked` 를 복원하고, 시드 런은 이미 복원한 상태를 다시 인코딩해 복원한다 — 작업 공간 편집 안내나 대기 명령이 두 번 붙을 수 있다)에서 오는지 먼저 본다; `parked` 에 대기 명령·작업 공간 편집이 없으면 같아야 한다.
테스트 치환: `<x>.loop._restore(A, B)` → `<x>.restore(B, input=A)` (`A` 가 `INPUT` 이면 `input=` 생략). `<x>` 가 하네스가 아니라 직접 지은 루프면 `restore_state(A, B, catalog=ToolCatalog(...), compactor=Compactor(...))` 로 그 루프와 같은 인자로.

- [ ] **Step 5: 확인·커밋**

```bash
grep -rnoE '\bloop\._restore\(' tests | wc -l                         # 0
grep -rhE '^class \w+Mixin' neos/coding/loop/_durable | wc -l         # 6
uv run pytest tests/coding tests/standing -q -p no:randomly
uv run ruff check neos/coding tests/coding tests/standing
git add -A neos/coding/loop tests/coding tests/standing
git commit -m "refactor(coding): restore_state completes the public checkpoint seam; the loop delegates and _dump_state goes"
```

---

### Task 5: 최종 검증 (controller)

- [ ] 이름 대조(사라진 이름 0; 새 이름은 `test_usage_functions.py`, `test_compactor.py`, `test_checkpoint_seam.py::test_the_harness_components_match_the_loop_run` 뿐), 이름별 결과 대조(통과→실패 0, 알려진 흔들림 규칙).
- [ ] 지표: compaction 0, catalog 0, usage 0, aliases 0, restore_cp 0, mixins 6, dump_state_src 0. 생성 뒤 재할당 재확인: `grep -rnE "\b(loop|self)\._(config|hooks|model|tools)\s*=[^=]" neos/coding/loop` 가 `durable.py` 의 `__init__` 외 0줄.
- [ ] CI Ruff 명령 그대로. spec 상태 줄 `구현 완료(2026-10-09)` 는 최종 수정 묶음에서.

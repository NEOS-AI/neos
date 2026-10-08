# 코딩 루프 믹스인을 컴포넌트로 — 도구 카탈로그·컴팩션·사용량·체크포인트 복원 (C)

- 날짜: 2026-10-08
- 상태: 구현 완료(2026-10-09)
- 범위: 테스트 구조 의존 줄이기 묶음의 세 번째(C). A(체크포인트 이음매, 555eb444)가 넘긴 것을 이어 받는다. B 는 별도 spec.
- 깊이: "개념 추출"(사용자 선택). spawn·도구 실행·모델 턴 믹스인은 이번 범위 밖이다.

## 1. 배경

`DurableCodingLoop`(`neos/coding/loop/durable.py`)은 믹스인 8개(`_durable/*.py`, ~3,970줄)로 조립되고, 모두 같은 `self` 를 공유한다 —
파일은 나뉘었지만 어느 믹스인이든 어느 필드든 읽을 수 있다. A 이후 테스트가 루프의 private 멤버를 부르는 곳 중 이번 대상:

| 개념 | 출처 | 테스트가 부르는 것 | 횟수 |
|---|---|---|---|
| 도구 카탈로그 | `ToolCatalogMixin`(174줄) | `_tool_definitions` | 8 |
| 컴팩션 | `CompactionMixin`(353줄) | `_compact_after_prompt_too_long` 12 · `_compact` 5 · `_over_budget` 2 · `_digest` 2 · `_maybe_llm_compact` · `_compact_with_hook` · `_compaction_request` · `_estimated_tokens` | 25 |
| 사용량·창 | `durable.py` 메서드 4개(`usage.py` 함수의 얇은 포장) | `_check_usage_budgets` 3 · `_parent_headroom_chars` 3 · `_price_tokens` · `_transcript_token_limit` | 8 |
| 체크포인트로부터의 복원 | `CheckpointMixin._restore`(체크포인트 분기) | `_restore(INPUT, checkpoint)` | 25 |

의존성은 좁다: 카탈로그는 `_tools`·`_config`, 컴팩션은 `_config`·`_hooks`·`_model` 과 카탈로그의 "드러난 도구", 사용량은 `_config` 뿐,
복원은 카탈로그와 컴팩션(`/compact` 명령)이다. 루프 내부 호출부도 메서드당 1~4곳이다. 예외는 `_digest`(11곳)로, 지금 `CompactionMixin` 의 `staticmethod(_transcript_digest)` 다 — 믹스인이 사라지므로 11곳을 모듈 함수 `_transcript_digest(...)` 호출로 바꾼다(`_estimated_tokens` 도 같다).
프로덕션은 생성 뒤 루프의 `_config`·`_hooks`·`_model`·`_tools` 를 바꾸지 않는다(2026-10-08 grep), A 이후 테스트도 바꾸지 않는다 —
그래서 컴포넌트가 생성 때 값을 붙잡아도 안전하다.

A 최종 리뷰가 넘긴 두 Minor 도 여기서 닫는다: (3) 공개 `neos/coding/loop/checkpoint.py` 가 내부 믹스인이 쓰는 private 헬퍼를 품는 역방향 의존,
(4) `self._dump_state` 7곳 → `encode_state` 직접 호출로 메서드 삭제.

## 2. 목표와 비목표

**목표**
- 네 개념을 루프 밖의 컴포넌트·함수로 꺼내 공개한다. 테스트는 그것을 **독립적으로 생성**해 공개 메서드만 부른다.
- A 에서 시작한 체크포인트 이음매의 **디코드 쪽**(`restore_state`)을 공개해 이음매를 완성한다.
- 믹스인 8 → 6.

**비목표**
- 행동 변경 없음. 체크포인트 형식·모델 요청·이벤트는 그대로다.
- spawn(`SubagentSpawnMixin`·`SpawnClaimsMixin`), 도구 실행(`ToolExecutionMixin`), 모델 턴(`ModelTurnMixin`), 전이(`TurnTransitionsMixin`)는 건드리지 않는다.
  남는 테스트 접근(`_after_result`, `_guard_thinking_prefix`, `_advance_detached_children` 스파이 3곳, `_price_child_usage` …)은 다음 차례다.
- 파일 위치는 `_durable/` 그대로 둔다(옮김 최소화). 공개는 `neos.coding.loop` 재수출로 한다.
- 루프에 컴포넌트를 내놓는 공개 속성은 두지 않는다(루프의 공개 인터페이스는 `run()` 그대로).

## 3. 설계

### 3.1 `ToolCatalog` — `_durable/tool_catalog.py`

```python
class ToolCatalog:
    def __init__(self, tools: CodingToolRegistry, config: CodingLoopConfig) -> None: ...
    def definitions(self, state: AgentLoopState): ...            # 지금의 _tool_definitions
    def revealed_from(self, transcript) -> frozenset[str]: ...    # 지금의 _revealed_from_transcript
    def allowed_by_skills(self, ...) -> bool: ...                 # 지금의 _tool_allowed_by_skills (내부 호출 4곳)
    def announce_reveals(self, ...): ...                          # 지금의 _announce_reveals
```
`ToolCatalogMixin` 은 사라진다. 루프는 `self._catalog = ToolCatalog(tools, config)` 를 짓고 내부 호출부는 `self._catalog.x(...)` 로 바뀐다.
`_registry_tool_names`·`_union_skill_allowed_tools` 는 클래스의 private 메서드로 따라간다.

### 3.2 `Compactor` — `_durable/compaction.py`

```python
class Compactor:
    def __init__(self, *, config, hooks=None, model, catalog: ToolCatalog) -> None: ...   # hooks=None → NullCodingHooks()
    async def after_prompt_too_long(self, state: AgentLoopState) -> AgentLoopState: ...   # 지금의 _compact_after_prompt_too_long
    def compact(self, transcript, *, force: bool = False, bodies=None): ...              # 지금의 _compact
    def over_budget(self, transcript) -> bool: ...
    def require_fit(self, transcript) -> None: ...
    async def compact_with_hook(self, ...): ...
```
LLM 요약 컴팩션(`_maybe_llm_compact`, `_compaction_request`)과 머리 버리기·최근 읽기 미리보기는 클래스의 private 메서드로 따라간다.
`_transcript_token_limit` 은 §3.3 의 함수를 부른다. 루프는 `self._compactor = Compactor(config=…, hooks=…, model=…, catalog=self._catalog)`.

### 3.3 사용량·창 함수 — `_durable/usage.py`

```python
def price_tokens(config, input_tokens, output_tokens, *, cache_read_tokens=0, cache_write_tokens=0) -> int   # 이미 있다
def check_usage_budgets(config, state) -> None                                                            # 이미 있다
def transcript_token_limit(config) -> int            # durable.py 의 _transcript_token_limit 를 옮긴다
def parent_headroom_chars(config, state) -> int      # durable.py 의 _parent_headroom_chars 를 옮긴다
```
루프의 `_price_tokens`·`_check_usage_budgets`·`_transcript_token_limit`·`_parent_headroom_chars` 메서드는 지우고 호출부가 함수에
`self._config` 를 넘긴다.

### 3.4 `restore_state` — 공개 `neos/coding/loop/checkpoint.py`

```python
def restore_state(
    input: LoopInput, checkpoint: CodingCheckpoint, *, catalog: ToolCatalog, compactor: Compactor
) -> AgentLoopState:
    """저장된 체크포인트에서 이 단계의 상태를 만든다: 작업 공간 편집을 덧붙이고, 열린 도구 호출이 없으면 대기 중인
    명령(/compact, /clear, /cost …)을 적용한다. 지금의 `_restore(input, checkpoint)` 와 같다."""
```
- `CheckpointMixin._restore` 는 `initial_state(input) if checkpoint is None else restore_state(input, checkpoint, catalog=self._catalog, compactor=self._compactor)`.
- 대기 명령 처리기(`_compact_command`·`_clear_command`·`_cost_command`·`_PENDING_COMMANDS`·`_note`·`_cleared_transcript`)는 `checkpoint.py` 로 옮긴다.
  `/compact` 는 `compactor.compact(...)` 를 부른다. 그러면 `_task_seed_text`·`_with_workspace_edits`·`_CLEARED_NOTICE` 를 쓰는 곳이 모두
  `checkpoint.py` 안에 있게 되어 **A 의 Minor 3(역방향 의존)이 사라진다** — `_durable/checkpoint.py` 는 그것들을 더 import 하지 않는다.
- `CheckpointMixin` 에는 중단·인터럽트 부분(`_has_pending_interrupt`, `_persist_abort_after_cancel`, `_checkpoint_aborted`)만 남는다 — 단계 진행이라 범위 밖이다.
- **A 의 Minor 4:** 루프의 `self._dump_state(...)` 7곳을 `encode_state(...)` 로 바꾸고 `_dump_state` 를 지운다.
- `neos/coding/loop/__init__.py` 는 `ToolCatalog`, `Compactor`, `restore_state`, 그리고 §3.3 의 네 함수를 재수출한다.

### 3.5 테스트 지원 — `tests/coding/loop/support.py`

```python
class Harness:
    def catalog(self) -> ToolCatalog: ...                 # ToolCatalog(self.loop_kwargs["tools"], self.config)
    def compactor(self) -> Compactor: ...                 # Compactor(config=…, hooks=self.loop_kwargs["hooks"], model=…, catalog=self.catalog())
    def restore(self, checkpoint, *, input=INPUT) -> AgentLoopState: ...  # restore_state(input, checkpoint, catalog=…, compactor=…)
```
루프가 컴포넌트를 짓는 방식과 하네스가 짓는 방식이 갈라지면 안 된다 — 둘 다 **같은 생성자와 같은 기본값**(기본값은 컴포넌트 안에 산다, 예: `hooks=None → NullCodingHooks()`)을 쓰고,
§4.3 의 고정 테스트가 그것을 지킨다.

### 3.5b 계획 때 더한 판정(2026-10-09)

- **공개 이름은 옛 이름에서 밑줄만 뗀다**(`_compact_after_prompt_too_long` → `compact_after_prompt_too_long`, `_tool_definitions` → `definitions` 만 예외 —
  카탈로그 안에서 `tool_` 은 중복이다). §3.1·§3.2 의 예시 이름(`after_prompt_too_long` 등)보다 이것이 우선한다 — 이름 바꾸기를 최소로 해서
  옮김을 기계적으로 대조할 수 있게 한다. `Compactor` 의 공개 메서드: `compact_after_prompt_too_long`, `head_drop_after_prompt_too_long`
  (모델 턴이 부른다), `compact_with_hook`(전이가 부른다), `compact`, `over_budget`, `require_transcript_fit`, `maybe_llm_compact`,
  `compaction_request`(테스트가 요청 모양을 시험한다 — 요약 컴팩션이 모델에 무엇을 보내는지는 독립된 개념이다).
- **`CompactionMixin` 의 staticmethod 별칭**(`_shrink_old_tool_results`, `_expand_artifact_refs`, `_maybe_ref_latest_tool_result`,
  `_compact_ref_path`, `_drop_oldest_prefix_turn`, `_serialized_bytes`, `_estimated_tokens`, `_digest`)은 믹스인과 함께 사라진다.
  루프 안의 `self.` 호출(`_digest` 5곳, `_maybe_ref_latest_tool_result` 1곳)은 모듈 함수 호출로, 테스트의 `loop.` 호출
  (`_shrink_old_tool_results` 5, `_expand_artifact_refs` 2, `_maybe_ref_latest_tool_result` 1, `_estimated_tokens` 1, `_digest` 2)은
  `neos.coding.loop` 가 재수출하는 공개 이름(`shrink_old_tool_results`, `expand_artifact_refs`, `maybe_ref_latest_tool_result`,
  `estimated_tokens`, `transcript_digest`)으로 옮긴다. 지표에 "별칭" 줄을 더한다(8 → 0, `_estimated_tokens`·`_digest` 는 컴팩션 줄에 이미 있다).

### 3.6 이주 규칙

| 지금 | 바꾼 뒤 |
|---|---|
| `h.loop._tool_definitions(state)` | `h.catalog().definitions(state)` |
| `await h.loop._compact_after_prompt_too_long(state)` | `await h.compactor().after_prompt_too_long(state)` |
| `h.loop._compact(t, force=True, bodies=b)` 등 컴팩션 private | `h.compactor().compact(...)` 등 공개 메서드 |
| `h.loop._digest(t)` / `h.loop._estimated_tokens(t)` | 공개 모듈 함수(`transcript_digest`, `estimated_tokens` 로 재수출) |
| `h.loop._check_usage_budgets(state)` 등 | `check_usage_budgets(h.config, state)` 등 |
| `h.loop._restore(INPUT, checkpoint)` | `h.restore(checkpoint)` (입력이 다르면 `input=`) |
| `from neos.coding.loop._durable.compaction import extract_preserved_summary` 등 이번 대상 모듈의 private 경로 import | 재수출된 `neos.coding.loop` 에서 |

단언 규칙은 B spec 과 같다: 기댓값·의미는 그대로, 대상 식은 같은 값을 돌려주는 공개 인터페이스로 옮길 수 있고 하나하나 보고한다.

## 4. 검증

1. 기준선: `tests/coding tests/standing` 이름(A 종료 시 3401 수집)·이름별 결과를 저장하고 작업 뒤 이름으로 대조한다(A 와 같은 절차).
2. 지표:

| 지표 | 명령 | 기준선 | 목표 |
|---|---|---|---|
| 컴팩션 private | `grep -rnoE '\bloop\.(_compact_after_prompt_too_long\|_compact\|_maybe_llm_compact\|_compact_with_hook\|_over_budget\|_compaction_request\|_estimated_tokens\|_digest)\b' tests \| wc -l` | 25 | 0 |
| 카탈로그 private | `grep -rnoE '\bloop\._tool_definitions\b' tests \| wc -l` | 8 | 0 |
| 사용량 private | `grep -rnoE '\bloop\.(_check_usage_budgets\|_price_tokens\|_transcript_token_limit\|_parent_headroom_chars)\b' tests \| wc -l` | 8 | 0 |
| 별칭 private | `grep -rnoE '\bloop\.(_shrink_old_tool_results\|_expand_artifact_refs\|_maybe_ref_latest_tool_result)\b' tests \| wc -l` | 8 | 0 |
| 체크포인트 복원 private | `grep -rnoE '\bloop\._restore\(' tests \| wc -l` | 25 | 0 |
| 믹스인 수 | `grep -rhE '^class \w+Mixin' neos/coding/loop/_durable \| wc -l` | 8 | 6 |
| `self._dump_state` | `grep -rnoE 'self\._dump_state\(' neos \| wc -l` | 7 | 0 |

3. **루프-하네스 동등성 고정:** 같은 입력으로 (가) 루프 `run()` 이 체크포인트에서 재개해 커밋한 상태와 (나) `h.restore(checkpoint)` 가
   돌려준 상태로 시작한 같은 단계가 같은 요청·같은 `loop_state` 를 남기는지, 그리고 `h.catalog().definitions(state)` 가 그 단계의
   모델 요청에 실린 도구 목록과 같은지를 런 수준에서 확인한다.
4. **옮김의 동등성:** 각 컴포넌트는 옮기기 전 믹스인 메서드와 같은 입력에서 같은 출력을 내는지 과도기 대조 테스트로 확인하고(A Task 1 방식), 위임 뒤 지운다.
5. CI 의 Ruff 명령을 그대로 돌린다.

## 5. 위험과 대응

- **컴포넌트가 생성 때 붙잡은 값과 루프가 읽는 값이 갈라진다.** 위 §1 의 확인(생성 뒤 재할당 없음)이 전제다. 작업 뒤 같은 grep 을 다시 돌려
  새 재할당이 생기지 않았는지 본다.
- **`ModelTurnMixin`·`ToolExecutionMixin`·`SubagentSpawnMixin` 이 옮긴 메서드를 `self.` 로 부른다.** 옮기기 전 이름으로 모든 호출부를 세고
  (§1 표의 src 열), 옮긴 뒤 같은 이름이 `self.` 로 남지 않았는지 grep 한다.
- **`hooks` 기본값.** 루프는 `hooks or NullCodingHooks()` 를 쓴다. 컴포넌트가 같은 기본값을 스스로 갖지 않으면 하네스가 만든 컴팩터가
  `None` 훅을 부른다 — 기본값을 컴포넌트에 둔다.
- **A 브랜치를 쓰는 옛 피처 브랜치.** `_restore`·`_tool_definitions` 를 쓰는 테스트가 그 브랜치에도 있으면 머지 때 같은 규칙으로 바꿔야 한다(메모에 적는다).

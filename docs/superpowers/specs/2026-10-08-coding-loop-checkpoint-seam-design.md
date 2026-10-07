# 코딩 루프 체크포인트 이음매 — 테스트의 구조 의존 줄이기 (A)

- 날짜: 2026-10-08
- 상태: 설계 승인 대기
- 범위: 리팩터링 묶음의 첫 번째(A). B(Orchestrator 단계 분리)·C(루프 믹스인 → 합성)·D(하네스 worker·API 라우트)는 각자 별도 spec 으로 간다.

## 1. 배경

`DurableCodingLoop`(`neos/coding/loop/durable.py`)는 공개 진입점이 `run(input, checkpoint, deps)` 하나뿐인 깊은 모듈의
모양을 이미 갖고 있고, 협력자·설정 19개를 전부 생성자 키워드로 받는다. 그런데 `tests/coding` 은 루프의 private 멤버를 **279번**
직접 만진다(27개 파일). 그래서 루프 내부의 이름을 하나 바꾸면 수십 개 테스트가 깨진다.

279번을 원인별로 나누면 다음과 같다.

| 종류 | 대표 | 원인 |
|---|---|---|
| ① 의존성 재할당 | `h.loop._clock = clock`(20), `_config = replace(...)`, `_user_rules`, `_metrics`, `_tools`, `_secrets`, `_device_bridge`, `_asks`, `_model`, `_subagents` | 생성자는 이미 받는데 공용 `harness()` 가 넘겨주지 않는다 — **테스트 쪽 원인** |
| ② 체크포인트 상태 만들기 | `h.loop._restore(INPUT, None)` → `replace(...)` → `h.loop._dump_state(INPUT, state)` | "상태 X 에서 루프를 시작"할 공개 경로가 없다 |
| ③ 행동 메서드 직접 호출 | `_compact_after_prompt_too_long`, `_guard_thinking_prefix`, `_shrink_old_tool_results`, 체크포인트로부터의 `_restore` … | 믹스인 구조 자체 — **C 로 미룬다** |

덧붙여, 36개 파일이 **다른 테스트 모듈**(`tests/coding/loop/test_anthropic_loop.py`)에서 `harness`·`INPUT`·`collect`
등을 import 하고, 파일마다 비슷한 `_loop()` 팩토리와 `_checkpoint()` 헬퍼가 따로 있다. 이것도 테스트끼리의 구조 의존이다.

## 2. 목표와 비목표

**목표**
- ①·② 를 0 으로 만든다. 테스트는 루프를 생성자와 `run()` 으로만 다루고, 상태는 공개된 체크포인트 이음매로 만든다.
- 공용 테스트 지원을 테스트 모듈이 아닌 지원 모듈로 옮긴다.

**비목표 (이번에 하지 않는다)**
- 행동 변경 없음. 순수 리팩터링이다.
- 체크포인트 형식(`loop_state` 매핑)은 바이트 수준까지 그대로다 — 저장된 체크포인트가 그대로 재개되어야 한다.
- ③ 은 건드리지 않는다. 특히 **체크포인트로부터의 `_restore(INPUT, checkpoint)` 25곳은 남긴다.** 이 경로는 도구 레지스트리
  (`_revealed_from_transcript`)와 `/compact` 처리(`loop._compact`)에 기대므로 순수 함수로 뺄 수 없고, 믹스인을 풀 때(C)
  같이 다룬다.
- 믹스인 구조, `_durable/` 내부 모듈 배치는 그대로 둔다.

## 3. 설계

### 3.1 공개 체크포인트 이음매 — `neos/coding/loop/checkpoint.py` (신규)

```python
def initial_state(input: LoopInput) -> AgentLoopState:
    """체크포인트 없이 시작하는 런의 첫 상태. 지금의 `_restore(input, None)` 과 같다."""

def encode_state(input: LoopInput, state: AgentLoopState) -> dict[str, Any]:
    """`state` 를 저장할 `loop_state` 매핑으로. 지금의 `_dump_state(input, state)` 와 같다."""
```

- 두 함수 모두 루프 인스턴스가 필요 없다. 현재 구현이 쓰는 것은 `_with_workspace_edits`(static),
  `_digest`(= `staticmethod(_transcript_digest)`), `_task_seed_text`·`_is_task_seed`(static),
  `_sync_active_children`·`_dump_loop_state`(모듈 함수)뿐이다.
- 이 static 헬퍼들은 `checkpoint.py` 의 모듈 함수로 옮기고, `CheckpointMixin` 은 그것을 부른다.
  이 헬퍼들의 호출부는 지금 `_durable/checkpoint.py` 안에만 있다(2026-10-08 grep 확인) — 옮긴 뒤 그 안의
  `CheckpointMixin.`/`self.` 접두 호출을 모듈 함수 호출로 바꾼다.
- 루프의 `_restore(input, None)` 분기와 `_dump_state` 는 이 두 함수로 **위임만** 한다. 프로덕션이 테스트와 같은 코드를
  지나므로 이음매가 실제 경로에서 벗어날 수 없다.
- `neos/coding/loop/__init__.py` 의 `__all__` 에 `AgentLoopState`, `initial_state`, `encode_state` 를 더한다.
  `AgentLoopState` 의 정의 위치(`_durable/state.py`)는 그대로 두고 재수출만 한다.

이 함수가 공개 계약이 되는 근거: `loop_state` 는 이미 DB 에 저장되어 배포를 넘어 재개되는 영속 형식이다. 테스트가 루프의
내부가 아니라 이 형식에 기대게 하는 것이 목표다.

### 3.2 테스트 지원 모듈 — `tests/coding/loop/support.py` (신규)

`test_anthropic_loop.py` 에서 `Harness`, `harness()`, `Model`, `Executor`, `Bindings`, `Events`, `tool_call`, `completed`,
`collect`, `LEASE`, `INPUT`, `NOW` 등 공용 부품을 옮긴다(`test_anthropic_loop.py` 는 테스트만 남는다).

- `harness()` 는 루프 생성자 인자를 전부 키워드로 받아 그대로 넘긴다: 지금 받는 것에 더해 `clock`, `metrics`, `tools`,
  `model`(턴 대신 모델 객체를 줄 때), `user_rules`, `secrets`, `browser`, `device_bridge`, `asks`, `jev`.
  기본값은 지금과 같다(`clock=lambda: NOW` 등). `Harness` 는 루프에 넘긴 키워드 전부를 들고 있고(`h.config` 등),
  테스트는 루프의 private 필드 대신 이것을 읽는다.
- `Harness.resumed(**overrides) -> Harness`: 같은 repository·events·executor·bindings·subagents 를 공유하는
  **새 루프 인스턴스**를 만든다. "설정이 바뀐 새 배포가 저장된 체크포인트를 재개한다"를 그대로 재현하므로,
  런 사이에 `h.loop._config = replace(...)` 하던 곳을 대신한다.
- `checkpoint_for(state, *, input=INPUT, checkpoint_id="cc_test", seq=1) -> CodingCheckpoint`:
  `encode_state` 로 `CodingCheckpoint` 를 만든다. 파일마다 있던 `_checkpoint()` 헬퍼(3개)를 대신한다.
- `support.py` 는 `test_` 로 시작하지 않으므로 수집되지 않는다. 다른 디렉터리(`tests/coding/connectors/`,
  `tests/coding/model/`)도 이것을 import 한다.

### 3.3 이주 규칙

| 지금 | 바꾼 뒤 |
|---|---|
| `h = harness(...); h.loop._clock = clock` | `h = harness(..., clock=clock)` |
| `h.loop._user_rules = rules` 등 생성 직후 재할당 | `harness(..., user_rules=rules)` |
| 런 사이 `h.loop._config = replace(h.loop._config, ...)` | `h = h.resumed(config=replace(h.config, ...))` |
| `h.loop._restore(INPUT, None)` | `initial_state(INPUT)` |
| `h.loop._dump_state(INPUT, state)` | `encode_state(INPUT, state)` |
| 파일별 `_checkpoint(h, state)` | `checkpoint_for(state)` |
| `from tests.coding.loop.test_anthropic_loop import ...` | `from tests.coding.loop.support import ...` |

각자의 `_loop()` 팩토리(`test_mcp_gate`, `test_mcp_pinned`, `test_user_rules_loop`, `test_secret_broker_loop`,
`test_device_bridge_*`, `test_agent_browser_loop`)는 생성자 인자로 넘기도록만 고친다. 하나로 합치는 것은 하지 않는다 —
각 파일의 기본값이 다르고, 합치는 것은 이 목표에 필요하지 않다.

테스트의 **단언(assert)은 바꾸지 않는다.** 바뀌는 것은 준비(arrange) 단계뿐이다. 단언까지 바뀌어야 하는 곳이 나오면
멈추고 따로 보고한다.

## 4. 검증

1. **기준선(작업 전):** `tests/coding` 의 테스트 이름 목록을 `pytest --collect-only -qq` 로 뽑아 저장하고, 전체 실행 결과
   (통과/실패 이름)를 저장한다. 원래 흔들리는 테스트(메모: managed secret 잘린 꼬리)는 기준선에서 표시해 둔다.
2. **작업 후:** 같은 두 목록을 다시 뽑아 **이름으로** 대조한다. 사라진 이름 0, 통과 → 실패로 바뀐 이름 0.
   (`test_anthropic_loop.py` 에서 옮긴 것은 헬퍼뿐이라 테스트 이름은 바뀌지 않아야 한다.)
3. **지표:** 아래 명령의 값이 기준선 → 목표가 된다.

| 지표 | 명령 | 기준선 | 목표 |
|---|---|---|---|
| 의존성 재할당 | `grep -rnE '\bloop\._[a-z_]+\s*=[^=]' tests/coding \| wc -l` | 70 | 0 |
| `_restore(…, None)` | `grep -rnE '\._restore\([^,]+,\s*None' tests/coding \| wc -l` | 40 | 0 |
| `_dump_state` | `grep -rnE '\._dump_state\(' tests/coding \| wc -l` | 22 | 0 |
| 테스트 모듈에서의 import | `grep -rlE 'from tests\.coding\.loop\.test_anthropic_loop import' tests \| wc -l` | 36 | 0 |
| 체크포인트로부터의 `_restore` | `grep -rnE '\._restore\(' tests/coding \| grep -v ', None' \| wc -l` | 25 | 25 (C 에서) |

4. **이음매의 동등성:** `initial_state`/`encode_state` 를 직접 겨누는 테스트를 하나 더한다 — 지금 루프가 커밋하는 첫
   체크포인트의 `loop_state` 와 `encode_state(INPUT, initial_state(INPUT))` 가 같은지(작업 공간 편집이 있는 입력 포함).
5. CI 의 Ruff 명령을 로컬에서 그대로 돌린다(메모: 미사용 import).

## 5. 위험과 대응

- **헬퍼를 옮기며 사본이 남는다.** `_task_seed_text` 등을 모듈 함수로 옮긴 뒤 `CheckpointMixin.` 접두로 부르는 곳이
  남지 않았는지 이름으로 grep 한다.
- **`resumed()` 가 공유해야 할 것을 빠뜨린다.** 재개 테스트가 같은 repository 의 체크포인트를 읽는지가 단언으로 이미
  확인되므로, 빠뜨리면 기존 단언이 실패한다.
- **병렬 작업과의 충돌.** `tests/coding/loop/` 를 고치는 다른 브랜치가 있으면 import 경로 변경이 충돌한다.
  작업은 dev 기준의 별도 브랜치에서 하고, 머지 직전에 dev 를 다시 받아 기준선 대조를 반복한다.

# 설계자 배선 (트랙 G의 G2) — 설계

**작성일:** 2026-08-23
**트랙:** G — 워크플로우 그래프 계약·검증 (`docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §14.3)
**범위:** G2-a·G2-b·G2-c·G2-d·G2-e **다섯 전부**
**선행 조건:** 없음. `8a1cdd47`이 배선의 선행 조건 셋(C1 `GRAPH_ENTRY_WRITES` ·
I1 `mandatory` 기본값 · I3 `checkpointer`/`interrupt_before` 수용)을 이미 넣었다.

> 📌 **트랙 A의 라이브 표본과 병행 가능하다.** 심층분석 표본은 job 서비스에서 돌고
> `graph.py`의 챗 노드는 job을 제출만 한다(`graph.py:1051-1122`, §10.5). 이 설계가
> 바꾸는 것은 챗 경로의 그래프 결정과 진행 추적이며 deep_analysis의 LLM 호출 경로·
> 프롬프트·모델·토큰 한도를 건드리지 않는다 — §10.2의 "측정 중 변경 금지"에 걸리지 않는다.

> ⚠️ **트랙 F와 혼동하지 말 것.** §14 서두가 못 박은 그대로다. F는 *심층분석 표본의
> 개선-측정-판정 루프*를 서브에이전트로 나눈 것이고(닫혔다, D83), G는 *`graph.py`의
> 노드 배선*을 데이터로 만들고 검증하는 것이다. 이 문서는 후자다.

---

## 1. 목적과 관문

**목적:** `design_graph_or_fallback`에 **프로덕션 호출자를 준다.**

**지금 무엇이 문제인가 — 플래그의 존재와 부재가 구별되지 않는다.**

`workflow.graph_design_enabled`(`neos/config/schema.py:245`)를 켜도 아무것도 바뀌지
않는다. `design_graph_or_fallback`의 호출자는 `tests/workflow/test_graph_design_ledger.py`
**뿐이고**(실측 2026-08-23), `build_ephemeral_workflow`의 호출자도
`tests/workflow/test_ephemeral_graph_execution.py` 뿐이다. 설계·검증·원장·조립이
전부 지어져 있는데 그 사슬에 진입점이 없다.

**관문:**

| # | 조건 | 측정 |
|---|---|---|
| G2-1 | 플래그가 꺼져 있으면 지금과 **바이트 단위로 같은** 정적 그래프가 돈다 | `test_the_compiled_static_graph_matches_its_pre_task_9_snapshot` 해시 불변 |
| G2-2 | 플래그를 켜고 설계가 승인되면 **그 토폴로지가 실제로 실행된다** | ephemeral 그래프의 노드 집합 = 승인된 토폴로지의 노드 집합 |
| G2-3 | 설계 실패 네 갈래가 전부 **정적 폴백 + 사유 기록**으로 끝난다 | 타임아웃·예외·위반·게이트 거부 각각에 대해 로그/span에 사유가 남는다 |
| G2-4 | 진행 이벤트가 **이번 실행의 그래프**를 서술한다 | 설계된 그래프의 노드에 대해 `on_node_start`가 나가고 ETA가 0이 아니다 |
| G2-5 | 동시 요청 둘이 서로의 그래프를 보지 않는다 | 인스턴스 속성 슬롯 0개 (기존 가드 유지) |

**G2-b가 왜 이 묶음에서 빠질 수 없는가.** §15.3이 트랙 H의 H3 관문으로 G2-b를
지목한 이유가 그것이다 — 진행 추적이 정적 노드 목록을 가정하므로 설계된 그래프는
진행 이벤트를 조용히 흘리고, 사용자에게는 멈춘 것처럼 보인다. **S6("실패가 사용자
에게도 보인다")의 회귀**를 우리 손으로 만드는 셈이다.

---

## 2. 이 설계가 방어하는 것 — 실측으로 드러난 결함들

### 2.1 하드코딩된 노드 순서 목록이 하나가 아니라 둘이다

§14.3은 G2-b를 "astream 진행 추적 재작업 — 정적 노드 목록을 가정"으로 한 줄 적었다.
코드를 읽으니 **목록이 둘이고 서로 다르다.**

| 위치 | 이름 | 내용 | 용도 |
|---|---|---|---|
| `neos/workflow/graph.py:2518-2535` | `workflow_nodes` | 손으로 나열한 19개 | 진행 단계 카운트 |
| `neos/workflow/events.py:66` | `WORKFLOW_NODE_ORDER` | `_STATIC_DURATIONS.keys()` | ETA 계산 |

둘 다 "목록의 순서 = 실행 순서"를 가정한다. 그 가정이 세 곳에서 관측 가능한
거짓말을 만든다:

1. **`total_steps = len(workflow_nodes)` = 항상 19.** 조건부 분기로 절반을
   건너뛰어도 사용자는 "19단계 중 n번째"를 본다.
2. **`prev_idx = workflow_nodes.index(node_name) - 1`**(`graph.py:2562`). 실제
   실행 순서가 아니라 **목록 순서상 이전 항목**의 `record_node_end`를 부른다.
   건너뛴 노드의 종료 시각이 기록되고 그것이 ETA 히스토리에 들어간다. 같은 결함이
   `graph.py:2594`의 `workflow_nodes[-1]`(목록의 마지막 ≠ 실제 마지막)에도 있다.
3. **`estimate_remaining_time`**(`events.py:136-146`)은 `WORKFLOW_NODE_ORDER.index()`
   이후 **모든** 노드의 예상 시간을 더하고, 목록에 없는 노드에는 `ValueError`를 잡아
   **0.0**을 돌려준다. 설계된 그래프의 노드는 이 목록에 없으므로 사용자는 매 단계
   **"남은 시간 0초"**를 보게 된다 — "곧 끝남"으로 읽히고 실제로는 계속 돈다.

**세 번째가 이 설계에서 가장 중요하다.** 진행 이벤트가 아예 안 나가는 것보다
나쁘다. 안 나가면 사용자는 모르지만, 0초가 나가면 **틀린 것을 안다고 믿는다.**

### 2.2 원장 이벤트 4종에 목적지가 없다

`design_graph_or_fallback`은 `DesignOutcome.events`에 이벤트 4종
(`graph_design_requested`/`accepted`/`rejected`/`fallback`)을 실어 **반환한다.**
그리고 지금은 그것을 받는 프로덕션 코드가 없으므로 **아무 데도 기록되지 않는다.**

그 모듈의 docstring(`graph_design_ledger.py:12-18`)이 존재 이유를 이렇게 적었다:
"**이벤트를 하나도 남기지 않는 폴백은 성공과 구별되지 않는다.**" 호출부를 붙인다는
것은 그 문장을 실현할 목적지를 정한다는 뜻이다.

**deep_analysis의 run 원장은 쓸 수 없다.** 같은 파일 81-84줄이 이미 닫아 놓았다 —
"그쪽은 run 하나의 생애주기에 묶여 있는데, 이 경로는 아직 run이 시작되기 전
(그래프를 빌드하는 시점)이라 묶일 run 자체가 없다."

### 2.3 인스턴스 슬롯 금지는 이미 코드에 적혀 있다

`graph.py:376-383`이 다음 사람에게 남긴 요구사항이다:

> 의도적으로 "설계된 토폴로지"를 담는 인스턴스 속성을 두지 않는다. `MultiAgentWorkflow`는
> 오래 살아남고 요청들이 공유하는 객체다 (…) 다음 태스크가 실제 배선을 만들 때는 이
> 값을 인스턴스 상태가 아니라 **호출 스코프**로만 들고 다녀야 한다.

위험은 실재한다 — `multi_agent_workflow = MultiAgentWorkflow()`가 모듈 레벨 싱글턴이다
(`graph.py:3398`). `test_the_static_path_does_not_carry_a_shared_designed_topology_slot`이
이 요구를 테스트로 고정하고 있다.

---

## 3. 구성 요소

### 3.1 `ExecutionGraph` — 호출 스코프의 값 객체 (G2-c)

```python
@dataclass(frozen=True, slots=True)
class ExecutionGraph:
    compiled: Any                          # astream/aget_state를 부를 대상
    nodes: tuple[str, ...]                 # 이번 실행에 존재하는 노드
    topology_hash: str                     # 설계 run과 정적 run의 조인 키
    source: Literal["static", "designed"]
```

`execute_workflow`가 캐시 미스 직후 `_resolve_execution_graph(...)`로 이 값을
**로컬 변수**로 받고, 지금 `self.graph`를 읽는 두 곳(`graph.py:2542` astream,
`graph.py:2663` aget_state)이 그 로컬을 쓴다.

| 결정 | 근거 |
|---|---|
| `self.graph`·`_graphs_by_checkpointer`는 **남긴다** | 정적 그래프의 컴파일 캐시로 계속 필요하다. 없애면 매 요청 재컴파일이다. 바뀌는 것은 "`execute_workflow`가 그것을 직접 읽는가"뿐이다 |
| 설계된 그래프는 **캐시하지 않는다** | 질의 하나에 종속된 값이다. 토폴로지 해시를 키로 캐시하면 §2.3이 경고한 경합이 캐시 층에서 재현되고, 컴파일된 그래프가 특정 인스턴스에 바인딩된 핸들러를 쥐고 있어 수명 관리가 생긴다 |
| `source`를 값에 싣는다 | 로그·span이 "이 run이 설계된 것인가"를 추측하지 않는다. 추측하면 §3.2가 이 저장소의 관통 주제로 적은 "조용한 degrade"를 관측 층에서 되풀이한다 |

**`nodes`의 출처가 둘이다.** 설계된 그래프는 승인된 `GraphTopology.nodes`,
정적 그래프는 `static_topology(flags=...)`의 노드 집합이다 — §3.5가 그 플래그를
어떻게 정하는지 적는다.

### 3.2 `_resolve_execution_graph` — 설계 호출부 (G2-a)

분기는 셋뿐이다.

```
graph_design_enabled == False           → 정적
enabled == True, 토폴로지 승인됨         → ephemeral
enabled == True, 그 외 전부              → 정적 (사유 기록)
```

**재설계 루프는 없다.** `graph_design_ledger.py:20-25`가 이미 못 박았다 — 위반
목록을 설계자에게 되돌려 다시 시도하게 하면 질의 하나가 LLM 설계를 여러 번 태워
지연이 상한 없이 늘어난다.

`design_graph_or_fallback`에 넘기는 값:

| 인자 | 값 | 근거 |
|---|---|---|
| `designer` | `LlmGraphDesigner(model, prompt_path, …)` | §3.6 |
| `request` | `DesignRequest(query, catalog=NODE_CONTRACTS의 값들, budget=graph_design_budget_hint)` | 카탈로그가 곧 선택지다. `budget`의 성질은 §3.6이 적는다 |
| `contracts` | `NODE_CONTRACTS` | 30개 전부 |
| `mandatory` | **기본값 그대로** (`response_generator`) | I1 불변식. 명시적으로 덮지 않는다 — `mandatory=()`는 "응답 없는 설계를 허용한다"는 뜻이고 챗 경로에서 그것은 언제나 오답이다 |
| `budget`·`node_costs` | **둘 다 `None` 유지** | `graph_design_ledger.py:35-44`가 이유를 적었다. 노드별 실제 비용 표가 이 트리 어디에도 없고, 지어내면 근거 없는 숫자로 설계를 거부/통과시킨다. 그리고 **`node_costs` 없이 `budget`만 넘기면 fail-closed 규칙이 모든 노드를 "비용 미선언" 위반으로 잡아 사실상 모든 설계를 거부한다** |
| `timeout_sec` | 생략 (설정값 `graph_design_timeout_sec`) | |

> ⚠️ **`request.budget`을 `budget` 인자로 흘려보내지 말 것.** 둘은 이름만 같고
> 다른 것이다 — 전자는 프롬프트에 박아 넣는 지시값이고 후자는 검증기가 강제하는
> 상한이다. 같은 파일이 이 함정을 명시적으로 적어 뒀다(41-44줄).

### 3.3 승인 게이트와 다섯 번째 실패 경로 (G2-d)

`interrupt_before`는 **토폴로지에서 계산한다**: `_INTERRUPT_GATED_NODES & set(topology.nodes)`.
하드코딩 목록을 다시 쓰지 않는 이유는 G2-b와 같다 — 이번 그래프에 실제로 있는
노드만 게이트한다.

**여기서 `design_graph_or_fallback`이 모르는 실패가 하나 생긴다.** 그 함수는 설계와
검증까지만 하고 **컴파일은 호출자가 한다.** `use_checkpointer=False`(챗 경로)인데
설계가 승인 게이트 노드를 포함하면 `build_ephemeral_workflow`가
`EphemeralApprovalGateUnsupported`를 던진다(`graph.py:221-231`).

| 처리 | 왜 |
|---|---|
| ❌ 잡지 않는다 | 요청이 죽는다. 설계 실패가 사용자 요청을 죽이는 것은 이 기능이 기본 꺼짐인 이유와 정면으로 어긋난다 |
| ❌ 조용히 잡는다 | §3.2가 관통 주제로 적은 "모든 실패가 성공처럼 보였다"의 재현 |
| ✅ **잡고 기존 kind로 기록한다** | `graph_design_fallback` + `reason="ephemeral_approval_gate_unsupported"` |

**새 kind를 만들지 않는 이유:** `reason` 필드가 이미 사유를 싣도록 설계돼 있고,
새 kind는 §3.2가 요구하는 "새 이벤트에는 FE 라벨을 같은 변경에 넣는다" 부채를
하나 더 만든다 — FE1이 이벤트 8종에서 정확히 그것을 빠뜨려 §5.2를 치렀다.

### 3.4 진행 추적을 실행에서 읽기 (G2-b)

세 가지를 바꾼다.

**(1) 노드 집합의 출처.** `workflow_nodes` 하드코딩 19개를 `execution_graph.nodes`로
대체한다. `total_steps`는 이번 그래프의 노드 수이며 **조건부 분기 때문에 상한**이라는
사실을 이름으로 드러낸다(`max_steps`). 이름이 값의 성질을 말하지 않으면 다음 사람이
그것을 정확한 총계로 읽는다.

**(2) "이전 노드" 추정 제거.** 직전 chunk에서 본 노드들을 로컬 변수로 들고 있다가
그다음 chunk가 올 때 종료를 기록한다. 마지막 노드 종료도 `workflow_nodes[-1]`이
아니라 **실제로 마지막에 본 노드**다.

**(3) ETA가 이번 그래프만 본다.** 시그니처를 바꾼다:

```python
def estimate_remaining_time(current_node: str, *, candidates: Sequence[str]) -> float
```

호출자가 이번 실행에서 **아직 보지 못한 노드 집합**을 넘기고 그 예상 시간을 합한다.
조건부 분기로 가지 않을 노드가 섞이므로 여전히 **과대추정**이지만, 지금과 달리
(a) 이 그래프에 없는 노드가 빠지고 (b) 설계된 그래프에서 `ValueError → 0.0`으로
"곧 끝남"이라 거짓말하지 않는다.

시그니처 변경은 안전하다 — 실측상 `estimate_remaining_time`의 호출자는
`graph.py:2575` 하나뿐이고 `WORKFLOW_NODE_ORDER`는 `events.py` 밖으로 나가지 않는다.
`get_duration_stats()`가 쓰는 용도(디버깅 통계)는 그대로 둔다.

### 3.5 정적 토폴로지 해시 (G2-e)

§14.3이 "지금은 조인 키만 있고 조인이 없다"고 적은 것이 이것이다 — 설계된 run은
`graph_design_accepted.topology_hash`를 갖는데 정적 run은 해시가 없어 비교할
상대가 없다.

정적 경로도 해시를 갖는다: `_topology_hash(static_topology(flags=<실행 시점 실제 플래그>))`.

| 결정 | 근거 |
|---|---|
| `_topology_hash`를 **공용으로 승격** | 설계·정적 양쪽이 같은 산식을 써야 조인이 성립한다. 산식이 둘로 갈리면 조인이 **조용히** 깨진다 — 해시는 다르기만 하면 되므로 아무도 눈치채지 못한다 |
| `flags`를 **실행 시점 값으로 명시적으로 넘긴다** | `static_topology()`의 기본값은 "플래그 전부 켬"이다. 그 기본값은 회귀 가드의 의도("배포 설정과 무관하게 항상 같은 토폴로지를 검증")에 맞춰진 것이고, G2-e의 의도는 정반대다 — **그 run이 실제로 쓴 그래프**를 식별해야 조인이 성립한다. 같은 함수를 다른 의도로 쓰는 것이므로 인자를 생략하지 않는다 |
| AST 파싱 비용은 **플래그 조합을 키로 캐시** | `static_topology`는 `inspect.getsource` + `ast.parse`를 돈다. 요청마다 하면 안 된다. 조합은 5비트라 상한 32개이고 배포 중 플래그가 바뀌지 않으므로 실질 1회다 |

**플래그 다섯은 `_FLAG_ATTR_TO_KEY`(`topology_export.py:46-52`)가 정의한다:**
`RECURSIVE_AGENT_ENABLED`→`recursive` · `HYPER_DEEP_AGENT_ENABLED`→`hyper_deep` ·
`DEEP_ANALYSIS_ENABLED`→`deep_analysis` · `EXECUTION_APPROVAL_ENABLED`→`execution_approval` ·
`A2UI_ENABLED`→`a2ui`. 실행 시점의 `settings` 값을 이 키로 옮겨 넘긴다. 알 수 없는
키가 오면 `static_topology`가 즉시 실패하므로(오타가 조용히 무시되지 않는다) 매핑을
손으로 다시 쓰지 말고 그 상수를 재사용한다.

### 3.6 설정 두 칸

```python
graph_design_model: str | None = None        # None = everyday 역할 기본값
graph_design_budget_hint: int = 1000         # 프롬프트에 박히는 참고용 상한
```

**`graph_design_model`.** `deep_analysis.models.*`·`coding_model.model`·
`recursive_agent.planner_model`이 이미 쓰는 **`None` = 역할 기본값** 계약을 그대로
따른다(§4.2 불변식). 새 규칙이 아니라 기존 계약의 소비자가 하나 느는 것이다.

모델은 **경계에서 한 번만 해석한다** — `_resolve_execution_graph` 진입 시 1회이며
설계자 인스턴스가 그 해석 결과를 쥔다. §4.2의 "경계마다 한 번만 해석 (토큰 스트림
루프 안 반복 해석 금지)"의 연장이다.

**`graph_design_budget_hint` — 이름에 성질을 담는다.** `DesignRequest.budget`은
프롬프트의 `{budget}`에 치환되는 **지시값일 뿐**이고 검증기가 강제하지 않는다.
프롬프트 자신이 그렇게 자백한다(`prompts/graph_design.md:31-34`): "이 예산 제약은
현재 노드별 비용 표가 없어 검증기가 자동으로 강제하지 않는다 — 비용 표가 추가되기
전까지는 참고용 상한이다."

| 결정 | 근거 |
|---|---|
| 코드에 상수로 박지 않는다 | §2.3의 "매직넘버 금지 — 전부 settings" |
| 이름에 `_hint`를 단다 | `budget`이라고만 부르면 다음 사람이 **강제되는 예산**으로 읽는다. §3.2가 경고한 `request.budget` ↔ `validate_topology`의 `budget` 혼동이 정확히 그 오독이며, 그 오독으로 값을 흘려보내면 **모든 설계가 거부된다** |
| 기본값 `1000`은 근거가 없고, 그 사실을 설정 주석에 적는다 | 기존 테스트가 쓰는 값과 같게 두어 동작 차이를 만들지 않는다. 근거 있는 값은 노드별 비용 표가 생겨야 나오며 그때 이 칸은 `_hint`를 떼고 `validate_topology`의 `budget`으로 승격된다 |

---

## 4. 이벤트와 관측

목적지는 **구조적 로그 + OpenTelemetry span 이벤트** 둘이다. `execute_workflow`가
이미 `trace_workflow_node("workflow_execution")` span을 쥐고 있으므로
(`graph.py:2427`) `add_span_event(span, kind, payload)`로 그대로 나간다 — 새 배관이
필요 없다.

| kind | 언제 | payload (출처) |
|---|---|---|
| `graph_design_requested` | 설계자를 부르기 직전 | `query`, `budget`, `catalog_size` |
| `graph_design_accepted` | 검증 통과 | `nodes`, `topology_hash` |
| `graph_design_rejected` | 위반 발견 | `violations`(rule·node·detail) |
| `graph_design_fallback` | 타임아웃·예외·**게이트 거부** | `reason` |

**payload는 `design_graph_or_fallback`이 정한다.** 호출부는 그것을 기록할 뿐이며
그 함수를 고치지 않는다 — 이벤트의 내용을 정하는 자리와 목적지를 정하는 자리를
섞지 않기 위해서다.

> ⚠️ **단 `graph_design_requested.payload["query"]`는 질의 전문이다**
> (`graph_design_ledger.py:143`). 그대로 흘리면 사용자 질의가 로그와 트레이스에
> 통째로 남는다. 이 저장소에는 이미 자르는 규율이 있다 — `graph.py:2438`이 50자,
> `graph.py:2444`의 `query_preview`가 100자다. **기록 시점에 같은 규율로 축약한다**
> (`query_preview`로 키 이름까지 맞춘다). 원본 payload를 바꾸지 않는 이유는 위와
> 같고, 축약은 *기록하는 쪽*의 책임이다.

**선택하지 않은 것과 그 이유:**

- **`WorkflowEventHandler` 확장** — 사용자 화면까지 도달시키는 안. 설계 폴백은
  사용자 강등이 아니라 **정상 동작**(정적 그래프)이므로 화면에 띄울 근거가 약하고,
  기본값이 `False`인 기능의 이벤트를 FE에 미리 그리는 모양이 된다.
- **새 테이블 `graph_design_events`** — 진짜 append-only 원장이 되지만
  마이그레이션 047이 늘어난다. **SCHEMA1**(§7 — 마이그레이션 44개를 신선한 DB에
  순서대로 적용하면 7개가 실패한다)을 안 고친 채 한 칸 더 쌓는 셈이다. H-1이
  같은 이유로 "마이그레이션 0건"을 결정타로 삼았다(D84).

> 📌 이 선택은 되돌릴 수 있다. 설계 run이 실제로 돌기 시작하고 "어느 설계가
> 반려됐는지"를 집계로 물어야 할 때가 오면 그때 테이블을 판단한다 — 그전까지는
> 답할 질문이 없는 스키마다.

---

## 5. 에러 처리

**설계 경로의 실패는 요청을 죽이지 않는다.** 폴백·거부·타임아웃·게이트 거부 전부
정적 그래프로 내려가고 사유를 남긴다.

**예외 하나: `asyncio.CancelledError`는 그대로 전파한다.** `graph_design_ledger.py:176-178`이
같은 규율을 이미 적었다 — `CancelledError`는 `BaseException`이라 `except Exception`에
잡히지 않으며, 취소 신호를 폴백으로 오인해 삼키면 안 된다. 새 `try` 블록도 같은
성질을 지킨다.

---

## 6. 테스트 (TDD)

**기존 가드 둘은 그대로 통과해야 한다.**

| 기존 가드 | 이 변경이 지켜야 하는 것 |
|---|---|
| `test_the_compiled_static_graph_matches_its_pre_task_9_snapshot` | `_create_workflow_graph`를 한 줄도 안 건드린다 → 스냅샷 해시 불변 |
| `test_the_static_path_does_not_carry_a_shared_designed_topology_slot` | 설계 토폴로지를 인스턴스 속성에 얹지 않는다 |

**새로 고정할 것:**

1. 플래그 off면 진행 이벤트가 **지금과 같은 노드·순서**로 나간다 (회귀 가드)
2. 플래그 on + 설계 승인 → ephemeral 그래프가 실행되고 진행 이벤트가 **그 그래프의
   노드**로 나간다
3. 설계 실패 네 갈래(타임아웃·예외·위반·게이트 거부) **각각**이 정적 폴백으로 끝나고
   사유가 기록된다
4. 동시 요청 둘이 서로 다른 그래프를 받는다 (G2-c 경합)
5. ETA가 이번 그래프에 없는 노드를 세지 않고, **설계된 그래프에서 0이 아니다**
6. 노드 종료 기록이 목록 인덱스가 아니라 **실제 직전 노드**다

> 🔴 **6번은 분기가 실제로 노드를 건너뛰는 그래프에서 검증해야 한다.** 모든 노드를
> 순서대로 지나는 그래프에서는 옛 코드와 새 코드가 똑같이 통과한다 — §8.1.2가
> 적은 교훈이 정확히 이것이다: "계측기가 도는지 보는 것은 통과를 보는 게 아니라
> **실패해야 할 때 실패하는지** 보는 것이다." `after <= before` 불변식이 양쪽 0이라
> 공허하게 성립해 버그를 되살려도 통과한 사례가 있다(D60).

**전체 스위트 기준선:** 2,938 passed / 23 skipped / 0 failed (2026-08-18, §10.4).
`pytest-randomly`가 매 실행 다른 시드를 쓰므로 순서 의존이 생기면 드러난다.

---

## 7. 하지 않는 것

- **`graph_design_enabled` 기본값을 바꾸지 않는다.** `False` 그대로다. 이 설계가
  파는 것은 "플래그를 켜면 실제로 무언가 달라진다"이지 "켜자"가 아니다.
- **`_create_workflow_graph`를 건드리지 않는다.** 스냅샷 해시가 그것을 강제한다.
- **재설계 루프를 만들지 않는다** (§3.2).
- **계약을 고쳐서 위반을 없애지 않는다.** §14.2가 적은 규율이다 — `.get()` 기본값을
  더해 `requires`를 떨어뜨리면 검증기는 초록이 되고 사용자가 보는 버그는 그대로다.
- **노드별 비용 표를 지어내지 않는다** (§3.2의 `budget`/`node_costs` 행).

---

## 8. 미결로 남기는 것

### G2-f — astream chunk는 완료 신호인데 시작으로 다뤄진다

`astream(initial_state, config)`은 `stream_mode`를 지정하지 않아 LangGraph 기본값인
`"updates"`로 돈다. updates 모드의 chunk는 **노드가 상태 업데이트를 낸 뒤** 방출된다 —
chunk 도착은 노드 *시작*이 아니라 *완료* 신호다. 그런데 현재 코드는 그 시점에
`record_node_start(node_name)`을 부르고 `on_node_start(...)`를 알린다(`graph.py:2567-2576`).

결과적으로 한 노드의 측정 구간이 **다음 노드가 끝날 때까지**로 밀려 있고, FE가 받는
"n번째 단계 시작"은 실제로는 그 단계의 완료다.

**이번 범위에 넣지 않는다.** G2-b가 겨눈 것("노드 집합을 실행에서 읽는다")과 **다른
결함**이고, 둘을 한 변경에 섞으면 ETA가 나아졌을 때 노드 집합 때문인지 시점 수정
때문인지 **귀속할 수 없다** — §13.5가 "여러 변경을 한 표본에"를 금지한 것과 같은 이유다.

고칠 때의 대가를 미리 적어 둔다: 기존 duration 히스토리의 의미가 바뀌어 학습된 ETA가
무효가 되고, FE의 단계 번호가 한 칸 당겨져 회귀처럼 보인다.

### 승인 재개는 정적 그래프에 묶여 있다 — 설계된 run 은 재개할 수 없다

`neos/api/handlers/approval_handlers.py:131`이 `multi_agent_workflow.graph`,
즉 **정적 컴파일 그래프**를 읽고 그 위에서 `aget_state`(139) ·
`aupdate_state`(176) · `astream(None)`(198)을 부른다. 그런데 설계된 run 의
그래프는 `_resolve_execution_graph` 가 만든 **호출 스코프의 ephemeral 그래프**이며
어디에도 캐시되지 않는다(§3.1의 "설계된 그래프는 캐시하지 않는다"). 설계된 run 이
`mission_approval`/`execution_approval` 에서 체크포인트를 남기고 멈추면, 재개는
그 토폴로지가 아니라 **다른 그래프**를 상대로 일어난다. 체크포인트의 노드가
정적 그래프에 없거나 간선이 다르면 재개가 엉뚱한 경로로 가거나 실패한다.

**지금은 잠재적이다** — 플래그가 꺼져 있는 한 모든 run 이 정적 그래프이고
재개 대상과 실행 대상이 같은 객체다. 그래서 이 브랜치는 `approval_handlers.py`
를 **한 줄도 고치지 않는다.**

**미루는 이유:** 고치려면 "이 스레드가 어떤 토폴로지로 멈췄는가"를 재개 시점에
복원할 수 있어야 한다. 그러려면 토폴로지(또는 그 해시와 원본)를 체크포인트와
같은 수명으로 **영속화**해야 하는데, 그것이 §4가 "새 테이블 `graph_design_events`"
를 물린 것과 같은 판단에 걸린다 — SCHEMA1(마이그레이션 44개 중 7개가 신선한 DB
에서 실패한다)을 안 고친 채 마이그레이션을 한 칸 더 쌓는 셈이다. 설계된 그래프를
프로세스 메모리에 캐시해 우회하는 안은 §2.3이 금지한 공유 슬롯을 캐시 층에서
되살리고, 워커가 여럿이면 애초에 성립하지 않는다.

**대가:** 이것이 열려 있는 동안 `graph_design_enabled` 를 켜는 것은 **승인
게이트가 있는 배포에서 안전하지 않다.** 즉 이 항목은 "언젠가"가 아니라 **플래그를
켜기 전에 반드시 닫아야 하는 선행 조건**이다. 우회로가 하나 있다: 설계된
토폴로지에서 승인 게이트 노드를 제외하면(§3.3의 `interrupt_before` 계산이 이미
교집합을 쓰므로 한 줄이다) 설계된 run 은 멈추지 않아 재개 자체가 없다 — 대신
설계 경로에서 사람 승인을 포기하는 것이므로, 그 선택도 이 항목이 닫힐 때 함께
판단한다.

### 이 문서가 답하지 않는 것

- **G1-a의 위반 3건** — 계약이 "`final_response`가 없을 때만 필요"라는 조건부
  `requires`를 표현하지 못해 진짜 버그와 무해한 경로가 같은 서명을 낸다(§14.2).
  계약 표현력의 확장이 필요하며 별도 판단이다(§14.4 후보).
- **`requires`의 기계 검증 0/30** — §14.4가 적은 정직성 지표. 검증기가 쓰는 두 필드
  (`writes`·`requires`)가 가장 덜 검증된다. 이 설계는 그 상태를 그대로 물려받는다.

---

## 9. 참조

- 로드맵: `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` §14(트랙 G) · §14.3(G2 항목표) ·
  §15.3(H3의 관문이 G2-b인 이유)
- 선행 설계: `docs/superpowers/specs/2026-08-14-subagent-graph-engineering-loop-design.md`
- 선행 커밋: `8a1cdd47`(C1·I1·I3) · `0d14dd76`(ephemeral 실행) · `500a238f`(공유 슬롯 제거)
- 코드: `neos/workflow/graph.py`(`execute_workflow`·`build_ephemeral_workflow`) ·
  `graph_design_ledger.py` · `graph_designer.py` · `graph_designer_llm.py` ·
  `topology.py` · `topology_export.py` · `contracts.py` · `events.py`
- 기존 가드: `tests/workflow/test_ephemeral_graph_execution.py` ·
  `test_graph_design_ledger.py` · `test_static_graph_contract.py`

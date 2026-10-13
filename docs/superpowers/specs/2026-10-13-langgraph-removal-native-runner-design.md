# LangGraph 제거 — 네이티브 워크플로 러너와 작업 생명주기 (W1)

- 날짜: 2026-10-13
- 상태: 설계 승인(섹션 ①~⑥ · 실행 계약 세 가지, 2026-10-12~13) · 스펙 검토 대기
- 기준 커밋: `adbae5da` (dev)
- 범위: 하위 프로젝트 **W1**. W2(심층분석 루프 스킬 배선 + cron 스킬)·W3(데이터셋 정리)는 별도 spec 이다(§10)
- 로드맵 영향: 트랙 D 의 순서를 바꾼다 — **D3b(langgraph 제거)를 D4(LangChain 전송 전환) 앞에 둔다**(§11)

## 1. 배경 — 진단 (코드 대조 2026-10-12, `adbae5da`)

### 1.1 LangGraph 가 걸린 범위

LangGraph 런타임을 쓰는 곳은 채팅 워크플로 하나다. 심층분석·코딩 루프·서브에이전트·상시 에이전트(`neos/standing`)·Jev 는
langgraph 도 LangChain 도, 채팅 그래프도 import 하지 않는다.

| 위치 | 쓰는 것 |
|---|---|
| `neos/workflow/graph.py` | `StateGraph` 정적 배선(`_create_workflow_graph`) · 설계 그래프 조립(`build_ephemeral_workflow`, `defer=True` 포함) · `compile(checkpointer, interrupt_before)` · `astream` · `GraphInterrupt` |
| `neos/workflow/checkpointer.py` | `PostgreSQLCheckpointer(BaseCheckpointSaver)` |
| `neos/workflow/resume_graph.py` + 호출부 셋 | `aget_state` / `aupdate_state` / `astream(None)` — `api/handlers/approval_handlers.py` · `api/channels/workflow_approvals.py` · `tasks/scheduled_task_runner.py` |
| `neos/workflow/topology_export.py` | `workflow.add_*` 호출을 AST 로 읽는다(트랙 S 불변식 5) |
| 죽은 코드 | `workflow/distributed_graph.py` · `workflow/checkpointers/hybrid_checkpointer.py`(import 자체가 깨져 있다) · CLI 워크플로 빌더(`cli_workflow_builder.py` + `workflow/builder/`) |
| 테스트 | langgraph 를 import 하는 16개 |

LangChain(39개 파일, 주로 `HumanMessage`·채팅 모델)은 노드 **안**에서만 쓰인다. 그래프 런타임은 `stream_mode="messages"`·
`astream_events` 를 쓰지 않는다. 그래서 D3b 는 D4 없이 할 수 있다(langchain-core 의존은 남는다).

### 1.2 지금 런타임 경로의 결함 (프로브 재현, 실 DB 미확인 — dev DB 가 꺼져 있었다)

| # | 결함 | 근거 |
|---|---|---|
| R1 | `PostgreSQLCheckpointer.aget_tuple` 이 `CheckpointTuple` 이 아니라 평범한 튜플을 돌려준다 → **같은 thread 두 번째 턴에서** `'tuple' object has no attribute 'checkpoint'` | 같은 반환 모양으로 프로브 재현 |
| R2 | `aput_writes` 는 저장하지 않는다. JSON 직렬화라 `SearchResult` 가 dict 로 돌아온다 | 코드 읽기 |
| R3 | LangGraph 1.x 의 `interrupt_before` 는 `astream` 에서 던지지 않고 `{'__interrupt__': ()}` chunk 를 낸다. `execute_workflow` 의 `except GraphInterrupt` 가지는 죽었고 `on_approval_request` 의 유일한 호출부가 거기 있다. 루프는 `final_state = ()` 로 끝난다 | 프로브 재현 |
| R4 | `final_state` 는 updates 모드의 **마지막 노드 부분 갱신**이지 전체 상태가 아니다 | 코드 읽기 |
| R5 | 응답 생성기·하네스·수리 노드가 **전체 상태**를 갱신으로 돌려준다(`return state`, `{**state, **updates}`) → `operator.add` 필드에 리스트 전체가 다시 붙는다. 노드 셋짜리 프로브에서 `search_results` ×4 (S-ORCH 의 "중복") | 프로브 재현 |
| R6 | 승인 타임아웃 주입은 Celery 워커에서 `multi_agent_workflow._graph_initialized` 가 False 라 **늘 건너뛴다** | 코드 읽기 |
| R7 | 채널 승인 뒤 재개 결과를 버린다(CH-RESUME) | 로드맵 §11 |
| R8 | 채널 대화가 이전 턴을 보지 않는다 — 게이트웨이가 `chat_history` 를 넘기지 않는다(CH-HIST) | 로드맵 §11 |
| R9 | `/new`·`/clear` 가 게이트웨이 장부만 지우고 체크포인트 thread 는 두지 않는다 | `api/channels/gateway.py` 리셋 블록 |
| R10 | `conversation_context_processor` 가 이력을 "최근이 앞" 으로 가정하고 `chat_history[:limit]` 로 자른다 — 입력은 오래된 것부터라 `summary_only`(상한 10)에서 **가장 오래된 10개**를 본다 | `processors/conversation_context_processor.py:243` |

트랙 S 가 D3b 에 넘긴 런타임 불변식(턴 간 승계 · 승인 재개)은 `MemorySaver` 테스트로만 고정됐고, 프로덕션 체크포인터
경로는 그 의미론을 제공하지 못하고 있었다. **그러므로 이 작업의 목표는 "LangGraph 와 같게" 가 아니라 의미론을 정하고 지키는 것이다.**

### 1.3 실행 계약 세 가지의 현재 (사용자 요구 2026-10-13)

**결과의 작성자.** 심층분석 리포트는 잡이 `report_markdown` 을 **그대로** 대화 메시지로 저장한다 — 지켜진다. 그러나
ROMA·HyperDeep·미션이 만든 `final_response` 도 `RESEARCH_HARNESS` 를 지나고, 게이트가 실패하면 `RESEARCH_HARNESS_REPAIR` 가
`final_response` 를 지우고 응답 생성기로 **다시 쓴다**(`graph.py` `_research_harness_repair_node`).

**실행 소유권.** 조사 자식은 서브에이전트 lease 를 가진다. **심층분석 부모 run 에는 없다.** 같은 run 이 둘 이상 도는 경로 셋:

1. `RESUMABLE_STATUSES = {"running", "failed"}` 이고 재개 라우트(`POST /deep-analysis/{run_id}/resume`)가 **실행 중인 run 도** 재개한다
2. Redis broker 에 `visibility_timeout` 이 없다(기본 3600초). 잡 `time_limit` 은 3900초, `task_acks_late=true` — 1시간을 넘는 run 은 **다른 워커에 다시 배달된다**
3. 채팅 디스패치 노드가 같은 턴에서 다시 실행되면 run 을 하나 더 만든다(멱등 키 없음)

원장의 `pg_advisory_xact_lock` 은 **커밋을** 직렬화할 뿐 두 부모의 동시 LLM 호출을 막지 않는다.

**입구별 생명주기.**

| 입구 | 작업 ID | 승인 | 결과 저장 | 전달 |
|---|---|---|---|---|
| 웹 | 없음(대화 id) | `stream_manager` | 대화 메시지 | SSE |
| 채널 | 없음(세션 키) | 게이트웨이 포트 | 없음 | 반환 문자열 · 승인 뒤 결과는 버림(R7) |
| 예약 | `scheduled_{uuid}` | 타임아웃이 워커에서 no-op(R6) | 없음 | 워커에서 게이트웨이 호출 → 조용히 실패 |
| 상시 트리거 | 코딩 태스크 id | 코딩 승인 | 코딩 체크포인트 | Q10b 알림 큐 |
| 채팅발 심층분석(웹·채널) | run id | — | 디스패치 노드는 `state["conversation_id"]` 로 저장 대상을 정하는데, 웹 스트림 파이프라인도 게이트웨이도 그 키를 넘기지 않는다 → **저장 안 됨**(코드 읽기) | **어디로도 안 감** |

## 2. 목표 · 비목표 · 수용 기준

**목표**

- 채팅 워크플로를 LangGraph 없이 돌린다. `pyproject.toml` 에서 `langgraph` 를 뺀다
- 상태는 `session_id` 단위로 턴 사이에 이어진다(트랙 S 불변식 1·2 유지)
- 세 실행 계약을 코드로 지킨다: **결과 작성자 · 실행 소유권 · 모든 입구의 같은 생명주기**
- 위 R1~R10 을 닫는다

**비목표**

- LangChain 제거(D4) · 플러그인 스킬(트랙 S P2) · 설계 그래프의 병렬 실행 · 코딩 태스크·심층분석 run 의 엔진 통합
  (`PARENT_MEDIATED_COLLABORATION_DESIGN.md` 의 "네 세계를 합치지 말 것"을 따른다 — 생명주기 기록만 잇고 엔진은 그대로 둔다)

**수용 기준**

1. 코드와 `pyproject.toml` 어디에도 `langgraph` 가 없다
2. 실 DB 확인 목록(§6.2) 일곱 항목이 통과한다
3. `tests/standing` · `tests/jev` · `tests/api/channels` 가 **변경 0줄**로 통과한다(diff 로 확인). **예외 하나**:
   `tests/api/channels/test_gateway_router.py` 의 `test_runtime_workflow_approvals_resumes_without_coding_loop` 와 그것만 쓰는
   `_FakeResumeGraph` 는 LangGraph 내부(`resume_graph_for`·`aget_state`·`aupdate_state`)를 흉내 내므로 승인 서비스(§4.5) 기준으로
   다시 쓴다. 같은 파일의 나머지 테스트는 변경 0줄이다
4. 옮기기 전후 테스트 이름 목록의 차이가 전부 설명된다(`--collect-only -qq`)

## 3. 결정 (사용자, 2026-10-12~13)

| 결정 | 내용 |
|---|---|
| 순서 | 로드맵(D4 → D3b)을 뒤집어 지금 걷어낸다 |
| 통합 루프 | 심층분석(deep_analysis) 루프 |
| P0 | **턴 사이 상태를 이어받는다** |
| 승계 단위 | **`session_id`** (Q8 스레드 아님) |
| Q8 꺼짐 | 세션 상태 안 유한 대화 기록으로 대체 — CH-HIST 를 함께 닫는다 |
| P5 | 설계 그래프는 **순차만**. 병렬 토폴로지는 검증에서 거절하고 정적 그래프로 폴백 |
| 옛 데이터 | **B** — 대기 승인은 만료, 닿는 지점에서 안내. 대화 상태는 새로 시작 |
| 접근 | 배선 표 하나 + 런타임 둘을 플래그로 전환 → 기본값 전환 → 삭제 |
| CH-RESUME | W1 에 포함 |
| R10 | W1 에 포함(`[:limit]` → `[-limit:]`) |
| CLI 워크플로 빌더 | 삭제 |
| 상시 트리거 연결 | **B** — Q 코드는 건드리지 않고 코딩 쪽 생성·완료 훅에서 작업 기록을 잇는다 |
| 무영향 | dots(트랙 Q)·Jev 컴포넌트 |

## 4. 설계

### 4.1 배선 표 — `neos/workflow/wiring.py`

```python
Requires = tuple[tuple[str, bool], ...]     # (플래그 키, 기대값) -- 전부 맞아야 켜진다

@dataclass(frozen=True)
class NodeSpec:   name: str; handler: str; requires: Requires = ()
@dataclass(frozen=True)
class Edge:       source: str; target: str; requires: Requires = ()
@dataclass(frozen=True)
class Route:      label: str; target: str; requires: Requires = ()
@dataclass(frozen=True)
class Branch:     source: str; router: str; routes: tuple[Route, ...]; requires: Requires = ()
@dataclass(frozen=True)
class Interrupt:  node: str; requires: Requires = ()

NODES: tuple[NodeSpec, ...]; EDGES: tuple[Edge, ...]; BRANCHES: tuple[Branch, ...]; INTERRUPTS: tuple[Interrupt, ...]
FLAG_ATTR_TO_KEY: dict[str, str]             # settings 속성 → 플래그 키 (여섯 개)
def resolve_wiring(flags) -> Wiring          # requires 가 맞는 항목만, 닫혀 있지 않으면 WiringError
def wiring_from_topology(topology, host) -> Wiring   # 설계 그래프 (§4.10, Plan 2)
def topology_of(wiring) -> GraphTopology             # 스냅샷 해시 · 노드 수 테스트의 입력
```

- 지금 `_create_workflow_graph` 의 `if settings.X:` 블록은 항목의 `requires` 가 된다(켜짐은 `(키, True)`, 꺼짐 경로는
  `(키, False)`). 경로 맵 안의 플래그별 대상(예: 스킬 실행이
  켜지면 skip·use 가 `SKILL_EXECUTOR` 로)은 **경로(`Route`)마다 `requires`** 를 두어 표현한다. `resolve_wiring` 은 켜진 경로만
  남기고, 한 라벨에 켜진 경로가 둘이면 `WiringError` 다(Plan 1 에서 정함 — 라벨 아홉 × 플래그 여섯의 조합을 `Branch` 사본으로
  적으면 폭발한다)
- `handler`·`router` 는 `MultiAgentWorkflow` 의 메서드 이름이다. 노드 핸들러와 `node_contract` 는 바꾸지 않는다
- **토폴로지 동일성**: 단계 2 의 첫 커밋에서 `topology_of(resolve_wiring(flags))` 가 기존 AST 추출 결과와 **노드·엣지 집합으로**
  같음을 모든 플래그 조합에서 확인한 뒤 AST 추출기를 지운다. `settings.SKILL_EXECUTION_ENABLED` 별칭은 **둔다** — 여섯 배선 플래그가 모두 같은 별칭 지도(`wiring.FLAG_ATTR_TO_KEY`)로 실행 시점 값을 읽으므로 하나만 지우면 비대칭이 된다(Plan 1 에서 정함)
- LangGraph 어댑터(`neos/workflow/runtime/langgraph_adapter.py`, 단계 7 에서 삭제)는 같은 표에서 `StateGraph` 를 조립한다

### 4.2 러너 — `neos/workflow/runtime/runner.py`

```python
class WorkflowRunner:
    def __init__(self, wiring, owner, *, interrupt_before=(), step_limit): ...
    def stream(self, state, *, start_at: str | None = None) -> AsyncIterator[dict[str, dict]]
    @property
    def outcome(self) -> Completed | Interrupted   # stream 이 끝난 뒤
```

- 한 걸음: 핸들러 실행 → 갱신을 리듀서로 병합 → `{node: update}` chunk 를 낸다(LangGraph updates 모드와 **같은 모양**) →
  `Edge` 또는 `Branch` 라우터로 다음 노드 → `END` 면 멈춘다
- **리듀서는 `AgentState` 의 `Annotated` 메타데이터에서 읽는다**(`typing.get_type_hints(include_extras=True)`) — `operator.add` 누적,
  `merge_node_dict` 병합, 그 밖은 교체. 표에 다시 적지 않는다
- **갱신은 계약의 `writes` 안의 키만.** 핸들러가 `NODE_CONTRACTS[node].writes` 밖의 키를 내면 러너가 거절한다(테스트·development
  에서 예외, 그 밖에서는 해당 키를 버리고 `workflow_update_rejected_total{node,key}`). `writes_hand_curated=True` 인 계약도
  이 검사를 받는다 — 목록이 틀리면 지금 드러나야 한다
- **(Plan 1 에서 정함) R5 는 노드를 하나씩 고치지 않고 노드 경계 정규화로 닫았다** — `neos/workflow/runtime/node_updates.wrap_node`
  가 노드에 상태의 작업 사본을 넘기고, `{**사본, **반환값}` 을 이전 상태와 비교해 "이번 노드의 갱신" 만 남긴다(누적 필드는 새
  항목만, 그 밖은 바뀐 키만). 전체 상태를 돌려주는 노드도, 부분 dict 를 돌려주며 사본에 제자리로 붙이는 노드도 같은 갱신을 낸다.
  LangGraph 어댑터와 네이티브 러너가 같은 함수를 쓴다
- **(Plan 1 에서 정함) 턴 결과는 모든 chunk 를 `node_updates.apply_update`(리듀서 의미론: 누적·병합·교체)로 접은 전체 상태다**
  — 마지막 chunk 를 결과로 읽던 R4 를 LangGraph 경로에서도 닫았다. 승인 재개(`approval_handlers._resume`)도 같은 함수로 접는다
- **(Plan 1 에서 정함) 정책은 `workflow.node_update_policy`(`report`·`drop`·`raise`) 다.** 스키마 기본값과 development 는
  `report`(지금 동작과 같다 — 기록만 하고 키를 둔다), 테스트 세션(`tests/fixtures/config/test-session.yaml`)은 `raise`.
  development 는 실제 노드로 라이브 dry run 을 돌려 위반이 없음을 본 뒤(Plan 3 단계 5) `raise` 로 올린다. 위에 적은 "테스트·
  development 에서 예외, 그 밖에서는 버림" 은 그때의 목표 상태다
- **(Plan 1 에서 정함) R3 는 LangGraph 경로에서 `__interrupt__` chunk 를 승인 요청으로 바꿔 닫았지만, 올바른 체크포인터를
  전제로 한다.** PostgreSQL 체크포인터에서는 승인 인터럽트가 여전히 R1(`aget_tuple` 이 `CheckpointTuple` 이 아니다)에 걸린다 —
  Plan 2 의 세션 저장소가 닫는다
- `step_limit` 은 지금의 `_recursion_limit_for` 계산 그대로. 넘으면 `StepLimitExceeded`
- `interrupt_before` 노드에 닿으면 **실행 전에** `Interrupted(next_node, state)` 로 끝난다. 예외가 아니라 결과다
- `Completed.state` 는 **병합된 전체 상태**다(R4)
- `start_at` 은 승인 재개용이다. 초기 상태를 다시 만들지 않는다(불변식 3)
- 저장하지 않는다. 저장은 바깥 층(§4.3·§4.4)이 턴 경계와 승인 대기 직전에 한다. 턴 도중 프로세스가 죽으면 그 턴은 남지 않고
  직전 턴의 세션 상태가 남는다

`execute_workflow` 는 `graph_astream_source` 이음매로 chunk 를 받으므로 진행 추적 코드(`node_started`·ETA)는 그대로다.
`except GraphInterrupt` 가지는 지우고 `Interrupted` 결과에서 `on_approval_request` 를 부른다(R3).

### 4.3 세션 저장소와 상태 승계 — `neos/workflow/runtime/sessions.py`

**규칙: 이번 턴의 입력은 이어받은 상태 위의 갱신이다.** 턴 시작에 `session_id` 의 상태를 읽고, `_create_initial_state` 의 결과를
**같은 리듀서로** 병합한다. 교체 필드(턴 리셋 필드 `skill_calls`·`skill_sources`·`approval_outcome`·`skill_execution_done` 포함)는
이번 턴 값으로 덮이고, 누적 필드는 이전 값이 남고, 입력이 건드리지 않는 키는 이어진다. LangGraph 의 `astream(initial_state)` 와
같은 의미론이라 트랙 S 의 2턴 테스트 사양이 그대로 유효하다. **이어받을 필드 목록은 따로 두지 않는다.**

**승인 필드도 턴 리셋 필드가 된다.** 지금 `_create_initial_state` 는 `pending_approvals`·`approval_decision` 을 채우지 않아,
상태가 이어지면 버려진 승인이 다음 턴의 라우터를 `needs_approval` 로 보낸다(S-PEND). 두 필드를 `[]`·`None` 으로 채운다.
승인 상태의 정본은 작업 기록(§4.4)이고, 승인 재개는 초기 상태를 다시 만들지 않으므로(`start_at`) 이 리셋은 재개를 해치지 않는다.

**누적 상한.** 저장 때 누적 필드마다 최근 `workflow.session.max_carried_items` 개만 남긴다. 기본값은 구현 계획에서 실측으로
정한다. 잘린 수는 `workflow_session_trimmed_total{field}`.

**테이블** `workflow_sessions` (마이그레이션 096)

| 컬럼 | |
|---|---|
| `session_id` text PK | 웹은 `conversation_id`, 채널은 세션 키 |
| `user_id` text | |
| `state` jsonb | 코덱 출력 |
| `version` int | 낙관적 잠금 |
| `updated_at` timestamptz | 보존 정리 기준(30일) |

세션당 최신 스냅샷 한 행. 저장은 `UPDATE … WHERE version = :loaded`(없으면 INSERT) — 겹친 턴은 **나중 저장이 진다**(경고 +
`workflow_session_conflicts_total`, 응답은 이미 나갔다). 턴 내내 행 잠금을 잡지 않는다. 메모리 구현과 Postgres 구현이 같은
계약 테스트를 지난다.

**코덱** `neos/workflow/runtime/state_codec.py` — 타입 태그로 `SearchResult`·`AnalysisResult`·`GenerationResult`·`WorkflowError`·
`datetime`·`Decimal` 를 원래 타입으로 복원한다. `_` 로 시작하는 런타임 주입 키(`_event_handler` 등)는 저장하지 않는다.
**등록되지 않은 타입은 실패한다**(조용히 dict 로 바꾸지 않는다 — R2).

**실패.** 세션 저장 실패는 턴을 막지 않는다(경고 + 카운터). 세션 읽기 실패는 빈 상태로 진행한다(경고 + 카운터).

### 4.4 작업 생명주기 — `neos/workflow/runtime/work.py`

**작업(work) = 입구에서 실행 한 번.** 웹 메시지 하나, 채널 메시지 하나, 예약 실행 하나, 트리거로 열린 코딩 태스크 하나가 각각
작업 하나다. 세션은 "무엇을 기억하나", 작업은 "누가 언제 무엇을 했고 결과를 어디로 보내나" 를 맡는다.

**테이블** `workflow_runs` (마이그레이션 097)

| 컬럼 | |
|---|---|
| `work_id` text PK | `wk_…` |
| `entry` text | `web` · `channel` · `schedule` · `trigger` · `api` |
| `kind` text | `workflow` · `deep_analysis` · `coding` — 무엇이 실행하나 |
| `ref_id` text null | `kind` 가 `deep_analysis` 면 run id, `coding` 이면 task id |
| `parent_work_id` text null | 채팅이 낸 심층분석 run 처럼 작업이 낳은 작업 |
| `session_id` text null · `user_id` text | |
| `status` text | `running` · `waiting_approval` · `completed` · `failed` · `expired` |
| `pending` jsonb null | 승인 대기 때 `{next_node, request_ids}` |
| `result` jsonb null | `{final_response, author, verified_by}` (§4.6) |
| `delivery` jsonb | 전달 대상 `{kind: sse\|channel\|conversation\|none, …}` |
| `version` int · `created_at` · `updated_at` | |

```python
class WorkLifecycle:
    async def start(entry, kind, *, user_id, session_id, delivery, parent=None, ref_id=None) -> str
    async def interrupt(work_id, pending) -> None
    async def complete(work_id, result) -> None        # 결과 저장 + 전달 아웃박스에 적기 (§4.7)
    async def fail(work_id, error) -> None
```

**입구별 연결.** 채팅 워크플로 입구는 **`execute_workflow` 가 스스로** 작업을 시작한다. 입구 종류와 전달 대상은 호출자가 이미
넘기는 키(`channel_source`·`channel_type`·`channel_id`·`session_id`)에서 정한다 — 게이트웨이·웹 파이프라인·예약 러너의 입력
모양은 바뀌지 않는다(§5 경계 1·3).

| 입구 | `channel_source` | 전달 대상 |
|---|---|---|
| 웹 | 없음(`api`) → `web` | `sse` + `conversation` `{conversation_id: session_id}` (웹의 `session_id` 는 `conversation_id` 다) |
| 채널 | `slack`·`discord`·`telegram` → `channel` | `channel` `{channel_type, channel_id}` (+ 메타데이터의 `thread_id`) |
| 예약 | `scheduler` → `schedule` | 태스크의 채널 또는 `none` |
| 채팅발 심층분석 | 디스패치 노드가 `start(..., "deep_analysis", parent=현재 work)` | **부모의 전달 대상을 물려받는다** — 웹발 리포트는 그 대화에, 채널발 리포트는 그 채널로 간다. 잡의 `_persist_assistant_message` 는 run 의 `conversation_id` 대신 작업의 전달 대상을 읽는다 |
| 상시 트리거 · 그 밖의 코딩 태스크 | **코딩 쪽 훅**(결정 B): `CodingTaskService.create_task`·`PostgresCodingService.create_task` 뒤의 새 생성 훅이 `start("trigger"\|"api", "coding", ref_id=task_id)`, 기존 완료 훅 자리(`CodingRunService._on_completed` 와 나란히)가 `complete` | 코딩 태스크의 기존 알림 경로(Q10b)를 **그대로** 쓴다 — `delivery={kind: none}` 으로 기록만 한다 |

코딩 태스크의 엔진·lease·코딩 승인·체크포인트는 그대로다. 작업 기록은 **같은 ID 체계와 같은 결과 저장 위치**를 주고, 전달은
기존 경로를 바꾸지 않는다(Q 무영향). Q 코드(`neos/standing/*`)는 바뀌지 않는다.

**`execute_workflow` 결과 계약에 `work_id` 를 더한다** — 기존 키(`success`·`response`·`final_response`·`interrupted`·
`pending_approvals`·`metadata`·`errors` …)는 그대로다. 소비자는 모르는 키를 무시한다(Q8 테스트의 fake 도 그렇다).

### 4.5 승인 서비스 — `neos/workflow/runtime/approvals.py`

```python
class WorkflowApprovals:
    async def pending_for_session(session_id) -> PendingApproval | None   # 소유자 · request ids · work_id
    async def decide(work_id, request_id, decision, actor) -> ResumeTicket | Refusal
    async def resume(ticket, event_handler) -> dict          # execute_workflow 와 같은 결과 dict
    async def expire(work_id, request_id) -> bool            # 시스템 actor 의 rejected, 재개하지 않는다
```

- 그래프 객체가 아니라 **`workflow_runs` 행**을 읽는다 — 어느 프로세스에서든 동작한다(R6)
- `decide` 는 request id ∈ 대기 목록 · actor = 소유자(시스템 만료 제외) · 버전 일치를 확인하고, 세션 상태에 `approval_decision` 을
  쓰고 작업의 `pending` 을 비운다. 같은 결정 두 번은 버전 충돌로 거절한다
- `resume` 은 저장된 `next_node` 부터 러너를 돈다(`start_at`). 다시 승인 대기에 걸리면 `interrupted` 를 돌려준다. 끝나면
  세션 저장 · 대화 기록 추가 · `WorkLifecycle.complete` — **처음 실행과 같은 꼬리**를 지난다
- 대기가 없는 승인에 닿으면(만료·옛 데이터) `Refusal("expired")` — 호출부가 "이 승인은 만료되었습니다. 다시 요청해 주세요" 로 답한다

**호출부**

| 호출부 | 바뀌는 것 |
|---|---|
| 웹 `approval_handlers` | `decide` → 백그라운드 `resume` → `stream_manager`. 이벤트 모양은 그대로 |
| 채널 `RuntimeWorkflowApprovals` | 공개 메서드 `interrupt_owner`·`decide` 의 **이름·시그니처·반환 문자열 유지**. 안쪽만 서비스로. 재개 결과는 작업의 전달 대상(채널)으로 간다 — **CH-RESUME 닫힘**(R7) |
| 타임아웃 `scheduled_task_runner` | `expire` — 워커에서 실제로 동작한다(R6) |
| `execute_workflow` | `Interrupted` 면 `WorkLifecycle.interrupt` + `on_approval_request` + `interrupted` 결과(R3) |

`neos/workflow/resume_graph.py` 의 설계 그래프 재조립 로직은 `wiring_from_topology` 로 옮긴다.

### 4.6 결과의 작성자

- 결과에 `author` 와 `verified_by` 를 붙인다. `AgentState` 에 `final_response_author: Optional[str]`,
  `final_response_verified_by: Optional[str]` 을 두고, `final_response` 를 쓰는 노드는 둘을 함께 쓴다
  (`direct_response`·`response_generator`·`recursive`·`hyper_deep`·`mission_integrator`·`task_scheduling`·`ui_frame`)
- **검증된 결과는 다시 쓰지 않는다.** `final_response_verified_by` 가 있으면
  - `RESEARCH_HARNESS` 는 판정을 기록만 하고 수리로 보내지 않는다(라우터 `_should_route_to_harness_repair` 가 `end`)
  - `_create_workflow_result` 의 하네스 차단 치환을 하지 않는다
  - 러너가 이후 노드의 `final_response` 갱신을 거절한다(§4.2 와 같은 처리 — 테스트·development 예외, 그 밖은 버림 + 카운터)
- 검증된 작성자 목록은 코드 상수다: 심층분석 리포트(`deep_analysis` / `report_grader`). HyperDeep·ROMA·미션은 **검증된
  작성자가 아니다** — 채팅 하네스가 계속 게이트하고 수리한다. 목록을 늘리는 것은 그 엔진이 자기 검증기를 가질 때의 별도 결정이다
- 심층분석 리포트는 지금처럼 잡이 `report_markdown` 을 그대로 저장하고, 작업 완료(§4.4)가 그것을 **그대로** 전달한다. 채팅
  계층은 리포트를 요약·정제·재생성하지 않는다(테스트로 고정 — 전달된 본문 = 원장의 `report_markdown`)

### 4.7 전달 아웃박스

- `workflow_deliveries` (마이그레이션 097, 같은 파일): `delivery_id`, `work_id`, `target` jsonb, `body`, `status`, `attempts`,
  `next_attempt_at`. **워커는 적기만 하고 API 프로세스가 보낸다** — Q10b 알림 큐(085)와 같은 모양·같은 재시도 정책
  (`retry_delay`)을 쓴다. 코드는 Q 모듈을 import 하지 않고 같은 규칙을 자기 모듈에 둔다(Q 무영향)
- `sse` 대상은 아웃박스를 거치지 않는다 — 살아 있는 스트림이 직접 받는다. 스트림이 없으면(재개·심층분석 완료) 대화 메시지가
  정본이고 FE 는 기존대로 다시 읽는다
- 예약 태스크의 워커 직접 전송(`_send_to_channel` 의 `ChannelGateway.get_instance()`)을 지우고 아웃박스로 옮긴다

### 4.8 대화 기록 대체와 리셋

**필드** `AgentState.session_transcript: List[{role, content, created_at, channel_type}]` — 교체형, `_create_initial_state` 가
채우지 않으므로 이어진다.

**기록** — 턴 경계(`execute_workflow`·`resume` 의 끝)에서 `final_response` 로 끝난 턴만 `(이번 턴 query, final_response)` 를
덧붙인다. 승인 대기·오류 턴은 기록하지 않는다. 상한은 개수 `chat.max_history_messages`, 항목 길이
`workflow.session.transcript_item_chars`. **Q8 플래그와 무관하게 늘 기록한다.**

**읽기** — 워크플로 입구에서 한 번

| 호출자 입력 | 이력 |
|---|---|
| `chat_history` 키가 **있다**(웹 DB 이력 · Q8 창 · 빈 리스트 포함) | 그대로 — 호출자가 정했다 |
| `chat_history` 키가 **없다**(Q8 이 붙지 않은 채널 대화) | `session_transcript` |

빈 리스트를 "정했다" 로 보는 이유: Q8 은 새 스레드 첫 턴에 `[]` 를 넘긴다. 순서는 웹과 같이 오래된 것부터, 현재 턴 제외.
`conversation_context_processor` 의 `[:limit]` 를 `[-limit:]` 로 고친다(R10).

**리셋** — `WorkflowSessions.reset(session_id)` 가 행을 지우고, 그 세션의 `waiting_approval` 작업을 `expired` 로 바꾼다.

| 계기 | |
|---|---|
| 채널 `/new`·`/clear` | 게이트웨이 리셋 블록에 한 줄. Q8 `rotate_for_session` 도 같은 블록에 있어 따로 손대지 않는다(R9) |
| 웹 새 대화 | 새 `conversation_id` |
| 웹 대화 삭제 | 삭제 경로에서 `reset` |
| 보존 30일 | 정리 태스크 |

### 4.9 심층분석 부모 run 의 실행 소유권 — `neos/workflow/deep_analysis/jobs.py`

- `deep_analysis_runs` 에 `lease_owner text`, `lease_expires_at timestamptz` (마이그레이션 098)
- `execute_run`·`resume_run` 은 시작 전에 **CAS 로 lease 를 얻는다**:
  `UPDATE … SET lease_owner = :me, lease_expires_at = now() + :ttl WHERE id = :run AND (lease_owner IS NULL OR lease_expires_at < now())`.
  못 얻으면 실행하지 않고 `RunLeaseHeld` — Celery 태스크는 재시도하지 않고 끝난다(다른 워커가 돌고 있다)
- 오케스트레이터 라운드마다 lease 를 갱신한다(`Orchestrator.checkpoint` 훅 자리). 갱신이 실패하면(다른 소유자) 라운드를 멈추고
  종료한다 — 원장 커밋은 그 앞에서 끝나 있다
- 종결(`completed`·`failed`)에 lease 를 비운다
- 재개 라우트와 `resume_run` 은 `failed` 이거나 lease 가 만료된 `running` 만 받는다. 살아 있는 run 의 재개 요청은 409
- `celery.broker_transport_options.visibility_timeout` 을 `deep_analysis.job_time_limit` 보다 크게 둔다 — 설정 검증이
  `visibility_timeout > job_time_limit` 를 강제한다
- run 생성에 **멱등 키**: 채팅 디스패치는 `work_id` 를 `create_run(idempotency_key=…)` 에 넘기고, 같은 키의 run 이 있으면
  그 run 을 돌려준다(새 run 을 만들지 않는다). Q3 상시 질문의 제출은 지금 계약 그대로 둔다(키 없음 = 매번 새 run)
- lease TTL 은 `deep_analysis.job_lease_seconds`(라운드 최대 시간보다 크게 — 구현 계획에서 실측)

### 4.10 설계 그래프 — 순차만

- 승인된 `GraphTopology` → `wiring_from_topology`. 트랙 I 템플릿 노드의 자기 반복은 `Branch` 로 표현한다
- `validate_topology` 에 규칙 `parallel_unsupported`: 한 노드에서 무조건 엣지가 둘 이상 나가거나 `defer` 노드가 있으면 위반 →
  기존 `design_graph_or_fallback` 이 정적 그래프로 폴백한다
- `EphemeralApprovalGateUnsupported`·`EphemeralSubagentUnsupported` 의 의미는 그대로다(체크포인터 → 세션 저장소)

## 5. Q · Jev 무영향의 경계

바뀌지 않는 것: `neos/standing/*` · `neos/jev/*` · `neos/coding/loop/*` · `neos/workflow/deep_analysis/*` 의 판정자·채점기.
경계는 다섯 계약이고 전부 §6 계약 테스트로 고정한다.

1. `execute_workflow` 결과 dict 의 기존 키 (추가 키 `work_id` 만)
2. `RuntimeWorkflowApprovals.interrupt_owner`·`decide` 의 시그니처와 반환 문자열
3. 게이트웨이 → Q8 의 `open_turn`/`close_turn`/`rotate_for_session` 호출 순서
4. `submit_deep_analysis_job` 의 시그니처(멱등 키는 키워드 인자 추가)
5. 코딩 태스크 생성·완료의 기존 의미 — 새 훅은 실패해도 태스크 생성·완료를 막지 않는다(로그만, Q13f 훅과 같은 규율)

import 가드: 코딩 루프·심층분석·standing·Jev 는 `neos.workflow.graph`·`neos.workflow.runtime` 을 import 하지 않는다.
(코딩 쪽 생성 훅은 `neos.coding.application` 에 두고 `WorkLifecycle` 을 포트로 주입받는다.)

## 6. 전환 단계와 확인

### 6.1 단계

각 단계는 그 자체로 머지 가능하다. 단계 4 까지 기본 동작은 바뀌지 않는다.

| 단계 | 내용 | 기본 |
|---|---|---|
| 1 안전망 | 계약 테스트(§7.1) · import 가드 · 죽은 코드 삭제(`distributed_graph.py`·`hybrid_checkpointer.py`) | 그대로 |
| 2 배선 표 | `wiring.py` · LangGraph 어댑터가 표에서 조립 · 토폴로지 동일성 확인 후 AST 추출기 삭제 · R5 노드 반환 수정 + `writes` 검사 | 그대로 |
| 3 러너·저장·작업 | 러너 · 코덱 · 096·097 · `WorkLifecycle` · `WorkflowApprovals` · 아웃박스 · 플래그 `workflow.runtime: langgraph \| native` · 호출부(실행·웹 승인·채널 승인·타임아웃·리셋)가 선택 지점 하나를 거친다 · 코딩 생성 훅 | langgraph |
| 4 계약 완성 | 대화 기록 대체 · 리셋 · R10 · CH-RESUME · 결과 작성자 · 예약 전달 이전 · 심층분석 lease(098, 런타임 플래그와 무관하게 켠다) · 멱등 키 | langgraph (lease 는 즉시) |
| 5 development | `neos.development.yaml` 에서 native · §6.2 확인 | dev native |
| 6 기본 전환 | 모든 프로파일 native · 옛 대기 승인 만료 표시 | native |
| 7 삭제 | 어댑터 · `checkpointer.py` · CLI 워크플로 빌더 · 플래그 · `langgraph_checkpoints` drop(099) · `pyproject.toml` · 문서(로드맵 §1 D행·§13 D·S, `CONFIGURATION.md`, `ROADMAP.md`) | — |

마이그레이션은 `db/BOOTSTRAP_ORDER.txt` 에 등록한다.

### 6.2 실 DB 확인 목록 (단계 5, 전부 통과해야 단계 6)

1. 웹 2턴 — 두 번째 턴이 죽지 않고 첫 턴을 이어받는다
2. 채널 2턴(Q8 꺼짐) — 두 번째 턴의 이력에 첫 턴이 있다
3. 승인 왕복 웹·채널 — 채널은 결과가 채널로 도착한다
4. 승인 타임아웃 — 워커에서 거절이 기록되고 작업이 `expired`
5. `/new` 뒤 빈 상태
6. 설계 그래프 — 순차는 돈다, 병렬은 정적 그래프로 폴백
7. 웹발·채널발 심층분석 리포트가 각각 그 대화·그 채널로 **원장의 `report_markdown` 그대로** 도착하고, 같은 run 에 재개
   요청을 두 번 보내면 하나만 돈다

## 7. 테스트

### 7.1 계약 테스트 (단계 1, `runtime` 파라미터로 두 런타임)

- `execute_workflow` 결과 계약 — 성공 · 하네스 차단 · 오류 · 승인 대기의 키와 타입
- 진행 이벤트 — 같은 스텁 노드 위 `node_started` 순서와 걸음 수
- 승인 포트 — `interrupt_owner`·`decide` 반환, 남의 승인 거절, 같은 결정 두 번
- **LangGraph 쪽 알려진 결함은 `xfail(strict=True)`** — R1·R3·R4·R5. 단계 7 에서 파라미터째 지운다

### 7.2 단위

- 러너: 리듀서 셋 · 조건 분기 · 자기 반복 · `END` · 걸음 상한 · 승인 직전 중단 · 전체 `final_state` · `writes` 밖 키 거절 ·
  검증된 `final_response` 덮어쓰기 거절
- 코덱: `AgentState` 필드 타입을 훑어 전부 왕복 · 미등록 타입 실패 · `_` 키 제외
- 세션 저장소·작업 저장소: 메모리·Postgres 같은 계약 테스트(Q8 `AgentThreadStore` 계약 테스트와 같은 방식) — 버전 충돌 · 리셋 · 보존 정리
- 대화 기록: 키 없음 vs `[]` · 상한 · 대기·오류 턴 미기록 · Q8 끔↔켬 전환
- 승인 서비스: `decide`/`resume`/`expire` · 재개 중 재대기 · 만료 안내
- 작업 생명주기: 입구별 `start` · 자식이 부모 전달 대상을 물려받음 · 코딩 생성 훅 실패가 태스크 생성을 막지 않음
- 아웃박스: 워커는 적기만 · 재시도 · API 프로세스 송신
- 심층분석 lease: 동시 두 시작 중 하나만 · 살아 있는 run 재개 409 · 만료 lease 인수 · 갱신 실패 시 멈춤 · 멱등 키 ·
  `visibility_timeout > job_time_limit` 설정 검증

### 7.3 옮기는 테스트

- langgraph 를 import 하는 16개를 러너·배선 표 기준으로 다시 쓴다. 트랙 S 2턴 `MemorySaver` 테스트는 **단언은 그대로** 러너 +
  메모리 세션 저장소로 옮긴다
- 전후 테스트 이름 목록을 `--collect-only -qq` 로 비교하고, 빠진 이름은 이유와 함께 커밋 메시지에 적는다

### 7.4 가드

import 가드 · 토폴로지 동일성(단계 2) · 병렬 거절 · 단계 7 뒤 `langgraph` import 부재와 `pyproject.toml` 부재 · Q·Jev 테스트
디렉터리 변경 0줄(diff).

### 7.5 변이 검사

리듀서 무시 · 턴 리셋 제거 · `[]` 를 대체 대상으로 · 세션 버전 검사 제거 · 승인 중단을 노드 실행 뒤로 · `pending` 비우기 누락 ·
채널 재개 결과 버리기 · `writes` 검사 제거 · 검증된 결과 덮어쓰기 허용 · lease CAS 의 만료 조건 제거 · 자식의 전달 대상 상속 제거 —
각각 테스트가 실패해야 한다.

### 7.6 머지 전

DB 를 띄운 전체 스위트 · CI 의 Ruff 명령 그대로 · §6.2(단계 5).

## 8. 위험과 대응

| 위험 | 대응 |
|---|---|
| R5 수정(갱신분만 반환)이 노드가 기대던 암묵 상태를 깬다 | 단계 2 에서 LangGraph 어댑터 위에서 먼저 고치고 기존 스위트로 확인한 뒤 러너로 간다 |
| `writes` 검사가 `writes_hand_curated` 계약의 누락을 대량으로 드러낸다 | 단계 2 에서 development 예외로 먼저 켜고 목록을 고친다 — 낡은 면제는 가드를 끈다(메모리) |
| 상태 승계로 누적 필드가 커진다 | 상한 + 카운터, 기본값은 실측 |
| 검증된 작성자 규칙이 하네스 차단률을 바꾼다 | 심층분석 리포트만 해당. 채팅 하네스 지표의 경계로 로드맵 §8 에 먼저 적는다 |
| lease 가 정상 run 을 막는다(TTL 이 라운드보다 짧음) | TTL 은 라운드 최대 시간의 실측보다 크게, 갱신 실패는 경고 + 카운터 |
| 두 런타임 공존 기간의 분기 | 계약 테스트가 둘 다 돌고, 공존은 단계 3~6 으로 한정 |

## 9. 열어 둔 수치 (구현 계획에서 실측으로 정한다)

`workflow.session.max_carried_items` · `workflow.session.transcript_item_chars` · `deep_analysis.job_lease_seconds` ·
`visibility_timeout` 값.

## 10. 범위 밖

- **W2** 심층분석 루프 스킬 배선(`build_orchestrator` 에 `skill_registry` — 매니페스트 `skills` 가 바뀌므로 §8 표본 경계 먼저) + `CronSkill` 추상 메서드
- **W3** 데이터셋 — 스냅샷 auto-save 제거 · 메모리 레코드 상한 · `DatasetManager` 가 `RecordSink` 를 정본으로
- D4(LangChain 전송 전환) · 트랙 S P2 · 설계 그래프 병렬 실행 · HyperDeep·ROMA 를 검증된 작성자로 올리기

## 11. 로드맵 갱신 (단계 7 에서)

- §1 D 행 · §13 D: D3b 착지, D4 는 남는다. "D3b 는 D4 의 결과다" 문장은 취소선으로 남긴다
- §13 S: 런타임 불변식 다섯의 새 자리(1·2 → §4.3, 3 → §4.5 `start_at`, 4 → §4.1 `Branch`, 5 → §4.1 `topology_of`)
- §11: CH-HIST · CH-RESUME · S-ORCH(중복) · S-PEND(만료 리셋) · 예약 태스크 워커 전송 구멍을 지운다
- §8: 검증된 작성자 규칙이 만든 경계

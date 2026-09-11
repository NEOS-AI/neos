# Claude Code Loop → NEOS 갭 분석

기준: CC `v2.1.88` (`/Users/yeonwoosung/Desktop/claude-code-source-code-v2.1.88`), NEOS `neos/coding/` 실측.
`src/query/transitions.ts`, `src/types/message.ts`는 복원본에 없음 — Terminal/Continue 필드와 StreamEvent 스키마는 `query.ts` 사용처로만 재구성(타입 정의는 미확인).

작성: explore 서브에이전트 `Analyze CC agent loop` (2026-09-11). 메인 에이전트가 파일로 고정.

## 1. Claude Code 루프 아키텍처 요약

CC는 **프로세스 메모리 안의 무한 제너레이터**다. NEOS는 **체크포인트 단위로 iterator를 매번 재생성하는 durable step machine**이다. 개념은 이식하되 while(true)를 통째로 넣으면 lease/승인/재개 설계와 충돌한다.

```
QueryEngine.submitMessage()          # 세션 수명, SDK 이벤트 정규화
        │
        ▼
query() → queryLoop() while(true)    # src/query.ts
  [1] preprocess: applyToolResultBudget → snipCompactIfNeeded
      → microcompactMessages → applyCollapsesIfNeeded → autoCompactIfNeeded
  [2] yield stream_request_start
      deps.callModel = queryModelWithStreaming
      tool_use 블록이 오면 needsFollowUp=true
      StreamingToolExecutor.addTool (게이트 켜진 경우, 스트림 중 실행)
  [3] abort? synthetic tool_result + Terminal
      복구 가능 에러는 withhold 후 continue (413/max_output_tokens/media)
  [4] tool 없음:
        handleStopHooks → token budget nudge? → return Terminal
      tool 있음:
        runTools | getRemainingResults
        큐/attachment drain → maxTurns 검사 → State 갱신 → 다음 턴
        │
        ▼  (도구가 Agent/Task이면)
runAgent() → 다시 query()            # 별도 agentId, abort, 도구 풀
```

핵심 파일/심볼

| 층 | 파일 | 심볼 |
|---|---|---|
| 세션 래퍼 | `src/QueryEngine.ts` | `QueryEngine.submitMessage` |
| 턴 루프 | `src/query.ts` | `query`, `queryLoop`, `State`, `QueryParams` |
| DI | `src/query/deps.ts` | `QueryDeps`, `productionDeps` |
| 게이트 스냅샷 | `src/query/config.ts` | `buildQueryConfig` |
| 종료 훅 | `src/query/stopHooks.ts` | `handleStopHooks` |
| 턴 토큰 예산 | `src/query/tokenBudget.ts` | `checkTokenBudget` |
| 도구 배치 | `src/services/tools/toolOrchestration.ts` | `runTools`, `partitionToolCalls` |
| 스트림 중 실행 | `src/services/tools/StreamingToolExecutor.ts` | `StreamingToolExecutor` |
| 단건 파이프 | `src/services/tools/toolExecution.ts` | `runToolUse` |
| 권한 | `src/hooks/useCanUseTool.tsx` | `CanUseToolFn`, `hasPermissionsToUseTool` |
| 서브에이전트 | `src/tools/AgentTool/runAgent.ts` | `runAgent` → `query()` |
| 코디네이터 | `src/coordinator/coordinatorMode.ts` | `isCoordinatorMode`, `getCoordinatorUserContext` |
| 워커 스텁 | `src/coordinator/workerAgent.ts` | `getCoordinatorAgents` → `[]` |
| 브리지 | `src/bridge/sessionRunner.ts` | 자식 CLI spawn — 루프 핵심 아님 |

`queryLoop`의 `State`: `messages`, `toolUseContext`, `autoCompactTracking`, `maxOutputTokensRecoveryCount`, `hasAttemptedReactiveCompact`, `maxOutputTokensOverride`, `pendingToolUseSummary`, `stopHookActive`, `turnCount`, `transition`.

관측된 Terminal `reason`: `blocking_limit`, `image_error`, `model_error`, `aborted_streaming`, `prompt_too_long`, `completed`, `stop_hook_prevented`, `aborted_tools`, `hook_stopped`, `max_turns`.
Continue `reason`: `collapse_drain_retry`, `reactive_compact_retry`, `max_output_tokens_escalate`, `max_output_tokens_recovery`, `stop_hook_blocking`, `token_budget_continuation`, `next_turn`.

## 2. 루프 구성요소 카탈로그

| 구성요소 | CC 파일:심볼 | 동작 요약 | 왜 중요한가 |
|---|---|---|---|
| 턴 상태기계 | `query.ts`:`queryLoop` | while(true); 전처리→스트림→도구/복구→재귀 | 에이전트의 실제 심장 |
| tool_use 감지 | `query.ts` 스트림 루프 | `stop_reason` 무시, content의 `tool_use`가 유일한 follow-up 신호 | API 필드 불신뢰 |
| 스트림 중 도구 | `StreamingToolExecutor` | 블록 도착 즉시 큐; 동시안전만 병렬; 결과는 도착 순서 유지 | TTFT 이후 대기 감소 |
| 배치 도구 | `runTools`/`partitionToolCalls` | 연속 read-only는 최대 10 병렬; 그 외 순차 | 설계 문서와 동일 규칙 |
| 권한 인터럽트 | `runToolUse` + `CanUseToolFn` | PreToolUse → allow/deny/ask → 실행 → PostToolUse | 루프가 사용자 입력에서 멈춤 |
| 중단/합성 결과 | `yieldMissingToolResultBlocks` | abort·fallback·예외 시 모든 tool_use에 is_error tool_result | API 쌍 불일치 방지 |
| Auto/micro/snip compact | `autoCompactIfNeeded` 등 | 임계값 요약, 인라인 축소, 오래된 메시지 삭제 | 장시간 세션 |
| 413/미디어 복구 | `reactiveCompact` | 에러 withhold → collapse drain → reactive compact 1회 | 사망 나선 방지 |
| max_output_tokens | `isWithheldMaxOutputTokens` | 8k→64k 1회 후 메타 이어쓰기 최대 3 | 잘린 응답 복구 |
| Stop hooks | `handleStopHooks` | 차단 메시지 주입 후 재턴, 또는 preventContinuation | 검증·정책 |
| 턴 토큰 예산 | `checkTokenBudget` | 90% 미만이면 nudge; 3회+Δ<500이면 조기 종료 | 무한 작업 억제 |
| maxTurns | `query.ts` 재귀 직전 | attachment `max_turns_reached` 후 return | 하드 캡 |
| 미드루프 스티어링 | `messageQueueManager.getCommandsByMaxPriority` | 도구 후 prompt drain | follow-up을 다음 API에 합침 |
| abort | `toolUseContext.abortController` | 스트림/도구 두 지점 | Stop vs 새 제출 |
| 서브에이전트 | `runAgent` | 독립 `query()`, 도구/권한/abort 격리 | 위임 |
| 스트리밍 이벤트 | `query` yield 유니온 | stream_request_start, StreamEvent, Message, Tombstone | UI/SDK 계약 |

## 3. NEOS 현재 구현

`neos/workflow/`는 coding 루프에 재사용되지 않는다. 실제 연결은 Celery 앱뿐: `neos/coding/workers/celery_tasks.py`, `runtime.py`, `managed/workers.py` → `neos.workflow.celery_app.app`.

| 구성요소 | NEOS 파일:심볼 | 성숙도 | 근거 |
|---|---|---|---|
| 루프 프로토콜 | `loop/base.py`:`CodingLoop.run` | 있음 | 입력 `LoopInput`, 체크포인트, `LoopDependencies` |
| 1-step durable 루프 | `loop/anthropic.py`:`AnthropicCodingLoop.run` | 있음 | 호출당 모델 1턴 **또는** pending tool 1개 |
| 페이즈 페이크 루프 | `loop/fake.py`:`FakeDurableCodingLoop` | 있음 | UNDERSTAND→…→REVIEW. 테스트/기본 워커 경로 |
| 바깥 스케줄러 | `application/run_service.py`:`advance_one_safe_point` | 있음 | lease → steer → `loop.run` 재생성 → checkpoint에서 return |
| 워커 재시도 | `workers/execution.py`:`CodingTaskRunner` | 있음 | retryable `CodingLoopFailure` 백오프 |
| 모델 스트림 | `model/base.py` 이벤트 유니온 | 있음 | provider-neutral |
| 도구 레지스트리 | `tools/registry.py`:`CodingToolRegistry` | 있음 | read/search/git/write/execute. 병렬 API 없음 |
| 도구 실행 | `tools/executor.py`:`SandboxToolExecutor.execute` | 있음 | 단건, sandbox 세션 |
| 순차 멀티툴 | `AgentLoopState.pending_tool_calls` | 부분 | 여러 call 저장하나 워커 step당 1개 |
| 승인 | `domain/approvals.py`:`evaluate_approval` | 부분 | READ_ONLY만 자동허용. classifier/세션 규칙 없음 |
| 승인 내구성 | `run_repository.request_tool_approval` | 있음 | PENDING이면 이벤트 후 정지 |
| 스티어링 | `CodingRunService.steer` | 부분 | `INTERRUPT_NOW`는 스텁 (`process_stopped=True`) |
| compact | `AnthropicCodingLoop._compact` | 부분 | sha256 고지 + 해시 축약. LLM 요약 없음 |
| 토큰·비용 캡 | `_check_usage_budgets` | 부분 | 초과 시 fail-closed. nudge continue 없음 |
| 에러 복구 | `CodingLoopFailure` | 부분 | 413 withhold/max_tokens escalate 없음 |
| 훅 | — | 없음 | Pre/Post/Stop/Compact 훅 없음 |
| 서브에이전트 | — | 없음 | Phase 1 비목표 |
| 중단 합성 tool_result | — | 없음 | CancelledError는 래핑만 |

테스트 앵커: `tests/coding/loop/test_anthropic_loop.py`.

## 4. 갭과 병합 후보

### P0

**P0-1. 도구 배치 의미론 (병렬 read / 순차 mutate)**
- 가져올 것: `partitionToolCalls` + `isConcurrencySafe`. 연속 READ_ONLY는 한 safe-point에서 gather.
- 붙일 곳: `neos/coding/tools/orchestrator.py`, `_advance_one_tool`을 배치 단위로.
- 작업량 M. 리스크: write/execute 병렬 시 `tool_outcome_unknown` 폭증.

**P0-2. 미완료 tool_use의 합성 결과**
- 가져올 것: `yieldMissingToolResultBlocks`.
- 붙일 곳: `anthropic.py` 취소·실패 경로, `CodingRunService` interrupt 커밋.
- 작업량 S. 리스크: 합성 결과 없이 resume하면 다음 모델 요청이 깨짐.

**P0-3. 의미 있는 compact (해시 드롭 대체)**
- 가져올 것: 오래된 tool_result 축약 + 임계값 근접 시 요약 턴 + 활성 tool 쌍 유지.
- 붙일 곳: `neos/coding/loop/compact.py`.
- 작업량 L. 리스크: 요약이 tool_id 쌍을 깨뜨림.

**P0-4. 실제 abort / Stop**
- 가져올 것: 루프 스코프 cancellation을 모델 스트림과 도구에 연결.
- 붙일 곳: `InProcessRunInterrupter`를 워커 task 취소로 교체.
- 작업량 M.

### P1

- **P1-1** 권한 파이프라인 allow/deny/ask + 세션 규칙. 작업량 M.
- **P1-2** prompt-too-long → compact 후 재시도, max_output_tokens escalate. 작업량 M.
- **P1-3** 훅 포트 (Pre/Post/Stop/Compact). 구현은 no-op부터. 작업량 M.
- **P1-4** 스티어링을 다음 API user 메시지로. `pending_instruction` 실루프 소비. 작업량 S.
- **P1-5** 스트림 중 READ_ONLY 실행. 작업량 L.

### P2

- **P2-1** 서브에이전트 `spawn_agent.v1` + 별도 task/run. 작업량 L.
- **P2-2** tool result artifact ref + 턴 토큰 nudge. 작업량 M.
- **P2-3** QueryEngine급 세션 래퍼 — `run_service.py`가 이미 담당. 별도 클래스 불필요.

## 5. 권장 구현 순서

1. 합성 tool_result + 실제 cancel
2. 배치 실행 (read 병렬, mutate 순차)
3. instruction/steer를 실루프 transcript에 결합
4. 계층 compact
5. 모델 복구 + 훅 포트
6. (후속) spawn_agent + 결과 예산

## 6. 가져오면 안 되는 것

- TUI/Ink/React 훅, Permission dialog
- Anthropic 전용 락인 (thinking signature strip, `USER_TYPE==='ant'`, Statsig)
- 복원 소스 복붙
- `sessionRunner` / bridge 자식 CLI
- coordinator/team 도구 세트 (Phase 1 비목표)
- feature-gated 실험 전체를 한 번에
- `chat_stream_pipeline` / LangGraph를 coding loop로 승격

## 7. 근거 파일 목록

Claude Code: `src/query.ts`, `src/query/deps.ts`, `src/query/config.ts`, `src/query/stopHooks.ts`, `src/query/tokenBudget.ts`, `src/QueryEngine.ts`, `src/services/tools/toolOrchestration.ts`, `src/services/tools/StreamingToolExecutor.ts`, `src/services/tools/toolExecution.ts`, `src/services/compact/autoCompact.ts`, `src/utils/toolResultStorage.ts`, `src/utils/hooks.ts`, `src/hooks/useCanUseTool.tsx`, `src/tools/AgentTool/runAgent.ts`, `src/coordinator/coordinatorMode.ts`.

NEOS: `neos/coding/loop/{base,anthropic,fake}.py`, `application/run_service.py`, `workers/execution.py`, `runtime.py`, `model/base.py`, `tools/{registry,executor}.py`, `domain/{approvals,events,phases}.py`, `tests/coding/loop/test_anthropic_loop.py`, `docs/NEOS_CODING.md`.

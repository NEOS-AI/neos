# NEOS 모멘텀 분석: 코딩 에이전트 루프 중심 AGI 비전에 비춘 현재 상태와 로드맵 (2026-09-28)

> **범위.** `dev` HEAD `403aeb77`을 읽기 전용으로 분석했다. 서브에이전트 다섯 개가 병렬로 맡았다.
> (① 로드맵 정렬 ② 딥 하네스 루프·JEV ③ 코딩 에이전트 루프 ④ 자기개선·진화 ⑤ 싱글턴·동시성·격리·서비스 방향)
> 이 문서는 그 다섯 보고서를 종합하고 교차 검증한 결과다.
>
> **검증 표기.** ✔는 종합 단계나 검수 단계에서 코드를 직접 다시 열어 확인한 주장이다. 표기가 없으면 서브에이전트가 file:line 근거와 함께 보고한 주장이다. ⚠는 런타임에서 재현하지 않은 추론이다. 검증한 내용 전체는 §9.2 검증 로그에 있다.
>
> **개정 이력.** v1.2 (2026-09-28) GEPA 항목을 설계 의도와 결함으로 나눴다(§4.3, §9.1). Redis 브로커 재확인. 로드맵, GEPA, MICROSERVICE 문서에 반영한 위치를 §9.3에 적었다. v1.0 (2026-09-28) 초판. v1.1 (2026-09-28 검수) 주요 주장을 코드로 재검증했다. 샌드박스 기본값과 비용 귀속 서술을 정정하고, 근거 없는 최상급 표현과 일정 추정을 삭제했다. 비전 자체에 대한 반대 검토(§6.6), 진척 지표(§8.5), 결정 필요 사항(§8.6), 검증 로그(§9.2), 의존 순서(§8 서두)를 추가했다.
>
> **기준 문서.** `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md`(정본 로드맵, 이하 "로드맵"), `docs/AGENT_RECIPE_DISTILLATION_260927.md`, `docs/GEPA_SELF_IMPROVEMENT_MIGRATION.md`, `docs/MICROSERVICE_REVIEW_260927.md`, `docs/DEEP_ANALYSIS_CODE_RESEARCH_CONTRACT.md`.

---

## 0. 한 페이지 결론

### 0.1 평가 대상 비전

> 코딩 에이전트 루프가 문제 해결용 코드를 짜고 실행한다. 루프 안에서는 JEV로 분기 판단, LLM-as-Judge, 도구 위험 검증을 효율적으로 한다. 이 위에 자기 보완·진화형 멀티에이전트 루프를 올린다. 그리고 "System distillation is the moat": 루프가 얻은 교훈을 버전 관리되는 모델 비종속 Agent Recipe로 증류한다.

### 0.2 판정

**방향은 맞다. 다만 브레이크만 달렸고 핸들과 엔진이 연결되지 않았다.**

| 층 | 비유 | 상태 |
|---|---|---|
| 안전·검증 규율 (도구 위험 단조 축소, 결정론 채점, 재실행, 원장, 사전 등록 표본) | 브레이크 | **저장소에서 가장 성숙한 층.** 비전보다 앞서 있다 (설계 기준이고, 대부분 기본 off다) |
| 내구성 실행 기반 (1-step durable loop, CAS lease, outbox, 멱등 claim) | 섀시 | **완성도 높음.** 장시간 자율 루프의 바닥으로 충분하다 |
| 코딩 루프가 실제로 코드를 짜고 돌려서 문제를 푸는 것 | 엔진 | **DA 경로에서 배선이 끊겼다.** 조사 자식에 `execute.v1`이 없다 ✔ |
| JEV 기반 분기, LLM-as-Judge 결과 판정 | 핸들, 계기판 | **없다.** JEV는 도구 위험 필터로만 쓰이고, VERIFY verdict는 아무도 읽지 않는다 ✔ |
| 자기개선·진화 (GEPA, lesson, recipe) | 변속기 | **부품은 있지만 닫힌 루프가 0개다.** evaluator 0개, 승인 호출자 0개 |
| 멀티에이전트 | 대열 | **깊이 1 위임 트리다.** 쓰기 child는 게이트 밖에 있다 ✔ |
| 서비스 (싱글턴, 동시성, 테넌트) | 도로 | 코딩 루프 싱글턴은 **안전하다.** DA lease 부재와 테넌트 격리 0이 **High 위험**이다 |

### 0.3 가장 중요한 다섯 가지 발견

1. **DA 조사 워커가 "코딩 루프"인데 코드를 실행하지 못한다** ✔
   - `ResearchToolPort.definitions()`가 내놓는 도구는 `fetch.v1`, `submit.v1`, `check_claims.v1`뿐이다(`neos/workflow/deep_analysis/research_tools.py:159-164`).
   - `ChildStepper`는 포트와 스펙의 교집합만 모델에 보여 준다. 그래서 스펙이 허용한 `execute.v1`, `read_file.v1`이 사라진다. 샌드박스는 열리지만 쓰이지 않는다.
   - 그 결과 computed claim 재실행 채점(`SandboxReexecutor`)은 도달할 수 없는 코드가 된다.
   - 트랙 J(J1~J3 착지)의 핵심 가치가 배선 한 줄 때문에 막혀 있다.
2. **검증 결과가 분기를 구동하지 않는다** ✔
   - 코딩 루프의 `VERDICT: PASS|FAIL|PARTIAL`은 `state.verdict`에 저장되지만, 읽는 곳은 codec 직렬화뿐이다(`neos/coding/loop/_durable/model_turn.py:524`, `codec.py:346,402`).
   - DA의 질문 신뢰도는 `max(conf, worker.self_assessment)`, 즉 행위자의 자기 평가로 움직인다.
   - "쓰고, 돌리고, 판정하고, 갈라진다"는 비전의 핵심 고리가 끊겨 있다.
3. **JEV는 브레이크로만 쓰인다**
   - 유일한 운영 소비처는 코딩 루프의 도구 위험 게이트다. 여기서도 기본값은 off다.
   - `jev.judge_shadow_enabled`는 소비처가 없는 플래그다 ✔(`schema.py` 밖 참조 0건).
   - DA에는 JEV 배선이 0이다 ✔(`neos/workflow`에서 `jev` grep 0건). DECISIONS에서 의도적으로 제외했다.
   - 로드맵에서 분기 판단은 L7, 즉 마지막 단계의 "후보 목록"에만 올라 있다.
4. **implement child의 도구 호출이 parent 게이트를 우회한다** ✔
   - `CodingToolPort.execute`는 스펙 allowlist만 확인하고 executor를 직접 부른다(`neos/coding/subagent_port.py:53-72`). approval, JEV, hook을 거치지 않는다.
   - Docker·managed 세션에는 `clone_with_workspace`가 없다. 그래서 쓰기 child는 격리 없는 memory 샌드박스에서만 돈다.
5. **자기개선 루프가 하나도 닫혀 있지 않고, 정본 로드맵은 GEPA의 존재를 모른다**
   - GEPA 커널은 커밋 5개로 착지했다. 하지만 등록된 evaluator, run 생성 호출자, `approve` 호출자가 모두 0이다 ✔(`neos/` 안에서 `register_evaluator`, `insert_run_with_seed`, `.approve(`, `submit_gepa_opt_job` 호출 0건).
   - held-out test 점수가 seed보다 낮아도 staged로 올라간다 ✔(`engine.py` `_succeed`는 test_mean을 기록만 하고 무조건 `status: "staged"`).
   - 로드맵 본문에서 "GEPA"를 grep하면 0건이다 ✔.

### 0.4 싱글턴 질문에 대한 답

- **코딩 루프 싱글턴(`coding_runtime`)은 동시성과 격리 문제를 만들지 않는다.** 루프 객체는 불변 의존성만 들고 있다. 런 상태는 매 호출 체크포인트에서 복원한다. lease가 없으면 실행을 거절한다. Celery 워커는 전달마다 루프를 새로 만든다.
- **DA 오케스트레이터는 런마다 새로 만들고, 예산은 `ContextVar`로 격리한다.**
- **진짜 문제는 싱글턴 주변의 프로세스 전역 가변 상태다.**
  - lesson 세션 팩토리 전역 토글 ✔
  - 전역 `db_manager`와 `LLMFactory` 캐시가 `asyncio.run` 루프를 넘나든다 ⚠
- **DA에는 lease가 없다.** 그래서 resume API나 Celery 재전달로 같은 run이 동시에 두 번 돌 수 있다 ✔

### 0.5 권고의 척추: 이미 있는 부품 세 개를 잇는 배선

1. **포트 합성:** DA 조사 자식에 게이트된 `CodingToolPort`를 합성하고 스크립트를 원장에 커밋한다. 엔진이 연결된다.
2. **verdict 기반 분기:** 결정론 검증(테스트 exit code, 재실행 digest)의 결과가 재진입, 에스컬레이션, 후보 선택을 구동하게 한다. 핸들이 연결된다.
3. **evaluator 등록:** 같은 결정론 검증기를 GEPA fitness로 등록하고 held-out 회귀 게이트를 건다. 변속기가 연결된다.

순서의 전제가 하나 있다. 1번에서 `execute.v1`을 열기 **전에** child 도구 게이트(P0-2)를 먼저 닫아야 한다(§8 의존 순서).

이 셋은 같은 추상화, 즉 **"재실행 가능한 결정론 검증기"**를 세 곳에서 쓰는 일이다. 새 개념을 발명할 필요가 없다. 로드맵이 이미 세운 `DeterministicGrader`와 `ComputedEvidence` 재실행 계약을 코딩 루프와 진화 루프로 일반화하면 된다.

---

## 1. 비전 대비 정렬 스코어카드

로드맵(설계)과 코드(실제)를 나눠 평가했다.

| 비전 요소 | 로드맵(설계) | 코드(실제) | 핵심 근거 |
|---|---|---|---|
| ① 코딩 루프 = 1차 문제 해결자 | 부분 정렬. 북극성은 "검증형 분석"이고, J는 DA 조사로 한정된다 | **공백.** DA 경로에서 코드 실행 불가. 범용 코딩 루프에는 결과 라벨이 없다 | 로드맵 §3.1, §4. `research_tools.py:159-164` ✔ |
| ② JEV 분기 판단 | 공백. L7 후보 목록뿐이고, §9는 라우팅 사용을 금지한다 | **공백** | 로드맵 §12.5 L831, §12.6 |
| ③ LLM-as-Judge | 부분 정렬. L4~L6 설계. 원장 소실로 L4를 측정할 수 없다 | 부분. `AgenticGrader`는 이진 라벨, 판정자는 행위자보다 약한 동일 계열, entailment는 자기 검증 | 로드맵 §12.11 ④. `graders/agentic.py`, `model_roles.py` |
| ④ 도구 위험 검증 | **강하게 정렬.** 단조 축소, D-L1~L3 | **강함(설계).** 기본 off. K9 unattended 신호가 전달되지 않는다. child가 우회한다 | `jev/gate.py`, `banding.py`. `subagent_port.py:53-72` ✔ |
| ⑤ 자기개선 | 공백. F는 닫힘, D19는 auto-mutation 금지, GEPA 미기재 | 부품만 있음. 닫힌 루프 0 | `gepa_opt/*`. `learn/*` |
| ⑥ 진화 | 공백. §6.3이 런타임 타입 발명을 거부한다 | GEPA Pareto 커널 있음. 운영 호출 0 | `gepa_opt/pareto.py`, `engine.py` |
| ⑦ 멀티에이전트 | 부분 정렬. 계층형이고 협업·경쟁 구조가 없다 | 깊이 1 위임 트리. 활성 child 1~4 | `subagent/catalog.py:401-405`. `children.py:28-29` |
| ⑧ 레시피 증류 | 철학은 정렬(§6.2 베팅 5). 단위와 경로는 없다 | 6개 범주 중 부분 동작 2개(수동), 없음 4개 | 4.4절 |

**총평.**
- 로드맵은 **검증 규율에서는 비전보다 앞서 있다.** 반면 **분기, 진화, 증류는 비어 있다.**
- 코드는 로드맵보다 한 발 더 끊겨 있다. 착지한 부품끼리 서로를 부르지 않는다. 로드맵 §14가 스스로 경계한 "무는지 보지 않은 게이트"가 여러 곳에서 재현됐다.

---

## 2. 딥 하네스(Deep Analysis) 루프 분석

### 2.1 실제 제어 흐름

```
jobs.execute_run (jobs.py:205)
  └─ service.build_orchestrator
       ├─ DeterministicGrader (+SandboxReexecutor: code_research일 때만)
       ├─ AgenticGrader(judge=everyday) / ReportGrader
       └─ research_runtime_factory (sandbox_provider 있을 때만)
  └─ Orchestrator.run
       ├─ _decompose (dig 모델)
       └─ while not budgeter.should_stop():
            _run_round
             ├─ budgeter.select: score = value×(1−conf)×gain_decay + aging
             │    SPLIT(fail_streak≥2 | cap) / DIG(conf<0.3) / SCOUT
             ├─ build_assignment: 거절 피드백 → REPAIR_PRESCRIPTIONS
             ├─ asyncio.gather(_run_worker)
             │    ├─ [code_research_enabled] run_research_worker
             │    │     샌드박스 열기 → SubagentRuntime.advance (1 step)
             │    │     포트 = {fetch, submit, check_claims}   ← execute·read_file 없음 ✔
             │    ├─ [subagent_enabled] investigate_via_subagent(explore)
             │    └─ [기본] 레거시 Worker: 검색→fetch→LLM 추출→entailment(행위자 모델)
             ├─ 순차 커밋(단일 기록자): Deterministic → Agentic 채점
             │    computed: 원장 blob → 전제 → 2회 재실행 → digest 비교 (도달 불가)
             ├─ _apply_repairs → _regrade_pending
             ├─ question.confidence = max(conf, self_assessment)   ← 행위자 자기 평가
             └─ stall 밸브, 하위질문 채택
       └─ _finalize: reduce → conflict(최대 1회 재조사) → assemble
                    → ReportGrader(결정론 인용 게이트 → judge) → revision 1회
```

### 2.2 강점 (유지할 것)

- 단일 기록자 원장, 조용한 degrade 금지, manifest·digest 기반 재현성, 사전 등록된 측정 규율(discard recall의 Wilson 상한 정지 규칙).
- **결정론 우선 검증.** quote 매칭, 원장 blob, computed 2회 재실행. `DeterministicGrader`가 출처를 보지 않는 비대칭(로드맵 §2.2)은 진화 루프의 fitness로 그대로 쓸 수 있는 자산이다.
- 토큰 예산을 계층으로 나눠 finalization을 보호한다.

### 2.3 결함

| # | 결함 | 영향 | 근거 |
|---|---|---|---|
| D1 | 조사 자식에게 코드 실행 도구가 없다. `fetch.v1` 설명은 "`read_file.v1`로 읽어라"라고 하는데 그 도구가 없다 | 트랙 J의 존재 이유가 무력화된다. computed 경로에 도달할 수 없다 | `research_tools.py:48,159-174` ✔, `research_session.py` ✔ |
| D2 | 스크립트를 원장 blob으로 커밋하는 경로가 없다 | computed claim이 `E_COMPUTE_INPUT_UNFETCHED`로 막힌다 | `graders/computed.py` |
| D3 | 티켓 `goal = question_text or brief`이므로 repairs, dead_ends, 확정 발견이 조사 자식에게 가지 않는다 | 수선 되먹임이 레거시 워커에서만 작동한다 | `subagent_adapter.py:147` |
| D4 | 분기의 입력이 행위자의 `self_assessment`다. 판정은 이진 라벨이다 | budgeter가 보정되지 않은 신호로 예산을 배분한다 | `ledger.py:969` |
| D5 | `AgenticGrader`의 필수 심사 여부가 행위자가 보고한 confidence로 정해진다 | 낮게 보고하면 심사를 70% 확률로 피한다. reward hacking 표면이다 | `schema.py:977-978` |
| D6 | computed claim이 `evidence=[]`로 agentic 단계에 들어간다 | 재실행을 통과해도 UNRELATED로 떨어질 수 있다(잠재 버그) | `submission.py:118-126`, `agentic.py:109` |
| D7 | judge는 행위자보다 약한 동일 계열 모델이다. entailment는 행위자 자신의 모델이다 | 상관된 오류가 생기고 자기 검증이 된다 | `model_roles.py`, `worker.py:_refine_claims` |
| D8 | 판정·수선 체계가 세 벌이다. DA `REPAIR_PRESCRIPTIONS`, `workflow/harness` check→repair 정적 매핑, 코딩 루프 게이트 | 레시피 증류의 원천이 흩어진다 | `workflow/harness/repair.py` |

---

## 3. 코딩 에이전트 루프 분석

### 3.1 아키텍처

```
Celery/worker  while keep_running()
  └─ RunService.advance_one_safe_point ── lease(CAS expected_checkpoint_id)
       ├─ on_safe_point (steer / interrupt / cancel)
       └─ DurableCodingLoop.run  (한 번 배달 = 한 걸음, 루프 안에 while 없음)
            ├─ pending tool → 게이트 체인
            │    stall → phase/skill/schema → pre_tool hook(Null)
            │    → approval(R₀ 정적 → JEV 밴딩(좁히기만) → unattended 접기)
            │    → claim(멱등) → execute(sandbox) → settle
            └─ model turn: system = static + Lessons(≤5) + summary + GEPA overlay
       └─ commit checkpoint + outbox INSERT (같은 트랜잭션) → dispatcher → Redis/SSE
```

**평가: 장시간 자율 루프의 바닥으로 충분히 성숙하다.** 크래시, 재전달, 워커 교체를 모두 설계 단계에서 다뤘다.
- 크래시 안전성이 있다. 쓰기 도구는 RECLAIMED 상태면 재실행하지 않고 `tool_outcome_unknown`으로 둔다.
- 예산 상한은 turns 40, tools 100, 연속 오류 5, 토큰 100만, 비용 상한이다.
- phase(EXPLORE, PLAN, IMPLEMENT, VERIFY)별로 쓰기 도구를 숨긴다.

### 3.2 도구 위험 검증

- **구조.** 정적 R₀(fail-closed)가 먼저다. 그 위에 JEV 확률 밴딩이 "좁히는 방향으로만" 얹힌다(`narrow = max(R₀, band_floor)`). 그다음이 unattended 접기(REQUIRE_APPROVAL → DENY)다.
- **fail 모드.**
  - 정적 평가기 예외, hook 타임아웃: DENY.
  - JEV 오류: R₀로 폴백.
  - WAF 403: MID로 좁힌다. 게이트를 끄는 공격을 막는 장치다.
  - JEV를 켰는데 설정이 틀리면 기동이 실패한다.
- **비용 문제.**
  - R₀=ALLOW인 `read_file`에도 매번 JEV를 호출한다. 타임아웃은 5초다.
  - shadow 모드도 인라인 await다.
  - enforce 모드에서는 read-only 배치와 speculative prefetch가 꺼진다.
  - 결과적으로 턴 지연이 N × RTT가 된다.
  - 운영 캐시는 없다. uid 난수로 캐시를 의도적으로 무력화한다. 일관성 측정 용도로는 맞지만 운영에서는 낭비다.
- **판단 맥락의 부재.** `jev_state`는 도구 이름과 입력만 보낸다. "이 호출이 과제 목표에 비추어 적절한가"는 판정할 수 없다.
- **K9.** `approval_unattended` 신호가 `runtime.py`에서 전달되지 않는다. 그래서 unattended DENY 접기가 운영에서 한 번도 실행되지 않았다(로드맵 L682).

### 3.3 실행 격리

- **Docker:** `--network none` 강제, 생성 뒤 inspect로 재확인, uid 10001, cap-drop ALL, read-only, digest 고정 이미지.
- **Managed(E2B/Modal):** deny 기본. capability 협상이 정확히 일치하지 않으면 생성 전에 거절한다. 폴백은 없다.
- **Memory(local):** host subprocess에서 돈다. env allowlist만 있고 네트워크와 FS 격리가 없다. 기본값은 `sandbox.enabled: false`, `provider: memory`다 ✔(`config/neos.default.yaml:540-542`). production·staging yaml에는 `sandbox` 섹션이 없다 ✔. 그래서 누군가 `enabled`만 켜면 격리 없는 memory provider로 돈다. 이를 거부하는 검증이 없다(5.3절).
- **Worktree:** implement child는 host git worktree를 쓰고 ff-only로 병합한다. 세션 복제는 `MemorySandboxSession`만 특별 처리하고, 다른 세션은 `clone_with_workspace` 메서드를 찾는다. 그런데 이 메서드를 구현한 클래스가 저장소에 없다 ✔(`loop/_durable/worktree.py:24-37`). 그래서 Docker·managed에서는 `worktree_session_not_cloneable`로 실패한다.

### 3.4 멀티에이전트

- parent가 중재하는 모드가 두 가지다. park와 detached(K3, 기본 off)다. mailbox와 coordinator는 로드맵 §2.3에서 의도적으로 금지했다.
- 재귀 spawn 깊이는 0이다. nested spawn은 explore만, 깊이 1로 제한된다.
- **평가.** 진짜 멀티에이전트라기보다 **깊이 1 위임 트리**다. child 간 통신, 비평자, 경쟁 후보가 없다.
- **보안 구멍** ✔. implement child는 `execute.v1`, `rm.v1`을 쓸 수 있다. 그런데 도구 호출이 parent의 approval, JEV, hook을 모두 우회한다. 게이트를 받는 것은 `spawn_agent(spec=implement)` 호출 한 번뿐이다.

### 3.5 자기 검증과 학습

- VERIFY phase는 VERDICT를 강제하고, PASS에는 실행 명령을 요구한다. **하지만 verdict를 아무도 읽지 않는다** ✔. FAIL이 나와도 재시도, 재계획, 에스컬레이션으로 이어지지 않는다.
- 재시도는 형식적인 것만 있다. 빈 응답 1회, stop hook 2회(hook은 Null), stall deny 3회.
- **unattended와 코드 실행이 충돌한다.** `execute.v1`은 COMMAND 위험이다. 그래서 unattended에서는 DENY된다. "코드를 돌려서 푸는" 자율 루프가 기본 설정에서는 막혀 있다.
- lesson은 실패한 run에서만 만들어진다. 내용은 `"Coding run X ended failed. Signals: …"`라는 기계적 문자열이다. 성공 궤적에서는 아무것도 배우지 않는다.

---

## 4. 자기개선·진화 루프 분석

### 4.1 장치 목록 요약

| 장치 | 산출물 | 게이트 | 루프가 닫혔는가 |
|---|---|---|---|
| GEPA opt | coding system prompt overlay | 3건 미니배치 strict-sum, val 평균, 사람 승인 | ✘. evaluator 0, run 생성 0, `approve` 호출 0 |
| 코딩 lesson | 실패 신호 문자열 | staged 강제 | ✘. 승인 경로 없음 |
| 리서치 procedure, LTM 피드백 | lesson, LTM | staged | ✘ |
| 채널 `/learn` | fact | `write_approval=False`일 때만 즉시 승인 | △. 사실상 유일한 승인 경로 |
| Curator | archive | 결정 규칙 | 정리만 한다 |
| **Ralph ImprovementTracker** | 개선 유형 효과 통계 → 우선순위 변경 | **없음** | **유일하게 자동으로 닫혔다.** 검증, 버전, 테넌트 구분이 없다. 로컬 JSON이다 |
| DA golden gate / D19 | 사람이 쓰는 프롬프트 변경 | replay 결정성, PR 리뷰 | 수동 |
| Harness calibration | 임계값 권고 | 일치율 규칙 | ✘. "Latest Run" 섹션이 비어 있다 |

### 4.2 루프가 끊긴 지점 (GEPA 기준)

```
신호 ──✘──▶ 데이터셋 ──✘──▶ 평가(evaluator 0) ──✘──▶ 승격(approve 호출자 0)
                                                          │
 새 신호 ◀──✘── (overlay id가 run에 기록되지 않음) ◀── 배포 ✔(model_turn.py:193, 플래그 off)
```

### 4.3 GEPA 구현상의 문제

> v1.2 정정: 초판은 아래를 모두 "버그"로 묶었다. 그런데 GEPA 설계 문서(Risks, Loop pins, Key Decisions)를 대조해 보니 절반은 **설계가 의도적으로 고른 동작**이었다. 둘을 나눈다. 같은 내용을 GEPA 문서의 "Post-landing review (2026-09-28)"에도 적었다.

**설계와 어긋나는 것 (고친다)**
- **RNG.** 부모 선택이 iteration마다 `random.Random(0)`을 새로 만든다 ✔(`engine.py:201`). 설계는 "engine is pure given a clock/rng"인데 rng를 넘기지 않는다. 미니배치 셔플이 `Random(0)`으로 고정된 것은 설계대로다(Loop pins).
- **reflector 주입 경로.** `system=curr_param`이다 ✔(`provider.py:26`). 최적화 대상 텍스트가 reflector의 system 지시가 되므로, 후보가 reflector를 조종할 수 있다. upstream은 메타 프롬프트를 user 턴으로만 보낸다.
- **`approve`가 archive할 때 surface로 필터하지 않는다** ✔(`store.py:638-647`). 지금은 surface가 `coding_overlay` 하나뿐이라 잠재 결함이다.
- **금지 토큰 검사.** `inspect.getsource` 문자열 매칭이라 사실상 장식이다.

**설계가 고른 것 (다시 열지 결정한다)**
- **held-out 회귀 게이트가 없다** ✔. 설계는 선택 편향을 이유로 "test_mean으로 고르지 않는다"고 정했다. 이것은 옳다. 하지만 **게이트**는 고르는 것과 다른 규칙이다. best가 seed보다 나쁘거나 seed 자신이면 staged하지 않는 규칙을 둘 수 있다. 지금은 회귀를 막는 것이 승인자 한 명뿐이다.
- **side_info가 8KB를 넘으면 전부 버린다** ✔. 8192는 설계가 정한 숫자다. 문제는 한도가 아니라 **통째로 버리는 방식**이다. 코딩 trace는 거의 항상 넘으므로 reflection이 받는 피드백이 사라진다. 필드별 truncate로 한도와 신호를 둘 다 지킬 수 있다.
- **evaluator 동기 호출.** 설계가 "The evaluator stays sync"로 정했다. async인 코딩 fixture를 첫 evaluator로 쓰려면 이 결정을 바꿔야 한다.
- **예제당 1회 평가, 3건 strict-sum.** 설계가 N=1 위험을 인정하고 "반복 횟수를 지어내지 않는다"고 했다. 결정론 채점기라면 문제가 없다. LLM 채점기를 쓰는 순간 노이즈에 매우 약해진다.
- **fitness 정책 충돌.** GEPA 설계 문서는 JEV와 verdict를 fitness에서 명시적으로 배제한다. 그런데 사용자 비전은 JEV를 judge로 쓰는 진화 루프다. 로드맵 §11 "사람의 결정" ②에 올렸다(해법 제안은 6.2절).

### 4.4 레시피 6범주 커버리지

| 범주 | 현황 |
|---|---|
| 실패 패턴 → judges/evals | 부분. golden gate와 calibration 도구는 수동. 실패 사례를 eval case로 캡처하는 경로가 없다 |
| 반복 행동 → prompts/skills | 없음. GEPA overlay는 운영하지 않는다. 스킬 자동 생성과 진화가 없다 |
| 사용자 불만 → memories | staged까지만. 취소와 재생성 신호는 기록하지 않는다 |
| 에이전트 고전 → tooling/docs | 코드에는 없다. 로드맵 §10과 §14에서 **사람이 손으로 증류하고 있다** |
| 프런티어 성능 → golden trajectories | 없음. transcript에 모델 출처가 기록되지 않는다 |
| 높은 비용 → routing | 없음. 키워드 기반 정적 라우팅이고, 비용과 품질을 조인하지 않는다 |

### 4.5 모델 비종속성

- **형식은 비종속이다.** 순수 텍스트이고, 공급자 중립 `ModelRequest`를 쓴다.
- **검증은 모델에 종속되는데, 그 사실이 기록되지 않는다.**
  - gepa 테이블에 target model, provider, base prompt hash 컬럼이 없다.
  - reflector 모델이 저장되지 않는다.
  - base prompt가 바뀌어도 overlay를 무효화하지 않는다.
- **모델을 교체할 때 기존 자산이 유효한지 판단할 근거가 없다.** "모델 세대가 바뀌어도 버티는 하네스"(로드맵 §6)라는 목표와 정면으로 충돌한다.

---

## 5. 싱글턴·동시성·격리·서비스 방향

### 5.1 싱글턴 판정

| 대상 | 형태 | 판정 |
|---|---|---|
| `coding_runtime`, `DurableCodingLoop` | 모듈 import 시점 싱글턴(`runtime.py:886`) | **안전.** 불변 의존성, 체크포인트 복원, lease 필수. Celery에서는 전달마다 새로 만든다 |
| DA `Orchestrator` | 런마다 생성 | 안전. 예산은 `ContextVar` + `asyncio.Lock` |
| `@lru_cache`(manifest, prompt_loader, rubric) | 불변 파일 캐시 | 안전 |
| **lesson 세션 팩토리 토글** ✔ | 프로세스 전역 `_USE_MEMORY_ONLY` | **위험.** 코딩 전달이 끝나며 `None`을 set하면, 같은 워커의 이후 DA와 gepa 태스크가 lesson과 overlay를 조용히 읽지 못한다 |
| **전역 `db_manager`, `LLMFactory._llm_cache`** ⚠ | `asyncio.run`마다 새 루프가 생기는데 풀과 클라이언트는 재사용된다 | **위험(미재현).** 코딩 워커는 전달마다 새로 만들어 이 문제를 피했다. DA와 gepa 태스크는 피하지 않았다 |
| import 시점 개발 런타임 생성 | 워커에서 sandbox provider를 누수시킨다 | Low |
| GEPA evaluator 레지스트리 | 프로세스 로컬 dict | API에서 등록한 것이 워커에서 보이지 않는다(fail-closed) |
| `ModelConfig` 핫 리로드 | 전역 | 런 도중 가격이나 창 크기가 바뀔 수 있다. 재현성이 깨진다 |

**결론.** "루프가 싱글턴이라서" 생기는 동시성·격리 문제는 없다. 로드맵 §10.3의 앰비언트 오염 사고 여섯 건과 같은 뿌리를 가진 문제가 운영 경로에 남아 있을 뿐이다. 그 뿌리는 **런 컨텍스트를 명시 객체가 아니라 모듈 전역으로 전달하는 것**이다.

### 5.2 동시성

- **코딩:** lease, 펜싱 토큰, heartbeat, CAS, outbox SKIP LOCKED, reconcile로 해결했다.
- **DA: lease가 없다** ✔
  1. `POST /deep-analysis/{id}/resume`은 status만 확인하고 다시 디스패치한다(`deep_analysis_handlers.py:231-238`). 살아 있는 run에 부르면 두 번째 실행자가 뜬다. 그 실행자의 `ledger.recover()`는 `investigating` 상태 질문을 `open`으로 되돌린다. 결과는 이중 지출과 작성자 두 명이다.
  2. DA `time_limit=3900s`, `acks_late=True`인데, Redis 브로커의 `visibility_timeout`을 설정한 곳이 저장소에 0건이다 ✔. Kombu 기본값은 1시간이다. 따라서 1시간이 넘는 run은 원래 워커가 살아 있는데도 재전달된다.
  3. enterprise compose의 Redis는 `allkeys-lru`이고 캐시와 브로커를 같이 쓴다. 대기 중인 태스크가 축출될 수 있다.
- **인라인 DA(기본값):** 동시성 상한, 사용자별 쿼터, 취소, orphan reaper가 없다.

### 5.3 격리(멀티테넌트)

- **테넌트.** `organizations` 테이블은 있지만 데이터 접근 경로 격리는 0이다(DIRECTION_260717). 격리가 모두 `owner`(user) 단위에서 끝난다.
- **GEPA overlay는 전역이 아니다.** owner와 surface 단위다. 약점은 네 가지다.
  - 턴마다 DB를 조회한다. 런 도중 승인이 바뀌면 프롬프트가 바뀌고 재현성이 깨진다.
  - 예외를 삼키고 조용히 꺼진다.
  - org 범위 overlay가 없다.
  - 승인 RBAC가 없다.
- **크리덴셜.** 플랫폼 키 하나를 모두가 쓴다. BYOK도 테넌트별 레이트리밋도 없다. 한 테넌트의 폭주가 전체를 소진한다.
- **비용 귀속.** `runtime.py:649-656`은 `TrackedCodingModel`을 조립할 때 `user_id`와 `session_id`를 넘기지 않는다. 그래서 기본값 `""`가 쓰인다 ✔(`dataset/adapters.py:108-109`). 전문은 로컬 JSONL에 섞인다.
- **샌드박스.** 기본값이 `enabled: false` + `provider: memory`(host subprocess)이고 production에서 memory를 거부하지 않는다. 지금은 production에서 coding_model과 sandbox가 모두 off라서 잠재 위험이다. 켜는 순간 격리 없이 돈다. managed B2 설계는 옳지만 게이트를 통과하지 못했다.
- **게이트웨이.** `API_GATEWAY_TRUSTED_IPS`가 비어 있으면 모든 IP를 신뢰한다. 그래서 `X-User-ID`를 위조할 수 있다.

### 5.4 서비스 방향 판정

- **옳은 것.**
  - 모듈러 모놀리스와 역할별 배포(MICROSERVICE_REVIEW §0, §5).
  - 무상태 API, job과 스트림 재생.
  - 코딩 control plane을 첫 분리 후보로 둔 것.
  - 관리형 microVM 샌드박스(allocation-per-task). 에이전트 루프 SaaS의 표준 형태와 맞는다.
- **빠진 축.**
  1. **테넌트를 1급 개념으로.** 리뷰는 테넌트 격리를 "미래 재검토 트리거"로 두었다. SaaS에서는 전제 조건이다.
  2. **DA에 코딩 수준의 실행 규약(lease, step 메시지, admission) 적용.**
  3. **테넌트별 backpressure와 비용 계량.**
  4. **production에서 memory 샌드박스 금지.**
  5. **배포 산출물.** enterprise compose에 Celery worker와 beat가 없다.

**핵심 통찰.** 코딩 루프가 이미 증명한 패턴(lease, step 메시지, admission, allocation-per-task)이 NEOS의 **실행 규약 표준**이다. DA와 GEPA를 이 규약 위로 올리면 동시성, 격리, 서비스 방향 문제가 한꺼번에 줄어든다. 여기에 멀티에이전트까지 같은 규약 위에 올리면, 비전의 "진화형 멀티에이전트"를 수평 확장할 가장 비용이 낮은 경로가 된다. 저장소에 이미 검증된 패턴이 있기 때문이다.

---

## 6. 교차 분석: 다섯 보고서가 공통으로 가리키는 것

### 6.1 반복 패턴: 착지했지만 서로 부르지 않는 부품

| 착지한 부품 | 부르지 않는 쪽 |
|---|---|
| `SandboxReexecutor`, `execute.v1` | DA 조사 포트 |
| `state.verdict` | 루프 분기 |
| `jev.judge_shadow_enabled` | 어떤 코드도 읽지 않음 |
| GEPA engine, store.approve | 운영 호출자 |
| lesson staged | 승인자 |
| `approval_unattended` | runtime 조립 |
| parent 게이트 체인 | child 도구 포트 |

"플래그 off로 착지"라는 방법론 자체는 훌륭하다(로드맵 §8). 그러나 **착지한 것이 연결 테스트 없이 쌓이고 있다.** 로드맵 §14의 교훈("무는지 보지 않은 게이트")을 **배선 수준의 E2E 계약 테스트**로 제도화해야 한다. 예를 들면 "DA 조사 자식이 `execute.v1`을 불러 computed claim이 verified된다", "VERIFY FAIL이 IMPLEMENT 재진입을 일으킨다", "child의 `rm.v1`이 approval 이벤트를 남긴다" 같은 테스트다.

### 6.2 JEV의 올바른 자리: 브레이크, 계기판, 핸들을 분리한다

로드맵의 단조 축소 불변식(S11: 확률이 denylist를 이기면 우회로가 된다)은 **유지해야 한다.** 동시에 비전은 JEV가 분기와 판정을 맡기를 요구한다. 둘을 조화시키려면 JEV의 역할을 세 채널로 나누고 채널마다 불변식을 따로 둔다.

| 채널 | 역할 | 불변식 | 시작 단계 |
|---|---|---|---|
| **브레이크** (현재) | 도구 위험 | 좁히기만 한다. R₀보다 느슨해지지 않는다 | L2 shadow → L3 |
| **계기판** | 결과 판정 (claim, VERIFY 산출물) | 결정론 검증기가 1차 판정이고 JEV는 보조한다. 결정론이 불가능한 영역에서만 판정 권한을 갖는다. 판정자는 크로스 프로바이더로 둔다 | L5를 앞당겨 shadow |
| **핸들** | 분기 (라운드 계속/중단, DIG/SPLIT, 후보 선택, MID 에스컬레이션) | shadow로 would-branch만 기록한다. 채점 경계는 건드리지 않고 지출 경계만 건드린다 | L7′(선행 L1이면 충분) |

**효율 원칙(캐스케이드).**
- 결정론으로 판정 가능하면 LLM을 부르지 않는다.
- JEV 확률이 LOW나 HIGH면 그대로 확정한다.
- **MID일 때만** 강한 모델, 다른 계열 모델, 드라이런, 스냅샷 후 실행으로 에스컬레이션한다.
- read-only이면서 R₀=ALLOW인 도구는 JEV를 건너뛴다.
- (tool, 정규화한 input) 해시로 운영 캐시를 둔다. 일관성 측정용 fresh-uid 모드와 분리한다.

**fitness 충돌의 해법.**
- GEPA의 1차 fitness는 **결정론 검증기**다. 테스트 통과, 재실행 digest, `DeterministicGrader`.
- JEV는 (a) 결정론 검증이 불가능한 차원의 보조 점수, (b) canary 온라인 지표로만 쓴다.
- JEV 점수를 fitness에 넣으려면 먼저 사람 라벨과의 meta-eval 일치율이 사전 등록한 기준을 넘어야 한다.
- 이렇게 하면 Goodhart 위험(GEPA Non-goals가 든 근거)을 피하면서 비전을 수용한다.

### 6.3 코딩 루프를 범용 해결자로: 결과 라벨이 없다

- 비전의 중심인 코딩 루프가 가장 약한 검증 계약을 갖고 있다. VERDICT는 자기 보고 문자열이고 태스크 상태를 바꾸지 않는다.
- DA의 `ComputedEvidence` 재실행 계약과 코딩의 테스트 재실행을 **하나의 `Verifier` 추상화**로 묶는다. 입력은 스크립트/명령, 입력 digest, 기대 조건이고, 출력은 구조화된 exit code, digest, 판정이다.
- 그러면 북극성을 "검증형 분석이 1차 실행 모델"에서 **"재실행 가능한 검증이 붙은 코드 실행이 1차 실행 모델"**로 일반화할 수 있다. DA는 그 한 응용이 된다.

### 6.4 멀티에이전트: 통신은 금지하되 구조는 연다

- 로드맵 §2.3이 금지한 것은 coordinator, mailbox, `while(true)`라는 **통신 방식**이다. 이 금지는 옳다. durable 1-step과 lease를 지키기 때문이다.
- 반면 **parent를 거치는 경쟁 구조**는 금지되지 않았다. 같은 과제를 K개의 implement child가 서로 다른 worktree에서 풀게 한다. Verifier 결과와 JEV 계기판 점수로 하나를 골라 ff-merge한다.
- 기존 worktree, ff-merge, `max_active` 설계를 그대로 재사용한다. 이것이 **진화형 멀티에이전트의 최소 형태**이자 GEPA 후보군 개념의 런타임 버전이다.
- 선행 조건이 둘 있다. child 도구 게이트, 그리고 Docker·managed에서의 workspace clone.

### 6.5 증류의 원료 보존이 가장 되돌리기 어려운 항목이다

- #1~#22 원장과 funnel 아티팩트가 소실됐다(로드맵 §12.11 ④). 그래서 L4 백테스트와 D92 재현 게이트가 멈췄다.
- "System distillation is the moat" 관점에서 **궤적과 원장은 곧 해자의 원료**다.
- 동시에 코딩 run에는 model, provider, prompt_hash, overlay_id, lesson_ids가 기록되지 않는다. 앞으로 쌓일 원료도 증류할 수 없는 형태로 쌓이고 있다.

### 6.6 비전 자체에 대한 반대 검토

지금까지는 비전을 기준으로 삼아 NEOS를 평가했다. 이 절에서는 비전 쪽의 가정을 점검한다. 로드맵을 개정할 때 이 가정들을 **사전 등록할 가설**로 다뤄야 한다. 전제로 깔면 안 된다.

| 가정 | 반론 | NEOS에 주는 함의 |
|---|---|---|
| "코드를 짜고 돌리면 문제가 풀린다" | 코드 실행이 강한 검증을 주는 영역은 계산, 데이터, 테스트가 있는 코드처럼 **결정론 검증이 가능한 영역**뿐이다. 문헌 해석, 판단, 전략처럼 정답 오라클이 없는 문제에서는 코드 실행이 검증을 대신하지 못한다 | DA가 코딩 루프로 바뀌어도 인용과 판정 계층(`AgenticGrader`, ReportGrader)의 중요성은 줄지 않는다. 북극성을 "모든 것을 코드로"로 확장하지 말고 **"검증 가능한 부분은 코드로, 나머지는 보정된 판정자로"**로 적는다 |
| "JEV로 분기하면 효율적이다" | 확률 판정자는 보정이 돼 있어야 분기 신호가 된다. L1 기준선은 **일관성**을 쟀을 뿐 정확도를 재지 않았다(로드맵 §12.1: "일치율은 정확도가 아니다"). 보정되지 않은 확률로 분기하면 행위자의 `self_assessment`를 다른 모델의 자기 확신으로 바꾸는 것에 그친다 | 핸들 채널(§6.2)은 사람 라벨 meta-eval로 보정을 확인한 뒤에만 shadow에서 승격한다. 보정 지표(ECE, Brier)를 exit criteria에 넣는다 |
| "LLM-as-Judge가 품질을 끌어올린다" | 판정자를 fitness나 분기에 쓰는 순간 최적화 압력이 판정자를 향한다(Goodhart). 판정자와 행위자가 같은 계열이면 오류가 상관된다 | 결정론 검증기를 1차로 둔다. 판정자는 크로스 프로바이더로 두고 주기적으로 교체하거나 held-out 판정자를 둔다. GEPA fitness에 판정자 점수를 넣으려면 meta-eval이 선행돼야 한다(§6.2) |
| "자기개선·진화 루프는 돌수록 좋아진다" | 트랙 F가 실제로 실패했다. 진단자가 표본을 읽지 않고 같은 이야기를 반복했다(11건 중 10건). 진화는 eval set의 품질을 넘지 못한다. eval set이 작으면 과적합만 진화한다 | 트랙 O(벤치)와 held-out 회귀 게이트를 트랙 N(진화)보다 **먼저** 둔다. 진화의 상한은 벤치 품질이다 |
| "멀티에이전트가 단일 에이전트보다 낫다" | 병렬 후보는 비용을 K배로 늘린다. 선택 신호가 약하면 K개 중 나쁜 것을 고를 수도 있다. 이득은 **검증기가 강할 때만** 확실하다 | 경쟁 후보(P2-1)는 결정론 검증기가 있는 태스크 클래스에서만 켠다. K와 비용 대비 성공률 곡선을 벤치에서 먼저 잰다 |
| "AGI로 가는 최적 경로" | 제품 로드맵이 검증할 수 있는 명제가 아니다 | 로드맵은 "AGI"가 아니라 **측정 가능한 중간 목표**(§8.5 지표)로 방향을 관리한다 |

**정리.** 비전은 "검증기가 강한 곳에서 루프를 돌린다"로 좁힐 때 가장 힘이 세다. 그 형태가 바로 NEOS가 이미 잘하는 것(결정론 검증)과 겹친다. 따라서 이 반대 검토는 권고의 방향을 바꾸지 않는다. 대신 **순서**를 확정한다. 검증기와 벤치가 먼저, 분기·진화·경쟁은 그 다음이다.

---

## 7. 로드맵 수정 제안

로드맵의 강점(사전 등록, 표본 경계, 플래그 off 착지, 단조 축소)은 모두 유지한다. 아래는 **추가하거나 개정할 것**이다.

### 7.1 신규 트랙

- **트랙 M: 증거·궤적 보존**
  - 원장과 아티팩트를 워크트리 밖 영속 저장소로 주기적으로 백업하고, 복원 검증 게이트를 둔다.
  - 코딩 run에 `model/provider/prompt_hash/overlay_id/lesson_ids/rubric_digest`를 기록한다.
  - **Exit:** #23 원장을 외부에서 복원하고, 그 위에서 `jev_judge_backtest.py`가 실행된다.
- **트랙 N: 자기개선·레시피 증류**
  - GEPA 커널과 레시피 문서 Phase 0~2를 정본으로 가져온다.
  - 파이프라인은 후보 생성(GEPA, J6 스킬, 실패 캡처) → Verifier → held-out 회귀 게이트 → 사람 승인 → `validated_on` 기록 → canary → 자동 롤백 순이다.
  - **D19 개정:** "자동 변경 금지, 자동 후보 생성과 자동 롤백은 허용."
  - **Exit:** held-out에서 개선을 보인 승인 overlay 1건. 모델 교체 비용 첫 측정.
- **트랙 O: 오프라인 평가 벤치**
  - 라이브 n=1 표본 규율은 유지한다. 진화와 튜닝의 반복 처리량은 벤치로 분리한다.
  - 코딩 fixture 30~50건(결정론 채점)과 DA 카세트 질문 세트를 사전 등록하고 버전 관리한다.
  - **Exit:** GEPA evaluator 등록. 반복 채점(k≥3)의 신뢰구간 산출.
- **트랙 P: 실행 규약 통일과 테넌시**
  - DA lease, broker 분리, `RunContext`/`TenantContext`, 테넌트 admission과 계량, production memory 샌드박스 금지(8절 P0/P1).

### 7.2 기존 트랙 개정

| 트랙 | 개정 |
|---|---|
| J | **J1.5(신설, 최우선):** 포트 합성, 스크립트의 원장 커밋, 브리프 전달, E2E(`execute.v1` → computed → verified). 이것 없이 #23을 J 기준으로 해석하는 것은 의미가 없다 |
| E | 코딩 태스크 결과 라벨 정의("테스트 통과 AND 사용자 비거부"), Verifier 통합, verdict 기반 재진입, child 게이트 |
| K | K9 모드 신호 결정을 최우선으로(D-L1 활성화). K3 exit criteria 정의 |
| L | L5를 코딩 VERIFY와 DA claim에 shadow로 **앞당긴다.** L7′(분기 shadow)의 선행을 L1으로 완화. 운영 캐시, read-only 스킵, MID 캐스케이드 추가. 크로스 프로바이더 판정자 |
| §11 | 모든 플래그에 "승격 사다리(shadow → dev → staging → default)와 수치 exit criteria" 열을 추가 |
| §6.3 | "런타임 타입 발명 금지"는 유지하되, **오프라인에서 진화시켜 승인받은 스펙을 레시피로 카탈로그에 등록하는 경로**를 명시적으로 허용 |
| §9 | "Jev를 역할 라우팅에 넣지 않는다"는 유지하되, 비용 → 라우팅 레시피 후보는 오프라인 replay 검증 뒤 사람 승인으로 허용 |

---

## 8. 우선순위별 실행 계획

> **원칙.** 새 개념보다 배선을 먼저 한다. 모든 항목은 플래그 off로 착지하고, **배선 E2E 테스트를 완료 조건에 포함한다.** 일정은 추정하지 않았다. 규모 판단은 각 항목의 설계 문서에서 한다.

**의존 순서 (반드시 지킬 것)**

```
P0-2 child 게이트 ──▶ P0-1 포트 합성 ──▶ P1-1 Verifier ──▶ P1-8 GEPA evaluator ──▶ P2-1 경쟁 후보
     (execute를 열기 전에 게이트부터)            │
P0-7 궤적 기록 ─────────────────────────────────┴──▶ P1-9 벤치 ──▶ P2-2 recipe_versions
P0-6 K9 신호 ──▶ P1-4 JEV 효율/MID 캐스케이드 ──▶ P3 sandbox 내 unattended execute
P0-4 DA lease ──▶ P1-5 RunContext ──▶ P1-6 테넌트 admission
```

- **P0-1은 P0-2보다 먼저 하면 안 된다.** DA 조사 자식은 `ChildStepper`를 거치므로 승인 경로가 없다. 게이트 없이 `execute.v1`을 합성해 열면, 지금 implement child에 있는 우회 구멍을 DA에도 새로 만드는 셈이다.
- P0-7(궤적 기록)은 다른 모든 개선의 효과 측정에 필요하다. 가장 먼저 착수해도 된다.

### P0: 엔진과 안전 구멍 (배선)

| # | 항목 | 근거 절 | 완료 조건 |
|---|---|---|---|
| P0-1 | DA 조사 포트 합성(`CompositeToolPort` = Research + 게이트된 Coding), 스크립트 원장 커밋, 티켓에 repairs/dead_ends 전달 | 2.3 D1~D3 | `execute.v1` → computed claim → 재실행 → verified E2E |
| P0-2 | child 도구를 parent 게이트 체인(approval, JEV, hook)에 통과시킨다 | 3.4 | child `rm.v1` 호출이 approval 이벤트를 남기는 테스트 |
| P0-3 | VERIFY verdict 기반 분기. FAIL/PARTIAL이면 IMPLEMENT로 재진입(N회), 다 쓰면 escalate. PASS 증거는 구조화된 exit code | 3.5 | FAIL → 재진입 → PASS 시나리오 테스트 |
| P0-4 | DA 실행 lease(`da_run_leases` + 펜싱 + heartbeat). 살아 있는 lease가 있으면 resume은 409. `visibility_timeout`을 `time_limit`보다 크게 설정 | 5.2 | 동시 resume 테스트에서 두 번째가 거절됨 |
| P0-5 | Celery 브로커 Redis 분리(`noeviction`). compose에 worker와 beat 추가 | 5.2 | enterprise compose로 모든 큐 소비 |
| P0-6 | K9: `unattended` 모드 신호를 런 요청 필드로 받고 runtime에 전달 | 3.2 | 운영 경로 변이 테스트에서 DENY 접기 실행 확인 |
| P0-7 | 궤적과 원장 외부 백업. 코딩 run에 model/prompt_hash/overlay_id/lesson_ids 기록 | 6.5 | 복원 검증 |

### P1: 계기판·핸들과 컨텍스트

| # | 항목 |
|---|---|
| P1-1 | `Verifier` 추상화로 DA 재실행과 코딩 테스트를 통합하고 결과 라벨을 정의한다 |
| P1-2 | JEV 계기판 shadow: 코딩 VERIFY 산출물(diff, 테스트 로그)과 DA claim에 `claim_judge`형 루브릭을 붙인다. `judge_shadow_enabled`를 실제로 배선한다 |
| P1-3 | JEV 핸들 shadow(L7′): budgeter DIG/SPLIT, 라운드 계속/중단 옆에 would-branch를 기록한다. 질문 confidence를 판정자 확률 집계로 바꾸는 A/B를 벤치에서 돌린다 |
| P1-4 | JEV 효율: read-only 스킵, 운영 캐시, shadow fire-and-forget, 배치 `gather`, MID 캐스케이드 |
| P1-5 | `RunContext`/`TenantContext`를 만들고 전역 setter(`set_lesson_session_factory`)를 없앤다. Celery 태스크별 `DatabaseManager`와 LLM 클라이언트. `TrackedCodingModel`에 user_id와 run_id |
| P1-6 | 테넌트 admission(동시 런, 월 비용). Redis 기반 테넌트 레이트리밋. DA 취소 엔드포인트와 orphan reaper |
| P1-7 | production·staging에서 `sandbox.enabled: true`이고 `provider: memory`면 기동 거부. Docker·managed에 `clone_with_workspace` 구현 |
| P1-8 | GEPA 운영화: 첫 evaluator(결정론 코딩 fixture) 등록, async evaluator, **held-out 회귀 게이트**(`test_mean > seed + margin`), seed와 같은 결과는 staged 금지, k회 반복, reflector system을 중립으로, side_info를 필드별로 truncate, surface 필터, run 단위 RNG, 운영자 CLI(생성, 승인, 롤백) |
| P1-9 | 오프라인 평가 벤치(트랙 O). 코딩 fixture 30~50건, DA 카세트 세트 |

### P2: 진화형 멀티에이전트와 증류

| # | 항목 |
|---|---|
| P2-1 | 경쟁 후보 멀티에이전트: implement child K개(서로 다른 worktree와 레시피) → Verifier와 JEV 계기판으로 선택 → ff-merge |
| P2-2 | overlay와 lesson을 `recipe_versions`(kind, scope, content hash, verifier, `validated_on`)로 일반화. base prompt나 모델이 바뀌면 주입을 중단하고 재검증 run을 staged |
| P2-3 | canary: overlay 행별 `rollout_pct`와 run 해시 버킷. 온라인 지표로 **자동 롤백만** 허용 |
| P2-4 | 크로스 프로바이더 판정자와 사람 라벨 meta-eval 정례화. calibration "Latest Run"을 채운다 |
| P2-5 | 성공과 실패 궤적 모두에서 LLM 증류기로 레시피 후보를 만든다(오프라인, staged만). 승인된 우수 궤적을 golden trajectory로 export |
| P2-6 | 판정·수선 체계 세 벌(DA, workflow/harness, 코딩)을 하나의 Recipe 레지스트리로 통합 |
| P2-7 | 비용과 품질 조인 → 라우팅 레시피 후보 → 오프라인 replay 검증 |
| P2-8 | Ralph `ImprovementTracker`를 같은 체계로 옮기거나 기본값을 off로 바꾼다(현재 유일하게 게이트가 없는 자동 학습) |
| P2-9 | overlay를 런 시작 시 핀으로 고정하고 manifest에 기록. 승인 RBAC와 API. 게이트웨이 신뢰 IP가 비면 fail-closed |

### P3: 자동 승격 (D19 재개정 조건)

다음 셋이 모두 충족돼야 자동 승격을 논의한다.
- 결정론 fitness
- held-out 회귀 게이트
- canary 자동 롤백의 실전 기록 N건 이상
- (추가) sandbox 안 `execute.v1`의 unattended 허용 정책. JEV LOW 밴드이고 network-deny가 확인된 sandbox에 한한다. 이것은 "넓히는" 정책이므로 단조 축소 불변식과 **분리된 별도 정책 층**으로 설계한다.

### 8.5 진척 지표 — 모멘텀을 무엇으로 재는가

"방향이 맞다"는 판단을 반복 측정할 수 있게 만든다. 모든 지표는 오프라인 벤치(트랙 O)나 원장에서 계산한다. 라이브 표본 규율(로드맵 §10.1)과 섞지 않는다.

| 층 | 지표 | 현재 값 | 첫 목표 |
|---|---|---|---|
| 엔진 | DA run에서 `execute.v1` 기반 computed claim이 verified된 비율 | 0 (경로 없음) | 0 초과, E2E 1건 |
| 핸들 | VERIFY FAIL 뒤 재진입해서 PASS로 끝난 코딩 run 비율 | 측정 불가 (재진입 없음) | 벤치에서 기준선 산출 |
| 계기판 | 판정자와 사람 라벨의 일치율, 보정 오차(ECE) | 미측정 (calibration "Latest Run" 비어 있음) | 1회 측정, 사전 등록 기준 |
| 브레이크 | JEV shadow의 `would_be_outcome`과 R₀의 불일치 건수, `jev_unavailable` 비율, 도구 호출당 추가 지연 | 미측정 (L2 off) | L2 shadow 기간의 기준선 |
| 변속기 | 신호 → 승인된 레시피 전환 수 / 월, 승인 overlay의 held-out 개선폭 | 0 | 1건, 개선폭 > 사전 등록 margin |
| 증류 | 6개 범주 중 자동 후보 생성 경로가 있는 범주 수 | 0/6 (수동 2) | 3/6 |
| 모델 비종속 | `validated_on` 공급자가 2개 이상인 레시피 비율, 모델 교체 뒤 재검증 비용 | 기록 없음 | 첫 측정 |
| 서비스 | 동시 resume 이중 실행 건수, 테넌트 귀속이 없는 LLM 호출 비율 | 가능(lease 없음) / 코딩 호출 100% | 0 / 0% |

### 8.6 사람의 결정이 필요한 사항

아래는 코드 작업으로 풀 수 없고 방향을 정해야 하는 항목이다. 로드맵 §11에 "결정 대기"로 올린다.

1. **D19 개정 범위.** "자동 후보 생성과 자동 롤백 허용, 자동 승격 금지"로 개정할 것인가(§7.1 트랙 N).
2. **진화 fitness 정책.** 결정론 검증기를 1차로 두고, JEV와 판정자는 meta-eval 뒤 보조로만 둘 것인가(§6.2). GEPA 문서의 Non-goals와 비전 사이의 충돌을 여기서 닫는다.
3. **K9 모드 신호.** unattended를 런 요청 필드로 받을 것인가, 채널이나 API 키 속성으로 받을 것인가.
4. **테넌트 경계.** 격리 단위를 user로 둘 것인가 org로 둘 것인가. overlay와 레시피를 org 범위로 공유할 것인가. 승인 권한(RBAC)은 누구에게 줄 것인가.
5. **북극성 문구.** "검증형 분석이 1차 실행 모델"을 "재실행 가능한 검증이 붙은 코드 실행이 1차 실행 모델"로 일반화할 것인가(§6.3). 일반화한다면 §6.6의 한계("검증 가능한 부분은 코드로")를 같이 적을 것인가.
6. **판정자 공급자 다양성.** 트랙 B의 "크로스 프로바이더 폴백 금지"와 별개로 크로스 프로바이더 **판정자**를 허용할 것인가.

---

## 9. 부록

### 9.1 즉시 수정 가능한 개별 버그

GEPA 항목 중 설계가 의도적으로 고른 동작(회귀 게이트 없음, side_info 통째로 폐기, 동기 evaluator)은 이 표에서 뺐다. 그 항목들은 §4.3의 "다시 열지 결정한다"에 있다.

| 위치 | 내용 |
|---|---|
| `neos/gepa_opt/provider.py:26` ✔ | reflector `system=curr_param`. 후보 텍스트가 system 지시로 들어간다 |
| `neos/gepa_opt/store.py:638-647` ✔ | approve할 때 archive에 surface 필터가 없다(잠재 결함) |
| `neos/gepa_opt/engine.py:201` ✔ | 부모 선택에 매번 `Random(0)`을 새로 만든다. run 단위 rng를 넘기지 않는다 |
| `neos/workflow/recursive/verifier.py:88` ✔ | `float(harness.get("score") or 1.0)`. score 0.0을 1.0으로 바꾼다 |
| `neos/learn/postgres.py:102-113` ✔ | lesson `list()` 쿼리에 ORDER BY가 없다. cap 5를 선택하는 결과가 비결정적이다 |
| `deep_analysis/submission.py:118-126`, `graders/agentic.py:109` | computed claim이 증거 없이 agentic 심사를 받는다 |
| `neos/learn/lessons.py:127-131` ✔ | 전역 memory-only 토글 |
| `neos/api/dependencies/auth.py:87-93` | 신뢰 IP가 비면 모두 신뢰 |

### 9.2 검증 로그 (v1.1 검수)

서브에이전트 보고 가운데 결론을 좌우하는 주장을 HEAD `403aeb77`에서 다시 확인했다.

| 주장 | 확인 방법 | 결과 |
|---|---|---|
| DA 조사 포트에 fetch/submit/check만 있다 | `research_tools.py:159-164` 열람 | ✔ 확인 |
| 조사 세션이 샌드박스를 열지만 코딩 포트와 합성하지 않는다 | `research_session.py` 열람, `CodingToolPort` 사용처 grep | ✔ 확인. 사용처는 `coding/runtime.py:594` 하나 |
| `state.verdict`를 분기에서 읽지 않는다 | `neos/coding` 전체에서 `verdict` grep | ✔ 확인. 읽는 곳은 parse, persist, codec뿐 |
| child 도구가 게이트를 우회한다 | `subagent_port.py:53-72` 열람 | ✔ 확인. allowlist, validate, risk 확인 뒤 executor를 직접 호출 |
| `judge_shadow_enabled` 소비처 0, DA에 jev 0 | grep | ✔ 확인 |
| `runtime.py`가 unattended 신호를 전달하지 않는다 | `runtime.py`에서 `unattended` grep | ✔ 0건 |
| GEPA 운영 호출자 0, 회귀 게이트 없음 | grep, `engine.py:420-445` 열람 | ✔ 확인 |
| 로드맵에 GEPA 언급 0 | grep | ✔ 확인 |
| `clone_with_workspace` 구현체 없음 | `def clone_with_workspace` grep | ✔ 0건. memory만 특별 처리 |
| DA resume이 running 상태도 재디스패치한다 | `jobs.py:66` `RESUMABLE_STATUSES = {"running","failed"}`, handler 열람 | ✔ 확인 |
| `visibility_timeout` 미설정, `time_limit=3900`, `acks_late=True` | grep | ✔ 확인 |
| lesson 팩토리 전역 토글 | `learn/lessons.py:127-131` 열람 | ✔ 확인 |
| 질문 confidence가 `max(conf, self_assessment)`다 | `ledger.py:969-972` 열람 | ✔ 확인. 해소 조건에는 `verified_any`도 함께 걸려 있다(`:999`) |
| AgenticGrader 임계 0.35, 샘플 0.3 | `schema.py:977-978` | ✔ 확인 |
| 티켓 goal이 question_text 우선 | `subagent_adapter.py:147` | ✔ 확인 |
| 샌드박스 기본값 | `neos.default.yaml:540-542`, production·staging yaml | ✔ **정정.** v1.0은 "기본 provider memory"라고만 썼다. 실제로는 `enabled: false`가 함께 있으므로 켤 때의 위험으로 서술을 고쳤다 |
| 코딩 LLM 기록에 user/session 없음 | `runtime.py:649-656`, `adapters.py:108-109` | ✔ **정정.** 값을 ""로 넘기는 것이 아니라 인자를 생략해서 기본값 ""가 쓰인다 |
| 전역 `db_manager`와 LLM 캐시가 이벤트 루프를 넘나든다 | 코드 구조 추론 | ⚠ 미재현. 재현 테스트를 P1-5 착수 전에 먼저 작성할 것 |
| Redis `allkeys-lru` 브로커 공유 | `docker-compose.enterprise.yml:26,94` 열람 | ✔ 확인 (v1.2). 브로커 db 2가 `--maxmemory-policy allkeys-lru` 인스턴스에 있다 |
| GEPA "버그" 목록 | GEPA 설계 문서 Risks, Loop pins, Key Decisions와 대조 | ✔ **정정 (v1.2).** 회귀 게이트 없음, 8KB 통째 폐기, 동기 evaluator, 미니배치 `Random(0)`은 설계가 고른 동작이다. §4.3을 둘로 나눴다 |

---

### 9.3 다른 문서에 반영한 위치 (v1.2)

| 문서 | 반영한 곳 | 내용 |
|---|---|---|
| `DEEP_ANALYSIS_HARNESS_ROADMAP.md` | 기준 시점 줄, §1 J 행·플래그 블록, §4.5 J1·**J1.5**, §10.1, §10.3, §11(사람의 결정, GRADE1·2, CHILD-GATE, J1.5), §12.3, §13 E·**E′**, §15 | 코드로 확인한 사실은 취소선과 날짜를 붙여 정정했다. 방향 제안(D19, fitness, Jev 세 채널, 판정자, 북극성)은 "사람의 결정" 행에만 올렸다 |
| `MICROSERVICE_REVIEW_260927.md` | §3.1 S14~S19, §7 트리거 주석, §8 D-6 | DA lease, visibility_timeout, 브로커 축출, 워커 전역 상태, 테넌트 귀속, memory 샌드박스 |
| `GEPA_SELF_IMPROVEMENT_MIGRATION.md` | Post-landing review 절, Open Questions 주석 | 결함 3건과 설계 재검토 5건을 나눠 적었다. 커널 밖에 남은 공백 5건 |

## 10. 맺음말

- NEOS는 "안전하게 멈추는 법"을 먼저 완성했다. 자율 루프를 만드는 순서로는 옳다. 대부분의 에이전트 프레임워크는 그 반대 순서로 간다.
- 이제 필요한 것은 새 트랙을 벌이는 일이 아니다. **이미 세운 검증기(결정론 채점, 재실행, JEV 밴딩)를 세 곳에 꽂는 배선**이다.
  - 조사 자식의 도구 포트 → 엔진
  - 루프의 분기 → 핸들
  - GEPA의 evaluator → 변속기
- 그러면 비전(코딩 루프 + JEV 분기·판정·위험 검증 + 자기개선 멀티에이전트)과 원칙("System distillation is the moat")이 같은 뼈대 위에 선다. 그 뼈대는 **재실행 가능한 검증기가 fitness이자 레시피의 verifier가 되는 구조**다.
- 서비스 측면에서는 코딩 루프가 증명한 실행 규약(lease, step 메시지, admission, allocation-per-task)을 DA, GEPA, 테넌트 축으로 넓히면 된다. 싱글턴 우려는 그 과정에서 `RunContext`로 자연히 해소된다.

# 하네스 Orchestrator 에서 리포트 작성·정체 판정 꺼내기 (B)

- 날짜: 2026-10-08
- 상태: 설계 승인 대기
- 범위: 테스트 구조 의존 줄이기 묶음의 두 번째(B). A(코딩 루프 체크포인트 이음매)는 dev 에 머지됐다(555eb444). C 는 별도 spec.
- 깊이: "개념 추출"(사용자 선택). 트리·라운드 진행(`_run_round`, `_split_decompose`, `_adopt_subquestions` …)과 워커 디스패치(`_run_worker`)는 이번 범위 밖이다.

## 1. 배경

`Orchestrator`(`neos/workflow/deep_analysis/orchestrator.py`, 클래스 ~1,650줄)의 공개 메서드는 `run(root_text)` 하나지만,
테스트는 그 private 멤버를 **121번** 만진다. 개념별로 묶으면:

| 개념 | 테스트가 만지는 것 | 횟수 |
|---|---|---|
| 트리·라운드 진행 | `_split_decompose` `_run_round` `_adopt_subquestions` `_reinvestigation_count` `_partition` `_ensure_root` … | 37 |
| **리포트 마무리** | `_finalize` 27 · `_child_summaries` · `_collect_caveats` | 29 |
| 워커 디스패치 | `_run_worker` 15 · `_grade` 3 | 18 |
| **정체 판정** | `_stall_counts` 6 · `_register_progress` 4 · `_made_progress` 3 · `_register_round_outcome` 3 · `_force_terminate_stalled` · `_all_failed_rounds` | 18 |
| 정지 사유·예산 | `_mark_stop_reason` 10 · `_install_token_budget` 9 | 19 |

`_finalize` 를 부르는 27곳 중 22곳(`test_orchestrator_m4.py` 18, `test_compose_child_j4.py` 4)은 **리포트 작성**
(compose/assemble → render → grade 재시도, 고아 인용, 실패 부록, compose 자식)을 시험한다. 5곳(`test_orchestrator_m4_reinvest.py` 2, `test_orchestrator_m4.py` 3)만
재조사 라운드를 시험한다. `_finalize` 의 본문도 그 경계로 갈린다 — 앞 ~23줄은 축약·충돌 해소·재조사(라운드 루프 `_run_round` 가 필요),
뒤 ~215줄은 리포트 작성이고 의존성은 `ledger`, `synthesizer`, `citation_renderer`, `report_grader`, `sandbox_provider`,
`compose_runtime_factory`, `_checkpoint` 일곱뿐이다(Orchestrator 의 생성자 인자는 27개).

정체 판정은 카운터·정책과 부수효과(원장 기록·이벤트·질문 분할·`SystemicWorkerFailure`)가 한 메서드에 섞여 있어, 테스트가
카운터를 직접 심고(`_stall_counts[q] = 2`) 메서드를 스파이로 바꿔치기한다(`_register_progress = spy`).

이미 생성자가 받는 의존성을 생성 뒤에 꽂는 곳도 있다(A 의 ①과 같은 원인): `orch.sandbox_provider = …`·`orch.compose_runtime_factory = …` 8곳,
`orch.max_stall_rounds = 2` 1곳.

## 2. 목표와 비목표

**목표**
- 리포트 작성을 `ReportWriter` 로, 정체 판정을 `StallTracker`(+ 순수 함수)로 꺼낸다. 각자 작은 공개 인터페이스를 갖고, 테스트는 그것을 직접 겨눈다.
- 위 두 개념에 걸린 테스트의 private 접근과 생성 뒤 의존성 꽂기를 없앤다.

**비목표**
- 행동 변경 없음. 원장 이벤트(종류·순서·페이로드), 리포트 문자열, 예외는 그대로다.
- 트리·라운드 진행, 워커 디스패치, 정지 사유·예산은 건드리지 않는다.
- `Orchestrator.__new__` 로 생성자를 건너뛰고 필드를 꽂는 두 파일(`test_subquestion_adoption.py`, `test_subquestion_budget_and_review.py`,
  6곳)은 트리 개념을 시험하므로 이번에 두지 않는다.
- `test_orchestrator_run_worker.py` 의 `orch._register_round_outcome(...)` 3곳은 남는다 — Orchestrator 가 tracker 를 먹이는 배선을 시험한다(단언 `_all_failed_rounds` 는 `tracker.failed_rounds` 로).
- `test_subagent_adapter.py` 의 `orch._force_terminate_stalled(...)` 1곳은 남는다 — 정체 종료의 **부수효과**(자식 취소·원장·분할)는 설계상 Orchestrator 에 남으므로 그것을 시험하는 호출이다. 그 테스트의 `_stall_counts` 심기·읽기는 `StallTracker` 로 옮긴다.
- 재조사 테스트 5곳의 `_finalize` 호출은 남는다(라운드 루프가 필요하다): `test_orchestrator_m4_reinvest.py` 2곳과 `test_orchestrator_m4.py` 의
  `test_conflict_reinvestigation_is_globally_capped_at_one`·`test_reinvestigation_gate_is_event_based_and_durable`·`test_a_starved_reinvestigation_round_does_not_kill_the_run`.
  이 셋은 `monkeypatch.setattr(orch_mod, "resolve_conflicts", …)` 로 충돌 해소를 바꿔치기한다 — `resolve_conflicts` 를 부르는 코드가
  `report_writer.reduce_and_resolve` 로 옮겨 가므로 패치 대상을 `report_writer` 모듈로 옮긴다(옮기지 않으면 패치가 조용히 무효가 된다).

## 3. 설계

### 3.1 `ReportWriter` — `neos/workflow/deep_analysis/report_writer.py` (신규)

```python
class ReportWriter:
    def __init__(
        self,
        ledger,
        synthesizer,
        citation_renderer,
        report_grader,
        *,
        sandbox_provider=None,
        compose_runtime_factory=None,
        checkpoint: Callable[[], Awaitable[None]] | None = None,  # None 이면 아무것도 안 하는 코루틴
    ) -> None: ...

    async def write(self, root_id: str, summaries: dict[str, NodeSummary]) -> str:
        """축약·해소가 끝난 요약으로 리포트를 쓴다. 빈손으로 끝나지 않는다(§6.8) — 캡을 다 쓰면 실패 부록을 단다.
        끝에서 `ledger.complete_run()` 을 부른다(지금과 같다)."""


async def reduce_and_resolve(synthesizer, ledger, source_tiers) -> tuple[dict[str, NodeSummary], list[str]]:
    """계층 축약 + 노드별 충돌 해소. (요약, 재조사할 질문 id 들)."""
```

- **옮기는 것**(글자 그대로, `self.` 대상만 바뀐다): `_finalize` 의 리포트 작성 부분(`root_summary = summaries.get(root_id)` 부터 끝까지),
  `_child_summaries`, `_collect_caveats`, `_compose_draft`, `_log_code_worker_outcome`, `_reduce_and_resolve`(→ 모듈 함수 `reduce_and_resolve`),
  그리고 그것들만 쓰는 모듈 헬퍼 `_reader_facing_caveats`, `_best_rejected_draft`, `_ensure_limits_section`, `_ensure_question_coverage`.
  옮기기 전에 각 헬퍼의 다른 사용처를 이름으로 확인한다(2026-10-08: 코드에서는 orchestrator 만, 테스트는 `_best_rejected_draft`·`_reader_facing_caveats` 를 import).
- `Orchestrator.__init__` 은 자기 인자로 `self.report_writer = ReportWriter(self.ledger, self.synthesizer, self.citation_renderer,
  self.report_grader, sandbox_provider=…, compose_runtime_factory=…, checkpoint=self._checkpoint)` 를 짓는다. 별도 주입 인자는 두지 않는다(YAGNI).
- `Orchestrator._finalize` 는 ~25줄로 준다: `reduce_and_resolve` → 재조사(있으면 `_run_round` 후 다시 `reduce_and_resolve`,
  `TokenBudgetExhausted` 는 지금처럼 `_mark_stop_reason`) → `return await self.report_writer.write(root_id, summaries)`.
- `_emit` 은 리포트 작성 부분이 쓰지 않는다(2026-10-08 확인) — `synth_pass` 이벤트는 `_finalize` 에 남는다.

### 3.2 정체 판정 — `neos/workflow/deep_analysis/stall.py` (신규)

```python
@dataclass(frozen=True)
class Progress:
    spent_tokens: int
    verified: int | None   # 원장이 `verified_claims` 를 모르면 None
    feedback: int | None   # 원장이 `feedback_count` 를 모르면 None


async def snapshot(ledger, question) -> Progress:
    """이번 패스 전의 신호. 토큰은 질문 객체에서, 검증 주장·피드백은 원장에서(지금의 1449-1452행과 같은 읽기)."""

async def made_progress(ledger, question_id: str, before: Progress) -> bool:
    """새 토큰 소비, 새 검증 주장, 새 반려 피드백 중 하나라도 있으면 진전. 알 수 없는 신호(None)는 진전으로 친다.
    지금의 `_made_progress` 와 **같은 순서로 읽고 같은 곳에서 멈춘다**(토큰이 늘었으면 원장의 나머지를 읽지 않는다)."""


class StallTracker:
    def __init__(self, max_rounds: int) -> None: ...
    def record(self, question_id: str, made_progress: bool) -> bool:
        """진전이면 0 으로, 아니면 +1. 캡에 닿으면 True(부르는 쪽이 종료시킨다)."""
    def count(self, question_id: str) -> int: ...
    @property
    def failed_rounds(self) -> int: ...
    def clear(self, question_id: str) -> None: ...
    def record_round(self, all_failed: bool) -> int | None:
        """모든 워커가 실패한 라운드가 연속 몇 번인지. 캡에 닿으면 그 수, 아니면 None."""
```

- `StallTracker` 는 부수효과가 없다. 원장 기록·이벤트·서브에이전트 취소·`_do_split`·`SystemicWorkerFailure` 는 Orchestrator 에 남는다:
  `_register_progress(qid, made)` 는 `if self.stall.record(qid, made): await self._force_terminate_stalled(qid)` 가 되고,
  `_force_terminate_stalled` 는 `self.stall.count(qid)` 를 읽고 `self.stall.clear(qid)` 한다. `_register_round_outcome` 은 `record_round` 의 반환으로 판단한다.
- `_made_progress`·`_verified_count`·`_feedback_signal` 은 `snapshot` + `made_progress` 로 바뀐다. 호출부(`_run_round`, 2026-10-08 기준 1449-1452·1532-1540행)는
  `before = await snapshot(self.ledger, question)` 를 들고 있다가 `await made_progress(self.ledger, qid, before)` 로 판정한다.
  (순수 `progressed(before, after)` 는 두지 않는다 — 토큰이 늘어도 원장을 두 번 더 읽게 되어 DB 쿼리 패턴이 바뀐다.)
- `Orchestrator.__init__` 에 `stall_tracker: StallTracker | None = None` 를 더한다. 기본은 `StallTracker(self.max_stall_rounds)`.
  `_stall_counts`·`_all_failed_rounds` 필드는 사라진다.
  - 이 주입은 테스트를 위한 문이지만 정당하다: 정체 상태는 크래시 재개 때 초기화되는 런타임 상태이고, 시험하려면 상태를 심어야 한다.

### 3.3 이주 규칙

| 지금 | 바꾼 뒤 |
|---|---|
| `orch = _orch(...); orch.sandbox_provider = P; orch.compose_runtime_factory = F` | `_orch(..., sandbox_provider=P, compose_runtime_factory=F)` (생성자가 이미 받는다) |
| `orch.max_stall_rounds = 2` (생성 뒤) | 생성자 `max_stall_rounds=2`, 또는 정체 판정만 시험하면 `StallTracker(2)` |
| `report = await orch._finalize("root0001")` (리포트 작성 시험) | `summaries, _ = await reduce_and_resolve(synth, ledger, tiers)` → `await ReportWriter(...).write("root0001", summaries)` — 지원 헬퍼 하나(`_write(...)`)로 묶는다 |
| `orch._child_summaries = lambda ...: [...]` (메서드 바꿔치기, `test_orchestrator_m4.py` 1곳) | 그 값이 나오도록 **입력**을 꾸민다: 원장 가짜의 `children(root)` 가 그 질문들을 돌려주고 `summaries` 에 그 요약이 있다. 같은 `NodeSummary` 값이 작성기에 닿는지 확인한다 |
| `await orch._collect_caveats(summaries)` | 작성기 경유 단언이 어려우면 `collect_caveats(ledger, summaries)` 를 모듈 공개 함수로 두고 그것을 부른다 |
| `orch._stall_counts[q] = 2` | `tracker = StallTracker(n); tracker.record(q, False)` ×2 → `Orchestrator(..., stall_tracker=tracker)` |
| `orch._register_progress = spy` | `StallTracker` 하위 클래스로 `record` 호출을 기록해 생성자로 넘긴다 |
| `await orch._made_progress(q, 0, 1, 0)` | `await made_progress(ledger, q, Progress(0, 1, 0))` |
| `await orch._register_round_outcome([...]); orch._all_failed_rounds == 1` | `StallTracker(2)` 의 `record_round(...)` 와 그 상태로(아래 단언 규칙) |
| `from ...orchestrator import _best_rejected_draft, _reader_facing_caveats` | `from ...report_writer import ...` |

**단언 규칙(B·C 공통, A 의 Task 4 판정을 일반화):** 단언의 **기댓값과 의미는 바꾸지 않는다.** 단 단언의 *대상 식*은 사라진 private
필드·메서드에서 **같은 값을 돌려주는 공개 인터페이스**로 옮길 수 있다(`orch._stall_counts[q] == 0` → `tracker.count(q) == 0`).
그런 곳은 보고서에 하나하나 적는다. 기댓값까지 바뀌어야 하면 멈추고 보고한다.

## 4. 검증

1. 기준선: `tests/workflow/deep_analysis` 의 테스트 이름(2026-10-08 수집 1199)과 실행 결과(이름별)를 저장한다. 작업 뒤 이름으로 대조 —
   사라진 이름 0, 통과→실패 0. (A 와 같은 절차. 결과 줄은 `^(PASSED|FAILED|ERROR|XPASS|XFAIL) \S+::` 로만 거른다.)
2. 지표:

| 지표 | 명령 | 기준선 | 목표 |
|---|---|---|---|
| `_finalize` 직접 호출 | `grep -rnoE '\borch(estrator)?\._finalize\(' tests \| wc -l` | 27 | 5 |
| 정체 private | `grep -rnoE '\borch(estrator)?\.(_stall_counts\|_register_progress\|_made_progress\|_register_round_outcome\|_force_terminate_stalled\|_all_failed_rounds)\b' tests \| wc -l` | 18 | 4 |
| 리포트·정체 의존성 생성 뒤 꽂기 | `grep -rnE '\borch(estrator)?\.(sandbox_provider\|compose_runtime_factory\|max_stall_rounds)\s*=[^=]' tests \| wc -l` | 9 | 0 |
| (참고) Orchestrator private 전체 | `grep -rnoE '\borch(estrator)?\._[a-z][a-z0-9_]*' tests \| wc -l` | 121 | 기록만 |

3. **동등성 고정:** `ReportWriter` 경유 리포트가 옮기기 전 `_finalize` 와 같은지 — 과도기 대조 테스트(A Task 1 과 같은 방식: 옛 경로와 새
   경로를 같은 입력으로 돌려 리포트 문자열과 원장 이벤트 목록이 같은지, 옮긴 뒤 삭제)로 확인한다. 대상 입력: 첫 시도 통과, 고아 인용 재시도 후 통과,
   캡 소진 부록, compose 플래그 on/off.
4. 하네스 스위트가 DB 를 쓰는 테스트를 포함하면 기준선과 같은 환경에서 돌린다(메모: 로컬 통합 테스트는 부트스트랩된 DB 필요).
5. CI 의 Ruff 명령을 그대로 돌린다.

## 5. 위험과 대응

- **원장 이벤트 순서가 바뀐다.** 작성기로 옮기며 `_checkpoint`·`log` 순서가 바뀌면 재개(resume)가 달라진다. 옮기는 본문은 글자 그대로이고,
  §4.3 의 과도기 대조가 이벤트 목록 전체를 비교한다.
- **`max_stall_rounds` 를 읽는 시점.** 지금은 `_register_progress` 가 `self.max_stall_rounds` 를 **매번** 읽는다. `StallTracker` 는 생성 때 받는다.
  프로덕션에서 생성 뒤 `max_stall_rounds` 를 바꾸는 곳은 없다(2026-10-08 grep — 생성자 396행뿐). 테스트의 1곳은 §3.3 으로 옮긴다.
- **재개 시 정체 카운터.** 지금도 인메모리라 재개하면 0 이다 — 그대로다.
- **모듈 수준 패치가 조용히 무효가 된다.** 옮기는 코드가 부르는 이름을 테스트가 `monkeypatch.setattr(<모듈>, 이름, …)` 로 바꿔치기하면, 코드가 옮긴 뒤엔 새 모듈을 패치해야 한다. 옮기는 코드의 import 문(함수 안 지연 import 포함)은 글자 그대로 옮기고, `orch_mod`·`orchestrator_module` 패치 5곳(2026-10-08) 중 옮긴 이름(`resolve_conflicts` 3곳)만 대상을 바꾼다.
- **compose 자식 경로.** `_compose_draft` 는 `sandbox_provider`·`compose_runtime_factory` 를 쓰고 원장에 code_worker 이벤트를 남긴다. 옮긴 뒤에도
  `test_compose_child_j4.py` 의 이벤트 단언이 그대로 통과해야 한다.

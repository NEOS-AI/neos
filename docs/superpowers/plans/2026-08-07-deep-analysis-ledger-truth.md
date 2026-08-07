# 원장이 진실을 말한다 (W2) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 심층분석 run이 왜 멈췄는지를 원장에 정확히 적고, 적힌 리포트 본문을 이름 있는 조회로 꺼낼 수 있게 하고, 리포트 품질을 깎은 사건이 프론트엔드 상태에 남게 한다.

**Architecture:** 세 층을 각각 최소 변경으로 고친다 — 정지 사유 판정을 `_mark_stop_reason()` 한 곳으로 접고(정상 경로와 예외 경로가 서로 다른 판정을 하던 것을 없앤다), 이미 `job_completed` 페이로드에 있는 리포트 본문에 `Ledger`·analytics 조회를 붙이고, 프론트 리듀서에 라벨 7종과 덮어써지지 않는 `degradations` 누적 필드를 더한다.

**Tech Stack:** Python 3.12 · SQLAlchemy 2.0 (async) · pytest + pytest-asyncio · TypeScript · Next.js 16 · vitest (`pnpm test:source`)

**설계 정본:** [../specs/2026-08-07-deep-analysis-ledger-truth-design.md](../specs/2026-08-07-deep-analysis-ledger-truth-design.md)

## Global Constraints

- **백엔드 테스트는 venv 경로로.** bare `pytest`는 asyncio 마커 수집에 실패한다.
  대상: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q`
  전체: `.venv/bin/python -m pytest -q`
- **PostgreSQL이 떠 있어야 한다.** 없으면 DB 기반 테스트 ~49건이 `OSError: Connect call failed ... 5432`로 실패한다. 확인: `nc -z localhost 5432`. **직접 띄우지 말고** 안 떠 있으면 보고할 것.
- **현재 기준선: 전체 2,390 passed / 16 skipped / 0 failed.** 회귀 비교 시 `grep '^FAILED tests/'`로 거른다 — `'^FAILED'`만 쓰면 진행 표시(`FAILED  [ 7%]`)까지 걸린다.
- **프론트엔드:** `pnpm --dir web test:source` (현재 147 passed) · `pnpm --dir web exec tsc --noEmit`
- **린트:** `.venv/bin/ruff check neos/ tests/workflow/deep_analysis/` — 손댄 파일은 clean이어야 한다. `neos/` 전체에 ~234건의 **기존** 부채가 있으며 이 브랜치가 만든 것이 아니다.
- **커밋 메시지에 `Co-Authored-By` 트레일러를 넣지 않는다.**
- **이벤트 로그는 append-only** (D8). 페이로드에는 개수·식별자만 — 프롬프트/응답/리포트 본문 금지. (단 `job_completed`는 예외이며 이미 본문을 싣는다 — 이 계획은 그것을 **읽기만** 한다.)
- **매직넘버 금지.** 튜너블 값은 `neos/config/schema.py`.
- 문서·주석은 각 파일의 기존 언어 관행을 따른다. `orchestrator.py`·`ledger.py`·`analytics.py`는 영문 docstring, `progress.ts`는 한국어 주석.

---

## File Structure

| 파일 | 책임 | Task |
|---|---|---|
| `neos/workflow/deep_analysis/orchestrator.py` | `_mark_stop_reason()` 신설 + 두 호출부 교체 | 1 |
| `neos/workflow/deep_analysis/ledger.py` | `report_markdown()` 단건 조회 | 2 |
| `neos/workflow/deep_analysis/analytics.py` | `report_bodies()` 배치 조회 | 2 |
| `web/lib/deep-analysis/progress.ts` | 라벨 7종 · `report_graded` 분기 수정 · `degradations` 누적 | 3 |
| `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md` | §2.2 S3·S4 · §5.2 · §7 · §8 W2 갱신 | 4 |
| `neos/workflow/deep_analysis/DECISIONS.md` | D26 추가 | 4 |

---

## Task 1: 정지 사유를 한 곳에서 판정한다 (G9)

**Files:**
- Modify: `neos/workflow/deep_analysis/orchestrator.py` — `_mark_investigation_stopped_at_floor` 아래에 새 메서드, `run()`의 두 지점
- Test: `tests/workflow/deep_analysis/test_orchestrator_token_budget.py`

**Interfaces:**
- Consumes: 기존 `Orchestrator._mark_token_budget_exhausted()`, `_mark_investigation_stopped_at_floor()`, `self.token_budget`
- Produces: `Orchestrator._mark_stop_reason() -> None` (async)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_orchestrator_token_budget.py` 끝에 추가한다. 이 파일에는 이미 `FloorLedger`, `Grader`, `Synthesizer`, `CitationRenderer` 더블이 있다 — **먼저 파일 상단을 읽고 그 이름들을 그대로 재사용하라.** 아래 테스트는 `FloorLedger`가 `has_event`와 `events` 리스트를 제공한다는 전제로 쓰였다(같은 파일 149-197행의 기존 테스트가 그렇게 쓴다).

```python
@pytest.mark.asyncio
async def test_the_exception_path_does_not_call_the_stop_a_cap_exhaustion():
    """G9: 예외 경로가 사유를 독자 판정하던 것이 6건 중 4건을 오분류했다.

    `reserve` 는 캡 소진과 floor 정지 양쪽에 같은 `TokenBudgetExhausted` 를
    던진다(token_budget.py). 예외 타입은 사유를 말해주지 않으므로 예산의
    상태를 봐야 한다.
    """
    ledger = FloorLedger()
    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=100,
        finalization_floor_tokens=100,
    )
    await orchestrator._install_token_budget()

    # floor 가 캡 전체다 -> 조사 예산 0, 그러나 캡은 소진되지 않았다.
    assert orchestrator.token_budget.exhausted is False

    await orchestrator._mark_stop_reason()

    kinds = [event[0] for event in ledger.events]
    assert "investigation_stopped_at_floor" in kinds
    assert "token_budget_exhausted" not in kinds


@pytest.mark.asyncio
async def test_a_genuinely_exhausted_cap_is_still_reported_as_exhausted():
    """floor 정지와 캡 소진을 뭉개면 반대 방향의 거짓이 된다."""
    ledger = FloorLedger()
    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=100,
    )
    await orchestrator._install_token_budget()
    # 캡 전체를 소비한 것으로 만든다.
    orchestrator.token_budget._consumed_tokens = 100
    assert orchestrator.token_budget.exhausted is True

    await orchestrator._mark_stop_reason()

    kinds = [event[0] for event in ledger.events]
    assert "token_budget_exhausted" in kinds
    assert "investigation_stopped_at_floor" not in kinds


@pytest.mark.asyncio
async def test_a_normal_stop_records_no_budget_event():
    """열린 질문이 없어 멈춘 run은 예산 사건이 아니다.

    세 번째 분기를 두지 않는 것이 의도다 -- 정상 종료에 예산 이벤트를
    남기면 원장이 다시 거짓말을 시작한다.
    """
    ledger = FloorLedger()
    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=1_000_000,
    )
    await orchestrator._install_token_budget()

    await orchestrator._mark_stop_reason()

    kinds = [event[0] for event in ledger.events]
    assert "token_budget_exhausted" not in kinds
    assert "investigation_stopped_at_floor" not in kinds


@pytest.mark.asyncio
async def test_calling_the_stop_reason_twice_records_it_once():
    """예외 경로와 정상 경로가 연달아 부를 수 있다 -- 중복 적재는 안 된다."""
    ledger = FloorLedger()
    orchestrator = Orchestrator(
        object(),
        "run",
        worker_factory=lambda: None,
        grader=Grader(),
        ledger=ledger,
        synthesizer=Synthesizer(),
        citation_renderer=CitationRenderer(),
        global_token_cap=100,
        finalization_floor_tokens=100,
    )
    await orchestrator._install_token_budget()

    await orchestrator._mark_stop_reason()
    await orchestrator._mark_stop_reason()

    floor_events = [
        e for e in ledger.events if e[0] == "investigation_stopped_at_floor"
    ]
    assert len(floor_events) == 1
```

- [ ] **Step 2: 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_orchestrator_token_budget.py -q -k "stop_reason or exception_path or genuinely_exhausted or normal_stop"`
Expected: FAIL — `AttributeError: 'Orchestrator' object has no attribute '_mark_stop_reason'`

- [ ] **Step 3: `_mark_stop_reason()`을 추가한다**

`_mark_investigation_stopped_at_floor` 메서드 **바로 아래**에 넣는다.

```python
    async def _mark_stop_reason(self) -> None:
        """Record why investigation stopped, from the budget's state.

        The exception path used to assert "exhausted" on its own, and the
        normal path made a different decision from the same facts a few
        lines later -- two judgements of one question, disagreeing. Measured
        2026-08-04: 4 of 6 recorded stops were labelled `token_budget_
        exhausted` when the run had actually stopped at the floor with
        headroom left in the cap.

        `TokenBudget.reserve` raises the same `TokenBudgetExhausted` for
        both causes, so the exception type carries no information about
        which one happened. Only the budget's state does.

        There is deliberately no third branch: a run that stopped because
        no open question cleared `score_floor` has no budget event to
        record, and inventing one would put the ledger back to guessing.

        Both `_mark_*` helpers are idempotent (in-memory flag plus a
        `has_event` lookup), so calling this from both paths cannot
        double-log.
        """
        if self.token_budget.exhausted:
            await self._mark_token_budget_exhausted()
        elif (
            self.token_budget.available_for_investigation
            < self.token_budget.min_viable_output_tokens
        ):
            await self._mark_investigation_stopped_at_floor()
```

- [ ] **Step 4: 두 호출부를 교체한다**

`run()` 안, `except TokenBudgetExhausted:` 블록에서

```python
                except TokenBudgetExhausted:
                    await self._mark_token_budget_exhausted()
```

를 아래로 바꾼다.

```python
                except TokenBudgetExhausted:
                    await self._mark_stop_reason()
```

이어서 그 아래의 if/elif 블록 전체 — `if self.token_budget.exhausted:`부터
`await self._mark_investigation_stopped_at_floor()`까지, 사이의 주석 포함 — 을 아래 한 줄로 바꾼다.

```python
                await self._mark_stop_reason()
```

> 주의: 삭제하는 주석("Stopped at the floor with headroom left in the cap…")의 내용은 Step 3의 docstring에 이미 흡수돼 있다. 근거가 사라지는 것이 아니다.

- [ ] **Step 5: 테스트 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q`
Expected: PASS — 신규 4건 포함 전부. 특히 기존 `test_investigation_stopped_at_floor_is_recorded_once`가 그대로 통과해야 한다(정상 경로의 동작은 바뀌지 않는다).

- [ ] **Step 6: 가드가 실제로 잡는지 확인한다**

`_mark_stop_reason`의 `if/elif`를 일시적으로 `await self._mark_token_budget_exhausted()` 한 줄로 바꾸고 (= 수정 전 예외 경로의 동작) 테스트를 돌려 `test_the_exception_path_does_not_call_the_stop_a_cap_exhaustion`이 **실패**하는지 확인한 뒤 되돌린다. 두 결과를 모두 보고한다.

- [ ] **Step 7: 커밋**

```bash
git add neos/workflow/deep_analysis/orchestrator.py tests/workflow/deep_analysis/test_orchestrator_token_budget.py
git commit -m "fix(deep-analysis): decide the stop reason from the budget, not the path

The exception path asserted cap exhaustion on its own while the normal
path judged the same facts differently a few lines later. reserve raises
one exception type for both causes, so only the budget's state can tell
them apart -- 4 of 6 recorded stops were mislabelled."
```

---

## Task 2: 리포트 본문에 이름 있는 조회를 붙인다 (G4)

**Files:**
- Modify: `neos/workflow/deep_analysis/ledger.py` — `complete_run` 근처(파일 끝 쪽)에 새 메서드
- Modify: `neos/workflow/deep_analysis/analytics.py` — `DeepAnalysisAnalyticsService`에 새 메서드
- Test: `tests/workflow/deep_analysis/test_ledger_report_body.py` (신규)

**Interfaces:**
- Consumes: `DAEvent`, `JOB_COMPLETED`(= `"job_completed"`), 기존 payload 디코딩 관용구
- Produces:
  - `Ledger.report_markdown() -> str | None` (async)
  - `DeepAnalysisAnalyticsService.report_bodies(run_ids: Sequence[str]) -> dict[str, str]` (async)

**배경 (구현자가 알아야 할 것):** 리포트 본문은 **이미 보존돼 있다.** `jobs.py`가 run 완료 시 `job_completed` 이벤트 페이로드에 `report_markdown`을 통째로 싣는다(AC6: 늦게 접속한 구독자가 이벤트 재생만으로 리포트를 받게 하려고). `deep_analysis_runs.report_path` 컬럼은 항상 NULL이지만 그건 포인터가 없는 것이지 본문이 없는 것이 아니다. 이 태스크는 **본문을 꺼내는 이름 있는 경로**를 만들 뿐이고, `report_path` 컬럼과 `complete_run`의 시그니처는 **건드리지 않는다.**

`DAEvent.payload`는 배포에 따라 `str`(JSON)일 수도 `dict`일 수도 있다 — `ledger.py:169-176`의 기존 관용구가 두 경우를 모두 처리하며, 새 코드도 같은 방식을 쓴다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/workflow/deep_analysis/test_ledger_report_body.py`를 새로 만든다. 이 파일은 실제 DB를 쓴다. 관용구는 `tests/workflow/deep_analysis/test_deep_analysis_analytics.py`에서 확인한 것을 그대로 따른다 — **픽스처가 아니라 `async with await db_manager.get_session() as s:`이고, 각 테스트는 반드시 `await s.rollback()`으로 끝난다**(이 테스트들은 쓰기를 남기면 안 된다). `create_run(session, root_text, profile)`의 `profile`은 위치 인자다.

```python
"""리포트 본문은 job_completed 페이로드에 있다 -- report_path 컬럼이 아니라.

test_deep_analysis_analytics.py 와 같은 규율을 따른다: 실제 DB에 쓰고
각 테스트 끝에서 롤백한다. 남는 쓰기가 있으면 안 된다.
"""

import pytest

import neos.database.models  # noqa: F401 - register FK targets on Base
from neos.database.connection import db_manager
from neos.workflow.deep_analysis.analytics import DeepAnalysisAnalyticsService
from neos.workflow.deep_analysis.ledger import Ledger, create_run


@pytest.mark.asyncio
async def test_report_markdown_reads_the_completed_job_payload():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        await Ledger(s, run_id).log(
            "job_completed", None, {"report_markdown": "## 요약\n본문"}
        )

        assert await Ledger(s, run_id).report_markdown() == "## 요약\n본문"
        await s.rollback()


@pytest.mark.asyncio
async def test_report_markdown_is_none_before_the_run_completes():
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        await Ledger(s, run_id).log("job_started", None, {"profile": "dev"})

        assert await Ledger(s, run_id).report_markdown() is None
        await s.rollback()


@pytest.mark.asyncio
async def test_report_markdown_is_none_when_the_payload_has_no_body():
    """방어적으로 읽는다 -- 페이로드 모양이 바뀌어도 예외를 내지 않는다."""
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "루트 질문", "dev")
        await Ledger(s, run_id).log("job_completed", None, {"run_id": run_id})

        assert await Ledger(s, run_id).report_markdown() is None
        await s.rollback()


@pytest.mark.asyncio
async def test_report_bodies_reads_many_runs_in_one_query():
    """G3는 수백 run을 훑는다 -- 단건 조회를 루프로 돌리면 run 수만큼 왕복한다."""
    async with await db_manager.get_session() as s:
        first = await create_run(s, "질문 A", "dev")
        second = await create_run(s, "질문 B", "dev")
        third = await create_run(s, "질문 C", "dev")
        await Ledger(s, first).log(
            "job_completed", None, {"report_markdown": "리포트 A"}
        )
        await Ledger(s, second).log(
            "job_completed", None, {"report_markdown": "리포트 B"}
        )
        # third 는 완료되지 않았다.
        await Ledger(s, third).log("job_started", None, {"profile": "dev"})

        bodies = await DeepAnalysisAnalyticsService(s).report_bodies(
            [first, second, third]
        )

        assert bodies == {first: "리포트 A", second: "리포트 B"}
        await s.rollback()


@pytest.mark.asyncio
async def test_report_bodies_returns_empty_for_no_run_ids():
    """빈 입력에서 질의를 아예 내지 않는다 -- IN () 은 DB마다 다르게 군다."""
    async with await db_manager.get_session() as s:
        assert await DeepAnalysisAnalyticsService(s).report_bodies([]) == {}
        await s.rollback()
```

- [ ] **Step 2: 실패를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis/test_ledger_report_body.py -q`
Expected: FAIL — `AttributeError: 'Ledger' object has no attribute 'report_markdown'`

- [ ] **Step 3: `Ledger.report_markdown()`을 추가한다**

`ledger.py`의 `complete_run` 메서드 **바로 위**에 넣는다.

```python
    async def report_markdown(self) -> str | None:
        """This run's final report body, or ``None`` if there isn't one yet.

        Read from the `job_completed` event payload -- NOT from the
        `deep_analysis_runs.report_path` column, which is always NULL. The
        body has been persisted since the job service landed: `jobs.py`
        puts it in that payload so a late subscriber replaying the event
        stream receives the report without a second request (AC6). The
        column is a missing pointer, not a missing body.

        Returns ``None`` for a run that failed or has not finished, and for
        a payload that carries no `report_markdown` key -- callers get one
        answer for "no report", not an exception to distinguish.
        """
        raw = await self.db.scalar(
            select(DAEvent.payload)
            .where(
                DAEvent.run_id == self.run_id,
                DAEvent.kind == "job_completed",
            )
            .order_by(DAEvent.seq.desc())
            .limit(1)
        )
        if raw is None:
            return None
        try:
            payload = raw if isinstance(raw, dict) else json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        body = payload.get("report_markdown")
        return body if isinstance(body, str) else None
```

> `select`, `DAEvent`, `json`은 `ledger.py`가 이미 임포트하고 있다 — 새 임포트를 추가하지 말고 확인만 하라.

- [ ] **Step 4: `report_bodies()` 배치 조회를 추가한다**

`analytics.py`의 `DeepAnalysisAnalyticsService`에, `_payload` 정적 메서드 아래에 넣는다. 파일 상단 임포트에 `Sequence`가 없으면 `from collections.abc import Sequence`를 추가한다.

```python
    async def report_bodies(
        self, run_ids: Sequence[str]
    ) -> dict[str, str]:
        """Map run_id -> final report body, for the runs that have one.

        The batch form exists because report-gate recalibration walks
        hundreds of runs at once; looping `Ledger.report_markdown()` would
        cost one round trip per run. Runs with no completed job -- or a
        payload without a body -- are simply absent from the result rather
        than mapping to None, so callers iterate what exists.
        """
        if not run_ids:
            return {}
        result = await self.db.execute(
            select(DAEvent.run_id, DAEvent.payload).where(
                DAEvent.run_id.in_(list(run_ids)),
                DAEvent.kind == "job_completed",
            )
        )
        bodies: dict[str, str] = {}
        for run_id, raw in result.all():
            payload = (
                raw if isinstance(raw, dict) else self._payload(raw)
            )
            if not isinstance(payload, dict):
                continue
            body = payload.get("report_markdown")
            if isinstance(body, str):
                bodies[run_id] = body
        return bodies
```

- [ ] **Step 5: 테스트 통과를 확인한다**

Run: `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q`
Expected: PASS — 신규 5건 포함 전부

- [ ] **Step 6: 커밋**

```bash
git add neos/workflow/deep_analysis/ledger.py neos/workflow/deep_analysis/analytics.py tests/workflow/deep_analysis/test_ledger_report_body.py
git commit -m "feat(deep-analysis): give the report body a named read path

The roadmap read report_path being NULL as the body being lost. It is
not: jobs.py has been putting the whole report in the job_completed
payload since the job service landed, and every run goes through that
path. What was missing is a way to ask for it."
```

---

## Task 3: 실패를 프론트엔드 상태에 남긴다 (FE1)

**Files:**
- Modify: `web/lib/deep-analysis/progress.ts`
- Test: `web/tests/source/deep-analysis-progress.test.ts`

**Interfaces:**
- Consumes: 기존 `DeepAnalysisProgress`, `activityLabel()`, `reduceDeepAnalysisEvent()`
- Produces:
  - `export type DegradationEntry = { kind: string; count: number }`
  - `DeepAnalysisProgress.degradations: DegradationEntry[]`

**배경:** `activityLabel()`이 반환하는 문자열은 `lastActivity` 하나로 접히고 다음 이벤트가 오면 덮어써진다. 그래서 라벨만 추가하면 강등이 스쳐 지나가고 run이 끝나면 흔적이 없다 — 로드맵 §5.2가 지적한 "사용자는 리포트가 템플릿으로 강등된 것을 알 수 없다"가 그대로 남는다.

**강등 판정 기준은 "리포트가 사용자가 받았어야 할 것보다 못한가"이다.** 🔴 3종만 누적하고 🟡 4종은 라벨만 붙인다. `llm_truncated`가 🟡인 이유: 확장 재시도가 성공하면 최종 산출물에 영향이 없고, 가르려면 `truncation_handled.action`과 상관시켜야 하는데 그 상태 기계는 범위를 넘는다. **과소 보고를 택한다.**

**`report_graded`는 새 kind 추가가 아니라 기존 분기 수정이다.** `judge_budget_exhausted`는 이벤트 kind가 아니라 `report_graded` 페이로드의 `diagnostics.judge` 값이다(`"budget_exhausted"` / `"truncated"` / `"unparseable"`). 현재 분기는 `payload.ok`만 보므로 판정자가 굶어서 통과한 리포트와 실제로 승인된 리포트가 같은 문구를 낸다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`web/tests/source/deep-analysis-progress.test.ts` 끝에 추가한다. **이 파일은 vitest가 아니라 `node:test` + `node:assert/strict`를 쓴다** — `expect()`가 아니라 `assert.deepEqual` / `assert.equal` / `assert.notEqual`이다. 파일 상단에 이미 두 헬퍼가 있으니 그대로 재사용한다:

```ts
const event = (seq, kind, payload = {}) => ({ seq, kind, payload });
const applyAll = (events) => events.reduce(reduceDeepAnalysisEvent, initialDeepAnalysisProgress());
```

```ts
test("리포트 품질을 깎은 사건은 뒤따르는 이벤트가 덮어쓰지 않는다", () => {
  const state = applyAll([
    event(1, "node_reduction_degraded", { reason: "token_budget_exhausted" }),
    event(2, "node_reduction_degraded", { reason: "token_budget_exhausted" }),
    event(3, "report_assembly_degraded", { reason: "token_budget_exhausted" }),
    event(4, "claim_verified"),
  ]);

  assert.deepEqual(state.degradations, [
    { kind: "node_reduction_degraded", count: 2 },
    { kind: "report_assembly_degraded", count: 1 },
  ]);
  // lastActivity 는 덮어써졌지만 degradations 는 남았다 -- 이 대비가 요점이다.
  assert.equal(state.lastActivity, "클레임 검증됨");
});

test("조사 범위만 깎은 사건은 라벨은 붙되 강등으로 세지 않는다", () => {
  const state = applyAll([
    event(1, "investigation_stopped_at_floor", { floor_tokens: 41040 }),
    event(2, "claim_discarded"),
    event(3, "llm_truncated", { stage: "worker_analysis" }),
    event(4, "entailment_filter_skipped"),
  ]);

  assert.deepEqual(state.degradations, []);
  assert.notEqual(state.lastActivity, null);
});

test("클램프가 허용량 안에 들어갔으면 강등이 아니다", () => {
  const fitted = applyAll([
    event(1, "finalization_prompt_clamped", {
      exhausted: false,
      stage: "report_assembly",
    }),
  ]);
  assert.deepEqual(fitted.degradations, []);

  const overflowed = applyAll([
    event(1, "finalization_prompt_clamped", {
      exhausted: true,
      stage: "report_assembly",
    }),
  ]);
  assert.deepEqual(overflowed.degradations, [
    { kind: "finalization_prompt_clamped", count: 1 },
  ]);
});

test("굶은 판정자가 통과시킨 리포트는 승인된 리포트와 다르게 말한다", () => {
  const approved = applyAll([event(1, "report_graded", { ok: true })]);
  const starved = applyAll([
    event(1, "report_graded", { ok: true, judge: "budget_exhausted" }),
  ]);

  assert.equal(approved.lastActivity, "리포트 채점 통과");
  assert.notEqual(starved.lastActivity, "리포트 채점 통과");
  assert.ok(starved.lastActivity?.includes("판정자"));
});

test("새 실패 이벤트 전부가 라벨을 가진다", () => {
  const kinds = [
    "report_assembly_degraded",
    "node_reduction_degraded",
    "finalization_prompt_clamped",
    "investigation_stopped_at_floor",
    "llm_truncated",
    "truncation_handled",
    "entailment_filter_skipped",
    "claim_discarded",
  ];
  for (const kind of kinds) {
    const state = applyAll([event(1, kind)]);
    assert.notEqual(state.lastActivity, null, `${kind} 에 라벨이 없다`);
  }
});

test("모르는 kind는 여전히 커서를 전진시킨다", () => {
  const state = applyAll([event(7, "a_kind_from_the_future")]);
  assert.equal(state.cursor, 7);
  assert.equal(state.lastActivity, null);
  assert.deepEqual(state.degradations, []);
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `pnpm --dir web test:source 2>&1 | grep -i "deep-analysis-progress"`
Expected: FAIL — `degradations`가 `undefined`

- [ ] **Step 3: 타입과 초기 상태를 확장한다**

`progress.ts`의 `DeepAnalysisProgress` 타입에서 `idleTimedOut` 필드 **위에** 추가한다.

```ts
  /**
   * 리포트 품질을 깎은 사건들. `lastActivity`와 달리 덮어써지지 않는다 —
   * 강등은 run이 끝난 뒤에도 남아야 하는 상태이기 때문이다.
   *
   * `kind`는 원장의 어휘 그대로 싣고 사람이 읽는 문구는 렌더 시점에
   * 만든다. 문구를 상태에 넣으면 재생된 옛 이벤트가 옛 문구를 고착시킨다.
   */
  degradations: DegradationEntry[];
```

같은 파일, `DeepAnalysisProgress` 타입 정의 **바로 위**에 추가한다.

```ts
/** 같은 kind가 여러 번 나면 count로 집계한다 — 3회와 1회는 다른 이야기다. */
export type DegradationEntry = { kind: string; count: number };
```

`initialDeepAnalysisProgress`의 반환 객체에서 `idleTimedOut: false,` **위에** 추가한다.

```ts
    degradations: [],
```

- [ ] **Step 4: 라벨 7종과 `report_graded` 분기 수정을 넣는다**

`activityLabel()` 안, `if (kind === "report_graded") { ... }` 블록 전체를 아래로 바꾼다.

```ts
  if (kind === "report_graded") {
    if (payload.ok !== true) {
      return "리포트 채점 재시도";
    }
    // `judge_budget_exhausted`는 이벤트 kind가 아니다 — 판정자가 굶었다는
    // 사실은 이 페이로드의 diagnostics.judge 로만 남는다
    // (graders/report.py). `ok`만 보면 굶은 판정자의 통과와 실제 승인이
    // 같은 문구를 내고, 그것이 이 항목의 실제 결함이었다.
    const judge = asString(payload.judge);
    if (judge === "budget_exhausted") {
      return "리포트 채점 통과 (판정자 예산 소진 — 실제 심사 없음)";
    }
    if (judge === "truncated") {
      return "리포트 채점 통과 (판정자 응답 잘림 — 실제 심사 없음)";
    }
    if (judge === "unparseable") {
      return "리포트 채점 통과 (판정자 응답 해석 실패 — 실제 심사 없음)";
    }
    return "리포트 채점 통과";
  }
```

이어서, `if (kind === JOB_STARTED)` 블록 **바로 위**에 새 라벨들을 넣는다.

```ts
  if (kind === "report_assembly_degraded") {
    return "리포트가 템플릿으로 강등됨 (조립 예산 부족)";
  }
  if (kind === "node_reduction_degraded") {
    return "하위 요약 강등 — 자식 답변 이어붙임";
  }
  if (kind === "finalization_prompt_clamped") {
    return payload.exhausted === true
      ? "마무리 프롬프트가 허용량을 넘음 — 내용이 잘림"
      : "마무리 프롬프트 축소됨";
  }
  if (kind === "investigation_stopped_at_floor") {
    return "조사 중단 — 마무리 예산만 남음";
  }
  if (kind === "llm_truncated") {
    const stage = asString(payload.stage);
    return stage ? `응답 잘림 · ${stage}` : "응답 잘림";
  }
  if (kind === "truncation_handled") {
    return payload.action === "retried_ok"
      ? "응답 잘림 — 재시도 성공"
      : "응답 잘림 — 복구 실패";
  }
  if (kind === "entailment_filter_skipped") {
    return "함의 필터 건너뜀";
  }
  if (kind === "claim_discarded") {
    return "클레임 폐기됨";
  }
```

- [ ] **Step 5: 강등 누적 로직을 넣는다**

`activityLabel` 함수 **바로 아래**에 헬퍼를 넣는다.

```ts
/**
 * 이 이벤트가 리포트를 사용자가 받았어야 할 것보다 못하게 만들었는가.
 *
 * 조사 범위나 검증 강도를 깎은 것(`investigation_stopped_at_floor`,
 * `claim_discarded` 등)은 여기 들지 않는다 — 리포트 자체는 주어진 재료로
 * 낼 수 있는 최선이기 때문이다. `llm_truncated`도 마찬가지다: 확장 재시도가
 * 성공하면 산출물에 영향이 없고, 실패한 경우만 가르려면 `truncation_handled`와
 * 상관시켜야 한다. 잘못된 경고보다 과소 보고를 택한다.
 */
function degradedReport(event: DeepAnalysisJobEvent): boolean {
  const { kind, payload } = event;
  if (kind === "report_assembly_degraded") return true;
  if (kind === "node_reduction_degraded") return true;
  if (kind === "finalization_prompt_clamped") return payload.exhausted === true;
  return false;
}

/** 최초 발생 순서를 보존하며 같은 kind를 count로 합친다. */
function withDegradation(
  entries: DegradationEntry[],
  kind: string
): DegradationEntry[] {
  const index = entries.findIndex((entry) => entry.kind === kind);
  if (index === -1) {
    return [...entries, { kind, count: 1 }];
  }
  return entries.map((entry, i) =>
    i === index ? { ...entry, count: entry.count + 1 } : entry
  );
}
```

그리고 `reduceDeepAnalysisEvent`가 새 상태를 만드는 지점 — `lastActivity: activityLabel(event) ?? state.lastActivity,`가 있는 객체 리터럴 — 에 한 줄 더한다.

```ts
    degradations: degradedReport(event)
      ? withDegradation(state.degradations, event.kind)
      : state.degradations,
```

- [ ] **Step 6: 테스트 통과를 확인한다**

Run: `pnpm --dir web test:source`
Expected: PASS — 신규 6건 포함 전부 (기준선 147 + 6)

Run: `pnpm --dir web exec tsc --noEmit`
Expected: 출력 없음

- [ ] **Step 7: 커밋**

```bash
git add web/lib/deep-analysis/progress.ts web/tests/source/deep-analysis-progress.test.ts
git commit -m "feat(web): surface the harness failures the UI was silent about

Labels for the seven failure kinds the reducer did not know, plus a
degradations list that -- unlike lastActivity -- is not overwritten by
the next event, because a downgraded report is a state that outlives the
run. report_graded also stops calling a starved judge's pass an approval."
```

---

## Task 4: 로드맵과 결정 원장을 갱신한다

**Files:**
- Modify: `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md`
- Modify: `neos/workflow/deep_analysis/DECISIONS.md`

**Interfaces:**
- Consumes: Task 1–3의 완료 상태와 커밋 해시
- Produces: 없음 (문서)

- [ ] **Step 1: 결정 번호를 확인한다**

Run: `rg -n "^## D2[4-9]" neos/workflow/deep_analysis/DECISIONS.md`
Expected: D25가 최고 번호 (W1의 floor 분할). 그렇지 않으면 실제 최고값 + 1을 쓰고 보고한다.

> W1 때 브리프가 "D24"를 지시했으나 이미 사용 중이어서 D25가 됐다. 번호를 가정하지 말고 반드시 확인하라.

- [ ] **Step 2: `DECISIONS.md`에 D26을 추가한다**

파일 끝에 기존 D 항목과 같은 형식으로 추가한다. 담을 내용:

- **D26 — 정지 사유는 예산 상태가 정한다. 리포트 본문의 정본은 `job_completed`다.**
- G9: 판정 코드가 정상 경로와 예외 경로에 두 벌 있었고 서로 달랐다. `reserve`가 두 사유에 같은 예외를 던지므로 예외 타입은 사유를 말하지 않는다. `_mark_stop_reason()` 하나로 접었다. 실측 6건 중 4건 오분류 → 0.
- G4: **로드맵의 전제를 정정한다.** `report_path`가 NULL인 것은 사실이나 본문이 유실된 적은 없다 — `jobs.py`가 `job_completed` 페이로드에 싣고(AC6), `neos/`에서 `orchestrator.run()`의 호출자는 `jobs.py` 하나뿐이다. 컬럼은 채우지도 은퇴시키지도 않고 조회 경로만 만들었다.
- FE1: 강등 판정 기준은 "리포트 내용을 깎았는가". `llm_truncated`는 재시도 성공 시 영향이 없어 제외 — 과소 보고를 택했다.
- 발견: `judge_budget_exhausted`는 이벤트 kind가 아니라 `report_graded.diagnostics.judge` 값이다. FE의 결함은 라벨 누락이 아니라 굶은 판정자의 통과를 승인과 같은 문구로 낸 것이었다.

- [ ] **Step 3: 로드맵 §2.2의 S3·S4를 갱신한다**

S3 행의 「측정 방법」을 `reports 테이블`에서 **`job_completed` 페이로드에 `report_markdown`이 실린 비율**로 바꾸고, 「현재」를 ❌에서 ✅로 바꾼다(본문은 이미 보존돼 있으므로). S4 행의 「현재」를 ⚠️에서 ✅로 바꾼다(G9 해소).

> 정직성 주의: S1(`synth_pass ≥ 1`)은 **여전히 ❌다.** 라이브 표본이 아직 실행되지 않았다. 건드리지 말 것.

- [ ] **Step 4: 로드맵 §5.2 표와 §7 인벤토리를 갱신한다**

§5.2의 이벤트 표에서 「FE 라벨」 칸을 ❌에서 ✅로 바꾸고, `judge_budget_exhausted` 행에는 **이벤트 kind가 아니라 `report_graded.diagnostics.judge`**라는 사실을 적는다.

§7 인벤토리에서 G9·G4·FE1 세 행을 제거하고 §3.5 「최근 해소된 것」 표에 옮긴다. 커밋 해시는 `git log --oneline -6`으로 확인해 채운다.

- [ ] **Step 5: 로드맵 §8 W2에 판정 상태를 적는다**

W2 절 끝에 추가한다. G4의 전제 정정을 명시할 것.

```markdown
**2026-08-07 완료.** G9는 `_mark_stop_reason()` 단일 판정으로, FE1은 라벨 7종 +
`report_graded` 분기 수정 + `degradations` 누적으로 해소했다.

**G4는 전제가 틀려 있었다** — `report_path`가 NULL인 것은 사실이나 리포트 본문은
`job_completed` 페이로드에 계속 보존돼 있었다(`jobs.py`, AC6). 컬럼을 채우는 대신
`Ledger.report_markdown()`과 `DeepAnalysisAnalyticsService.report_bodies()`를 만들어
G3가 표본 전체의 본문을 읽을 수 있게 했다. §2.2 S3의 측정법도 이에 맞춰 정정했다.
```

- [ ] **Step 6: 커밋**

```bash
git add docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md neos/workflow/deep_analysis/DECISIONS.md
git commit -m "docs(deep-analysis): record W2 and correct the report-body premise

G4 was written against a false premise: report_path being NULL was read
as the body being lost. It never was. S3's measurement changes with it."
```

---

## 완료 기준

- Task 1–4의 모든 스텝 체크
- `HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q` 통과
- `.venv/bin/python -m pytest -q` — 2,390 이상 passed / **0 failed**
- `pnpm --dir web test:source` — 147 이상 passed / 0 failed
- `pnpm --dir web exec tsc --noEmit` 무출력
- `.venv/bin/ruff check neos/ tests/workflow/deep_analysis/` — 손댄 파일 clean

**변하지 않는 것:** 로드맵 §2.2의 **S1은 ❌로 유지**한다. `synth_pass ≥ 1`은 라이브 표본이 필요하고 그 실행은 아직 없다. W2는 S3·S4·S6을 채울 뿐 S1을 채우지 않는다.

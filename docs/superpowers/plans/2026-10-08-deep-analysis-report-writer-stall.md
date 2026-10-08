# 하네스 ReportWriter·StallTracker 추출 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 하네스 `Orchestrator` 에서 리포트 작성(`ReportWriter`)과 정체 판정(`StallTracker`)을 깊은 모듈로 꺼내, 테스트가 그 공개 인터페이스를 겨누게 한다 — 행동 변경 없이.

**Architecture:** 리포트 작성 코드(~215줄 + 헬퍼)를 `report_writer.py` 로 글자 그대로 옮기고 `_finalize` 는 축약·재조사 뒤 위임만 한다. 정체 카운터·정책은 부수효과 없는 `stall.py` 로, 부수효과(원장·이벤트·분할·예외)는 Orchestrator 에 남긴다. 옮김의 동등성은 과도기 대조 테스트로 고정한 뒤 지운다.

**Tech Stack:** Python 3.12, pytest(asyncio), uv, ruff.

**Spec:** `docs/superpowers/specs/2026-10-08-deep-analysis-report-writer-stall-design.md`

## Global Constraints

- 순수 리팩터링: 원장 이벤트(종류·순서·페이로드), 리포트 문자열, 예외, DB 읽기 패턴을 바꾸지 않는다.
- 범위 밖: 트리·라운드 진행(`_run_round` 본문의 정체 호출 외), `_run_worker`, 정지 사유·예산, `Orchestrator.__new__` 를 쓰는 두 테스트 파일.
- 단언 규칙: 기댓값·의미는 바꾸지 않는다. 대상 식은 사라진 private 에서 같은 값을 돌려주는 공개 인터페이스로 옮길 수 있고, 그런 곳은 보고서에 하나하나 적는다. 기댓값까지 바뀌어야 하면 멈추고 보고한다.
- 옮기는 코드의 import(함수 안 지연 import 포함)는 글자 그대로 옮긴다. 옮긴 이름을 `monkeypatch.setattr(<모듈>, …)` 하는 테스트는 패치 대상을 새 모듈로 바꾼다.
- 검증은 테스트 **이름**으로. `-o addopts=""` 금지, `-p no:randomly` 사용. 결과 줄은 `^(PASSED|FAILED|ERROR|XPASS|XFAIL) \S+::` 로만 거른다.
- 브랜치 `refactor/deep-analysis-report-writer`(dev 555eb444 기준). 커밋 메시지에 Co-Authored-By 트레일러 금지.

## Review Focus

1. **compose 자식 경로의 원장 이벤트** — code_worker_* 이벤트 순서·페이로드가 옮긴 뒤에도 같아야 한다. → Task 2 과도기 대조의 compose 시나리오.
2. **캡 소진 실패 부록** — 렌더된 최선 초안 + 부록, `complete_run` 1회. → Task 2 과도기 대조의 캡 소진 시나리오.
3. **정체 판정의 원장 읽기 순서** — 토큰이 늘었으면 `verified_claims`·`feedback_count` 를 읽지 않는다. → Task 1 `test_made_progress_stops_reading_once_tokens_moved`.
4. **모듈 패치의 조용한 무효화** — `resolve_conflicts` 패치 3곳이 옮긴 뒤에도 효과가 있어야 한다. → Task 3 Step 4 의 "패치가 실제로 불렸는지" 확인.
5. **시스템 실패 라운드 리셋** — 실패 아닌 결과가 하나라도 있으면 연속 수가 0 으로. → Task 1 `test_record_round_resets_on_any_non_failure`.

---

## 공통: 경로와 명령

```bash
cd /Users/ywsung/Desktop/neos
SCRATCH=<controller 가 dispatch 때 준다>   # 기준선 파일 디렉터리
T=tests/workflow/deep_analysis
```

---

### Task 0: 기준선 (controller)

- [ ] 이름: `uv run pytest $T --collect-only -qq | grep '::' | sort > $SCRATCH/names_before.txt` (2026-10-08: 1199)
- [ ] 결과: `uv run pytest $T -q -rA -p no:randomly > $SCRATCH/run_before.txt 2>&1`; `grep -E '^(PASSED|FAILED|ERROR|XPASS|XFAIL) \S+::' … | sort > $SCRATCH/outcomes_before.txt`
- [ ] 지표(`$SCRATCH/metrics_before.txt`):
```bash
echo "finalize $(grep -rnoE '\borch(estrator)?\._finalize\(' tests | wc -l)"          # 27
echo "stall $(grep -rnoE '\borch(estrator)?\.(_stall_counts|_register_progress|_made_progress|_register_round_outcome|_force_terminate_stalled|_all_failed_rounds)\b' tests | wc -l)"   # 18
echo "postset $(grep -rnE '\borch(estrator)?\.(sandbox_provider|compose_runtime_factory|max_stall_rounds)\s*=[^=]' tests | wc -l)"   # 9
echo "orch_privates $(grep -rnoE '\borch(estrator)?\._[a-z][a-z0-9_]*' tests | wc -l)"   # 121
```

---

### Task 1: `StallTracker` 와 정체 판정 함수, 그리고 정체 테스트 이주

**Files:**
- Create: `neos/workflow/deep_analysis/stall.py`
- Modify: `neos/workflow/deep_analysis/orchestrator.py` (`__init__` 의 `_stall_counts`·`_all_failed_rounds`, `_verified_count`·`_feedback_signal`·`_made_progress`·`_register_progress`·`_force_terminate_stalled`·`_register_round_outcome`, `_run_round` 의 1449-1452·1532-1540행 근처)
- Test: `tests/workflow/deep_analysis/test_stall.py` (create)
- Modify tests: `test_commit_pass_explore_brief.py`(2 테스트), `test_orchestrator_run_worker.py`(`test_non_failed_worker_result_resets_systemic_failure_rounds`), `test_subagent_adapter.py`(`_force_terminate_stalled` 테스트)

**Interfaces:**
- Produces (`neos.workflow.deep_analysis.stall`): `Progress(spent_tokens: int, verified: int | None, feedback: int | None)` (frozen dataclass); `async snapshot(ledger, question) -> Progress`; `async made_progress(ledger, question_id, before: Progress) -> bool`; `StallTracker(max_rounds: int)` with `record(question_id, made_progress) -> bool`, `count(question_id) -> int`, `clear(question_id) -> None`, `record_round(all_failed: bool) -> int | None`.
- Produces (`Orchestrator`): 생성자 키워드 `stall_tracker: StallTracker | None = None`; 속성 `self.stall`.

- [ ] **Step 1: 실패하는 테스트**

`tests/workflow/deep_analysis/test_stall.py`:
```python
"""Stall policy (D15): counting is pure; the Orchestrator acts on the verdict."""

from types import SimpleNamespace

import pytest

from neos.workflow.deep_analysis.stall import (
    Progress,
    StallTracker,
    made_progress,
    snapshot,
)

pytestmark = pytest.mark.no_db


class _Ledger:
    def __init__(self, spent=0, verified=0, feedback=0):
        self.question = SimpleNamespace(id="q1", spent_tokens=spent)
        self.verified = verified
        self.feedback = feedback
        self.reads: list[str] = []

    async def get_question(self, qid):
        self.reads.append("get_question")
        return self.question

    async def verified_claims(self, qid):
        self.reads.append("verified_claims")
        return [object()] * self.verified

    async def feedback_count(self, qid):
        self.reads.append("feedback_count")
        return self.feedback


class _MinimalLedger:
    async def get_question(self, qid):
        return SimpleNamespace(id=qid, spent_tokens=0)


def test_record_counts_no_progress_and_reports_the_cap() -> None:
    tracker = StallTracker(max_rounds=2)

    assert tracker.record("q1", False) is False
    assert tracker.record("q1", False) is True
    assert tracker.count("q1") == 2


def test_progress_resets_the_count() -> None:
    tracker = StallTracker(max_rounds=3)
    tracker.record("q1", False)

    assert tracker.record("q1", True) is False
    assert tracker.count("q1") == 0


def test_clear_forgets_a_question() -> None:
    tracker = StallTracker(max_rounds=3)
    tracker.record("q1", False)
    tracker.clear("q1")

    assert tracker.count("q1") == 0
    assert tracker.count("unknown") == 0


def test_record_round_resets_on_any_non_failure() -> None:
    tracker = StallTracker(max_rounds=2)

    assert tracker.record_round(all_failed=True) is None
    assert tracker.record_round(all_failed=False) is None
    assert tracker.record_round(all_failed=True) is None
    assert tracker.record_round(all_failed=True) == 2


def test_failed_rounds_reads_the_streak() -> None:
    tracker = StallTracker(max_rounds=5)
    tracker.record_round(all_failed=True)
    tracker.record_round(all_failed=True)

    assert tracker.failed_rounds == 2


@pytest.mark.asyncio
async def test_snapshot_reads_tokens_from_the_question_and_signals_from_the_ledger() -> None:
    ledger = _Ledger(verified=2, feedback=1)

    before = await snapshot(ledger, SimpleNamespace(id="q1", spent_tokens=7))

    assert before == Progress(spent_tokens=7, verified=2, feedback=1)
    assert ledger.reads == ["verified_claims", "feedback_count"]


@pytest.mark.asyncio
async def test_made_progress_stops_reading_once_tokens_moved() -> None:
    ledger = _Ledger(spent=5)

    assert await made_progress(ledger, "q1", Progress(0, 0, 0)) is True
    assert ledger.reads == ["get_question"]


@pytest.mark.asyncio
async def test_no_new_signal_is_no_progress() -> None:
    ledger = _Ledger(spent=0, verified=1, feedback=0)

    assert await made_progress(ledger, "q1", Progress(0, 1, 0)) is False
    assert ledger.reads == ["get_question", "verified_claims", "feedback_count"]


@pytest.mark.asyncio
async def test_unknown_signals_count_as_progress() -> None:
    assert await made_progress(_MinimalLedger(), "q1", Progress(0, None, None)) is True
    assert await snapshot(_MinimalLedger(), SimpleNamespace(id="q1", spent_tokens=0)) == Progress(0, None, None)
```

- [ ] **Step 2: 실패 확인** — `uv run pytest $T/test_stall.py -q -p no:randomly` → `ModuleNotFoundError: neos.workflow.deep_analysis.stall`

- [ ] **Step 3: `stall.py` 를 쓴다**

```python
"""D15 stall policy: when a question has stopped moving, and when a whole run has.

The tracker only counts and decides. What a stall *does* -- the ledger line,
the event, cancelling the child, splitting the question, `SystemicWorkerFailure`
-- stays with the Orchestrator, which acts on the verdict. The counts are
in-memory: a resumed run starts them at zero, as it always has.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Progress:
    """A question's progress signals at one moment. `None` = the ledger cannot say."""

    spent_tokens: int
    verified: int | None
    feedback: int | None


async def _verified_count(ledger, question_id: str) -> int | None:
    fn = getattr(ledger, "verified_claims", None)
    if fn is None:
        return None
    return len(await fn(question_id))


async def _feedback_signal(ledger, question_id: str) -> int | None:
    fn = getattr(ledger, "feedback_count", None)
    if fn is None:
        return None
    return await fn(question_id)


async def snapshot(ledger, question) -> Progress:
    """The signals before a pass mutates anything."""
    return Progress(
        spent_tokens=question.spent_tokens,
        verified=await _verified_count(ledger, question.id),
        feedback=await _feedback_signal(ledger, question.id),
    )


async def made_progress(ledger, question_id: str, before: Progress) -> bool:
    """A pass made progress iff it produced a new verified claim, new rejection
    feedback, or burned tokens. An inert pass (partial with 0 tokens/0 claims,
    or a mismatch-skipped assignment) fails all three. Unavailable signals
    (limited fakes) count as progress -> no stall. Reads stop at the first
    signal that moved."""
    question = await ledger.get_question(question_id)
    spent_after = question.spent_tokens if question is not None else before.spent_tokens
    if spent_after > before.spent_tokens:
        return True
    verified_after = await _verified_count(ledger, question_id)
    if before.verified is None or verified_after is None or verified_after > before.verified:
        return True
    feedback_after = await _feedback_signal(ledger, question_id)
    if before.feedback is None or feedback_after is None or feedback_after > before.feedback:
        return True
    return False


class StallTracker:
    """Consecutive no-progress passes per question, and consecutive all-failed rounds."""

    def __init__(self, max_rounds: int) -> None:
        self.max_rounds = max_rounds
        self._counts: dict[str, int] = {}
        self._all_failed_rounds = 0

    def record(self, question_id: str, made_progress: bool) -> bool:
        """Count one pass. True when this question just reached the cap."""
        if made_progress:
            self._counts[question_id] = 0
            return False
        count = self._counts.get(question_id, 0) + 1
        self._counts[question_id] = count
        return count >= self.max_rounds

    def count(self, question_id: str) -> int:
        return self._counts.get(question_id, 0)

    @property
    def failed_rounds(self) -> int:
        return self._all_failed_rounds

    def clear(self, question_id: str) -> None:
        self._counts[question_id] = 0

    def record_round(self, all_failed: bool) -> int | None:
        """Count one round. The streak length once it reaches the cap, else None."""
        if not all_failed:
            self._all_failed_rounds = 0
            return None
        self._all_failed_rounds += 1
        if self._all_failed_rounds < self.max_rounds:
            return None
        return self._all_failed_rounds
```
`_made_progress`(orchestrator.py ~1275행)의 본문·독스트링과 대조해 판정 순서가 같은지 확인한다.

Run: `uv run pytest $T/test_stall.py -q -p no:randomly` → 9 passed

- [ ] **Step 4: Orchestrator 를 tracker 위로 옮긴다**

`orchestrator.py`:
- import: `from neos.workflow.deep_analysis.stall import StallTracker, made_progress, snapshot`
- `__init__` 키워드에 `stall_tracker: StallTracker | None = None` 를 더한다(`compose_runtime_factory` 뒤). `self.max_stall_rounds` 를 정한 **뒤**에 `self.stall = stall_tracker if stall_tracker is not None else StallTracker(self.max_stall_rounds)`. `self._stall_counts = {}` 와 `self._all_failed_rounds = 0` 를 지운다.
- `_verified_count`, `_feedback_signal`, `_made_progress` 메서드를 지운다.
- `_register_progress`:
```python
    async def _register_progress(self, question_id: str, made_progress: bool) -> None:
        """D15 stall safety valve: track consecutive no-progress passes and
        force-terminate at the cap so a livelocked question cannot spin to the
        global token cap."""
        if self.stall.record(question_id, made_progress):
            await self._force_terminate_stalled(question_id)
```
- `_force_terminate_stalled`: `rounds = self._stall_counts.get(question_id, 0)` → `rounds = self.stall.count(question_id)`, `self._stall_counts[question_id] = 0` → `self.stall.clear(question_id)`. 나머지 그대로.
- `_register_round_outcome`:
```python
        if not results:
            return
        rounds = self.stall.record_round(
            all(result.status == "failed" for result in results)
        )
        if rounds is None:
            return

        reasons = [(result.fail_reason or "unknown")[:200] for result in results]
        payload = {
            "rounds": rounds,
            "reasons": reasons,
        }
        ...  # log / emit / checkpoint 그대로
        raise SystemicWorkerFailure(
            f"all workers failed for {rounds} consecutive rounds"
        )
```
- `_run_round` 의 "전" 스냅숏(1449-1452행 근처): `spent_before`·`verified_before`·`feedback_before` 세 줄을 `before = await snapshot(self.ledger, question)` 한 줄로. (`question` 은 그 위에서 이미 읽은 객체다 — `value_est = question.value_est` 가 쓰는 그것.)
- 판정(1532행 근처): `made_progress = await self._made_progress(assignment.question_id, spent_before, verified_before, feedback_before)` → `progressed = await made_progress(self.ledger, assignment.question_id, before)`, 이어지는 `if result.subagent_step_kind == "continuing": progressed = True`, `await self._register_progress(assignment.question_id, progressed)`. (지역 변수 이름이 import 한 함수 `made_progress` 를 가리지 않게 `progressed` 로 바꾼다.)
- `grep -nE "_stall_counts|_all_failed_rounds|_verified_count|_feedback_signal|_made_progress|spent_before|verified_before|feedback_before" neos/workflow/deep_analysis/orchestrator.py` → 0줄.

- [ ] **Step 5: 정체 테스트 이주**

`test_commit_pass_explore_brief.py` 두 테스트(~242행, ~337행 근처) — 모양:
```python
    class _RecordingTracker(StallTracker):
        def __init__(self, max_rounds):
            super().__init__(max_rounds)
            self.registered: list[tuple[str, bool]] = []

        def record(self, question_id, made_progress):
            self.registered.append((question_id, made_progress))
            return super().record(question_id, made_progress)

    tracker = _RecordingTracker(settings.config.deep_analysis.max_stall_rounds)   # 생성자 기본과 같은 값 — 아래 주의
    tracker.record(question.id, False)
    tracker.record(question.id, False)
    tracker.registered.clear()
    orchestrator = Orchestrator(..., stall_tracker=tracker)   # 나머지 인자 그대로
    ...
    question.spent_tokens = 40
    assert await made_progress(ledger, question.id, Progress(0, 1, 0)) is True
    question.spent_tokens = 0
    assert await made_progress(ledger, question.id, Progress(0, 1, 0)) is False
    ran = await orchestrator._run_round()
    assert ran is True
    assert tracker.registered == [(question.id, True)]
    assert tracker.count(question.id) == 0
```
주의: 생성자가 `max_stall_rounds` 를 정하는 식(orchestrator.py ~396행)을 읽고, 테스트의 tracker 에 **같은 값**을 준다. 그 값이 2 이하이면 시드용 두 번째 `record` 가 True 를 돌려주지만 tracker 는 아무것도 하지 않는다(부수효과는 Orchestrator 쪽) — 그대로 둔다. `_RecordingTracker` 가 두 테스트에 똑같이 필요하면 모듈 수준에 한 번만 둔다.

`test_orchestrator_run_worker.py::test_non_failed_worker_result_resets_systemic_failure_rounds` — **Orchestrator 의 `_register_round_outcome` 이 tracker 를 옳게 먹이는지**를 보는 배선 테스트라 `_register_round_outcome` 호출 3줄은 남긴다(spec 지표 18 → 4 의 근거):
```python
    tracker = StallTracker(max_rounds=2)
    orch = <그 파일의 _orch 와 같은 인자로 Orchestrator 를 짓되 stall_tracker=tracker>   # _orch 에 **kwargs 를 더해 넘기는 편이 낫다
    failed = WorkerResult(question_id="q", status="failed")
    completed = WorkerResult(question_id="q", status="completed")

    await orch._register_round_outcome([failed])
    await orch._register_round_outcome([completed])
    await orch._register_round_outcome([failed])

    assert tracker.failed_rounds == 1          # 옛 단언: orch._all_failed_rounds == 1 (같은 값, 대상 식 이동)
```
`orch.max_stall_rounds = 2` 줄은 지운다(값은 tracker 가 갖는다).

`test_subagent_adapter.py`(~573행): `orch._stall_counts["qid00001"] = 3` → 생성 전에 `tracker = StallTracker(<그 orch 의 max_stall_rounds 와 같은 값>)`, `tracker.record("qid00001", False)` ×3, `_orch(..., stall_tracker=tracker)`(그 파일의 `_orch` 가 키워드를 넘기게 고친다). `await orch._force_terminate_stalled("qid00001")` 는 **남긴다**(부수효과 시험 — spec §2). 마지막 단언은 `tracker.count("qid00001") == 0`. `orch._do_split = capture_split` 는 범위 밖이라 그대로.

각 파일 실행: `uv run pytest $T/test_commit_pass_explore_brief.py $T/test_orchestrator_run_worker.py $T/test_subagent_adapter.py $T/test_stall.py -q -p no:randomly`

- [ ] **Step 6: 전체·지표·커밋**

```bash
uv run pytest $T -q -p no:randomly
grep -rnoE '\borch(estrator)?\.(_stall_counts|_register_progress|_made_progress|_register_round_outcome|_force_terminate_stalled|_all_failed_rounds)\b' tests | wc -l   # 4: _force_terminate_stalled 1 + _register_round_outcome 3 (둘 다 Orchestrator 쪽 부수효과·배선 시험)
uv run ruff check neos/workflow/deep_analysis tests/workflow/deep_analysis
git add neos/workflow/deep_analysis/stall.py neos/workflow/deep_analysis/orchestrator.py $T/test_stall.py $T/test_commit_pass_explore_brief.py $T/test_orchestrator_run_worker.py $T/test_subagent_adapter.py
git commit -m "refactor(deep-analysis): stall policy as a pure StallTracker; the Orchestrator acts on its verdict"
```

---

### Task 2: `ReportWriter` 추출 (과도기 대조로 동등성 고정)

**Files:**
- Create: `neos/workflow/deep_analysis/report_writer.py`
- Modify: `neos/workflow/deep_analysis/orchestrator.py`
- Test: `tests/workflow/deep_analysis/test_report_writer_transition.py` (create, Step 6 에서 삭제)

**Interfaces:**
- Produces (`neos.workflow.deep_analysis.report_writer`): `ReportWriter(ledger, synthesizer, citation_renderer, report_grader, *, sandbox_provider=None, compose_runtime_factory=None, checkpoint=None)` with public attributes of the same names and `async write(root_id: str, summaries: dict[str, NodeSummary]) -> str`; `async reduce_and_resolve(synthesizer, ledger, source_tiers) -> tuple[dict[str, NodeSummary], list[str]]`; `async collect_caveats(ledger, summaries) -> list[str]`; module privates `_reader_facing_caveats`, `_best_rejected_draft`, `_ensure_limits_section`, `_ensure_question_coverage`.
- Produces (`Orchestrator`): 속성 `self.report_writer`.

- [ ] **Step 1: `report_writer.py` 를 사본으로 만든다 (Orchestrator 는 아직 그대로)**

옮길 것(orchestrator.py, 2026-10-08 행 번호 — 내용으로 확인):
- 모듈 함수 `_reader_facing_caveats`(157), `_best_rejected_draft`(191), `_ensure_limits_section`(251), `_ensure_question_coverage`(281) — 그리고 이것들만 쓰는 모듈 상수·함수가 있으면 함께(이름으로 확인).
- 메서드 `_compose_draft`(815), `_log_code_worker_outcome`(900), `_reduce_and_resolve`(1567), `_child_summaries`(1587), `_collect_caveats`(1613), `_finalize` 의 리포트 작성 부분(`root_summary = summaries.get(root_id)` 부터 끝까지).

모양:
```python
"""Report writing for a deep-analysis run: assemble (or compose) → render → grade,
retried up to `report_retry_cap`, never empty-handed (§6.8).

Moved verbatim from `Orchestrator._finalize` (2026-10-08). The Orchestrator still
owns reduction, conflict reinvestigation (it needs a round) and the run loop;
this module owns everything from "here are the summaries" to the delivered text.
"""

class ReportWriter:
    def __init__(self, ledger, synthesizer, citation_renderer, report_grader, *,
                 sandbox_provider=None, compose_runtime_factory=None, checkpoint=None) -> None:
        self.ledger = ledger
        self.synthesizer = synthesizer
        self.citation_renderer = citation_renderer
        self.report_grader = report_grader
        self.sandbox_provider = sandbox_provider
        self.compose_runtime_factory = compose_runtime_factory
        self._checkpoint_fn = checkpoint

    async def _checkpoint(self) -> None:
        if self._checkpoint_fn is not None:
            await self._checkpoint_fn()

    async def write(self, root_id, summaries) -> str:
        config = settings.config.deep_analysis
        <_finalize 의 root_summary = ... 부터 끝까지, 글자 그대로>

    async def _child_summaries(self, root_id, summaries): <그대로>
    async def _compose_draft(...): <그대로>
    async def _log_code_worker_outcome(...): <그대로>


async def reduce_and_resolve(synthesizer, ledger, source_tiers): <_reduce_and_resolve 본문, self.synthesizer→synthesizer, self.ledger→ledger, config.source_tiers→source_tiers>

async def collect_caveats(ledger, summaries): <_collect_caveats 본문, self.ledger→ledger>
```
`write` 안의 `self._collect_caveats(summaries)` 는 `collect_caveats(self.ledger, summaries)` 로. `_finalize` 가 리포트 작성 부분에서 쓰는 지역 변수(`config` 등) 가 앞부분에서 정의됐다면 `write` 앞머리에서 같은 식으로 정의한다. 옮긴 코드가 쓰는 import 를 모두 옮긴다(함수 안 지연 import 는 그 자리에 그대로 — `compose_worker.run_compose_worker` 처럼 **모듈 경유로 부르는지** 확인하고 그 형태를 유지한다; 테스트가 `compose_worker` 모듈을 패치한다).
Orchestrator 의 `_checkpoint` 가 하는 일을 읽고, 작성기에 넘길 `checkpoint` 콜러블이 같은 일을 하게 한다(Task 2 Step 5 에서 `checkpoint=self._checkpoint`).

- [ ] **Step 2: 과도기 대조 테스트 (옛 `_finalize` 대 새 작성기)**

`tests/workflow/deep_analysis/test_report_writer_transition.py`:
```python
"""TRANSITIONAL: the moved ReportWriter writes what Orchestrator._finalize wrote. Deleted once _finalize delegates."""

import pytest

from neos.config.settings import settings
from neos.workflow.deep_analysis import compose_worker
from neos.workflow.deep_analysis.report_writer import ReportWriter, reduce_and_resolve
from tests.workflow.deep_analysis.test_orchestrator_m4 import (
    FakeLedger,
    FakeSynth,
    FlakyRenderer,
    OkGrader,
    _orch,
)

pytestmark = pytest.mark.no_db


async def _old(renderer_fail, grader):
    ledger, synth = FakeLedger(), FakeSynth()
    report = await _orch(ledger, synth, FlakyRenderer(fail_times=renderer_fail), grader=grader)._finalize("root0001")
    return report, ledger.events, ledger.completed


async def _new(renderer_fail, grader):
    ledger, synth = FakeLedger(), FakeSynth()
    summaries, _ = await reduce_and_resolve(synth, ledger, settings.config.deep_analysis.source_tiers)
    writer = ReportWriter(ledger, synth, FlakyRenderer(fail_times=renderer_fail), grader)
    report = await writer.write("root0001", summaries)
    return report, ledger.events, ledger.completed


@pytest.mark.asyncio
@pytest.mark.parametrize("renderer_fail", [0, 1, 99])
async def test_TRANSITIONAL_writer_matches_finalize(renderer_fail) -> None:
    assert await _new(renderer_fail, OkGrader()) == await _old(renderer_fail, OkGrader())


@pytest.mark.asyncio
async def test_TRANSITIONAL_writer_matches_finalize_with_the_compose_child(monkeypatch) -> None:
    monkeypatch.setattr(settings.config.deep_analysis, "compose_child_enabled", True)

    async def fake(**kwargs):
        return "COMPOSED [C:c1aaaaaa]\n\n## 출처", {"steps": 1, "cited_verified": 1}

    monkeypatch.setattr(compose_worker, "run_compose_worker", fake)
    # sandbox_provider / compose_runtime_factory: test_compose_child_j4.py 의 MemoryProvider 와 `lambda port: None` 을 그대로 쓴다.
    ...  # 옛 경로: _orch(...) 에 두 값을 꽂고 _finalize, 새 경로: ReportWriter(..., sandbox_provider=..., compose_runtime_factory=...)
    # 두 경로의 (report, ledger.events, ledger.completed) 가 같다.
```
compose 시나리오는 `test_compose_child_j4.py` 의 `_summaries()`·`FakeSynth(_summaries())`·`MemoryProvider` 를 import 해 그 파일의 `test_with_the_flag_on_the_compose_child_writes_the_draft` 와 같은 준비를 두 경로에 준다. FakeLedger 의 `events` 가 비교 불가능한 객체를 담으면 `repr` 로 비교한다(보고서에 적는다). `FlakyRenderer(fail_times=99)` 는 캡 소진 시나리오다 — 렌더러의 `fail_times` 의미를 확인하고, 캡 소진이 되지 않으면 `report_retry_cap + 1` 이상으로 준다.

Run: `uv run pytest $T/test_report_writer_transition.py -q -p no:randomly` → 4 passed. 실패하면 옮긴 본문이 원본과 다른 것이다 — diff 한다.

- [ ] **Step 3: Orchestrator 가 작성기에 위임한다**

`orchestrator.py`:
- import: `from neos.workflow.deep_analysis.report_writer import ReportWriter, reduce_and_resolve`
- `__init__` 끝(필요한 속성이 모두 정해진 뒤): 
```python
        self.report_writer = ReportWriter(
            self.ledger,
            self.synthesizer,
            self.citation_renderer,
            self.report_grader,
            sandbox_provider=self.sandbox_provider,
            compose_runtime_factory=self.compose_runtime_factory,
            checkpoint=self._checkpoint,
        )
```
(생성자가 이 속성들을 다른 이름으로 저장하거나 기본값을 채우는 식이 있으면 그 결과를 넘긴다.)
- `_finalize`: 앞부분(축약·해소·재조사)에서 `self._reduce_and_resolve(root_id)` 두 곳을 `reduce_and_resolve(self.synthesizer, self.ledger, config.source_tiers)` 로, 리포트 작성 부분 전체를 `return await self.report_writer.write(root_id, summaries)` 로.
- 옮긴 메서드·모듈 함수를 orchestrator.py 에서 지운다. 더 쓰이지 않는 import 를 ruff 로 지운다.
- `grep -nE "_child_summaries|_collect_caveats|_compose_draft|_log_code_worker_outcome|_reduce_and_resolve|_best_rejected_draft|_reader_facing_caveats|_ensure_limits_section|_ensure_question_coverage" neos/workflow/deep_analysis/orchestrator.py` → 0줄.

- [ ] **Step 4: 과도기 테스트를 위임 뒤에도 돌린다**

과도기 테스트는 이제 옛 경로도 작성기를 지난다 — 통과는 "위임이 옳다"는 증거이고, Step 2 의 통과가 "옮김이 옳다"는 증거다.
Run: `uv run pytest $T/test_report_writer_transition.py $T/test_orchestrator_m4.py $T/test_compose_child_j4.py $T/test_orchestrator_m4_reinvest.py -q -p no:randomly`
Expected: 모두 통과 — 단 `test_orchestrator_m4.py` 의 `orch_mod.resolve_conflicts` 패치 3 테스트는 **이 시점에 실패할 수 있다**(패치가 옛 모듈을 겨눈다). 실패하면 그 3곳의 `monkeypatch.setattr(orch_mod, "resolve_conflicts", …)` 를 `monkeypatch.setattr(report_writer_mod, "resolve_conflicts", …)`(`import neos.workflow.deep_analysis.report_writer as report_writer_mod`)로 바꾼다 — 이 단계의 일이다(Task 3 가 아니다). 실패하지 않으면 패치가 실제로 효과가 있는지(패치 함수가 불렸는지) 확인한다 — 효과가 없는데 통과하면 그 테스트는 이미 공허했던 것이다: 보고한다.
`test_orchestrator_m4.py` 와 `test_compose_child_j4.py` 의 private import(`_best_rejected_draft`, `_reader_facing_caveats`) 가 깨지면 import 경로를 `report_writer` 로 바꾼다.

- [ ] **Step 5: 과도기 테스트를 지우고 전체·커밋**

`rm $T/test_report_writer_transition.py`
```bash
uv run pytest $T -q -p no:randomly
uv run ruff check neos/workflow/deep_analysis tests/workflow/deep_analysis
git add -A neos/workflow/deep_analysis $T
git commit -m "refactor(deep-analysis): report writing moves to ReportWriter; _finalize reduces, reinvestigates, delegates"
```

---

### Task 3: 리포트 작성 테스트를 작성기 위로

**Files:**
- Modify: `tests/workflow/deep_analysis/test_orchestrator_m4.py`, `tests/workflow/deep_analysis/test_compose_child_j4.py`

**Interfaces:**
- Consumes: `ReportWriter`, `reduce_and_resolve`, `collect_caveats` (Task 2).

- [ ] **Step 1: 헬퍼**

`test_orchestrator_m4.py` 의 `_orch` 옆에:
```python
def _writer(ledger, synth, renderer, grader=None, **kwargs):
    return ReportWriter(ledger, synth, renderer, grader, **kwargs)


async def _write(writer, root_id="root0001"):
    """What _finalize hands the writer when nothing needs reinvestigation."""
    summaries, _ = await reduce_and_resolve(
        writer.synthesizer, writer.ledger, settings.config.deep_analysis.source_tiers
    )
    return await writer.write(root_id, summaries)
```

- [ ] **Step 2: 18 + 4 곳을 바꾼다**

`test_orchestrator_m4.py` 의 `_finalize` 호출 중 **재조사 3 테스트**(`test_conflict_reinvestigation_is_globally_capped_at_one`, `test_reinvestigation_gate_is_event_based_and_durable`, `test_a_starved_reinvestigation_round_does_not_kill_the_run`)를 **뺀** 나머지:
```python
# before
orch = _orch(ledger, synth, renderer, grader=OkGrader())
report = await orch._finalize("root0001")
# after
writer = _writer(ledger, synth, renderer, grader=OkGrader())
report = await _write(writer)
```
`test_compose_child_j4.py` 4곳:
```python
# before
orch = _orch(ledger, synth, FlakyRenderer(0), grader=OkGrader())
orch.sandbox_provider = MemoryProvider()
orch.compose_runtime_factory = lambda port: None
report = await orch._finalize("root0001")
# after
writer = _writer(ledger, synth, FlakyRenderer(0), grader=OkGrader(),
                 sandbox_provider=MemoryProvider(), compose_runtime_factory=lambda port: None)
report = await _write(writer)
```
(`_writer`·`_write` 를 m4 에서 import 에 더한다.) 이 4 테스트 중 `orch.<다른 필드>` 를 읽는 단언이 있으면 같은 값을 주는 `writer.<필드>` 로 — 보고서에 적는다.

- [ ] **Step 3: 메서드 바꿔치기·직접 호출**

`test_the_harness_names_the_resolved_questions_the_model_dropped`(~779행): `orch._child_summaries = lambda …: [resolved, open_child]` 를 지우고, 같은 두 `NodeSummary` 가 작성기에 닿도록 **입력**을 꾸민다 — `_child_summaries` 의 본문(이제 `ReportWriter._child_summaries`)을 읽고: `ledger.children(root)` 가 `child001`(resolved, text=`resolved.question_text`)·`child002`(open, text=`open_child.question_text`) 질문을 돌려주고, `summaries` 에 두 id 의 요약이 있으면 같은 값이 나온다. 이 테스트는 `_write` 대신 `writer.write("root0001", summaries)` 를 직접 불러 summaries 를 손으로 준다(`_Synth.reduce_tree` 가 루트만 돌려주던 것과 같은 결과가 되게 루트 요약 포함). FakeLedger 의 `children` 이 무엇을 돌려주는지 읽고, 필요하면 이 테스트 안에서 `children` 만 바꾼 하위 클래스를 쓴다. 단언 3줄은 그대로.

`test_collect_caveats_hands_the_report_reader_facing_text`: `await orch._collect_caveats(summaries)` → `await collect_caveats(ledger, summaries)`. `orch = _orch(...)` 줄은 쓰이지 않으면 지운다.

- [ ] **Step 4: 확인·커밋**

```bash
grep -rnoE '\borch(estrator)?\._finalize\(' tests | wc -l        # 5
grep -rnE '\borch(estrator)?\.(sandbox_provider|compose_runtime_factory|max_stall_rounds)\s*=[^=]' tests | wc -l   # 0
git diff HEAD -- tests | grep -E '^[-+]\s*assert'                 # 보고서에 전부 적는다(대상 식 이동만이어야 한다)
uv run pytest $T -q -p no:randomly
uv run ruff check tests/workflow/deep_analysis
git add -u $T
git commit -m "test(deep-analysis): report-writing tests drive ReportWriter, not Orchestrator._finalize"
```

---

### Task 4: 최종 검증 (controller 확인)

- [ ] 이름 대조: 작업 뒤 `$T` 수집 이름 — 사라진 이름 0, 새 이름은 `test_stall.py` 의 테스트들뿐(과도기 테스트는 지워졌다).
- [ ] 결과 대조: 이름별 결과에서 통과→실패 0.
- [ ] 지표: finalize 5, stall 4, postset 0, orch_privates(기록).
- [ ] CI Ruff 명령 그대로:
```bash
uv run --frozen ruff check neos/workflow/deep_analysis neos/coding neos/subagent neos/fsi neos/univer neos/config neos/learn neos/jev tests/workflow/deep_analysis tests/coding tests/subagent tests/fsi tests/univer tests/k_skill tests/security_audit tests/learn tests/jev tests/config tests/conftest.py
```
- [ ] spec 상태 줄을 `- 상태: 구현 완료(2026-10-08)` 로 고치고 커밋: `docs(spec): deep-analysis report writer + stall tracker landed`

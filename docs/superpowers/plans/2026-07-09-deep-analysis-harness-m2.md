# 심층 분석 하네스 — M2 구현 계획 (예산 + 병렬 + SPLIT)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** M1 순차 k=1 SCOUT 루프를 원 설계 §6.2/§6.3의 완전한 예산 기반 병렬 루프로 확장한다 — Budgeter 점수/사다리, asyncio 병렬 워커, 타임아웃→partial 시맨틱, cap 소진·연속 실패 시 SPLIT, depth cap에서 abandon.

**Architecture:** 원 설계 [docs/DEEP_ANALYSIS_HARNESS_DESIGN.md](../../DEEP_ANALYSIS_HARNESS_DESIGN.md) §9 M2 정본. 이미 구현된 M0–M1 코드(Ledger/Worker/Orchestrator/Budgeter 스텁) 위에 증분 확장. 단일 작성자(P2)·run 스코프(D3/D4)·워커 무상태(D9)·orphan 인용 실패(D10)는 그대로 유지. Budgeter 상태(aging/라운드)는 인메모리(D1).

**Tech Stack:** Python 3.12, async SQLAlchemy 2.0, asyncio(gather/wait_for), pytest + pytest-asyncio. FakeWorker 계약 테스트(LLM 없음).

**정본:** 컴포넌트 규칙 §6.2/§6.3, 부록 A1(취소 시맨틱). DECISIONS: [neos/workflow/deep_analysis/DECISIONS.md](../../../neos/workflow/deep_analysis/DECISIONS.md).

## Global Constraints

- **범위: M2만.** 에이전틱 채점/feedback 순환/repair(M3), 계층 리듀스/충돌/ReportGrader(M4)는 착수 금지(원 설계 §11.10).
- **§6.2 Budgeter는 순수 함수 + 인메모리 상태만.** DDL에 aging 컬럼 추가 금지(D1). 점수/사다리는 LLM 호출 없음.
- **P2 단일 작성자:** 병렬 워커 결과는 **순차 커밋**. `asyncio.gather`로 워커를 병렬 실행하되, 커밋 루프는 한 번에 하나씩(`commit_blobs`→grade→`commit_pass`). 워커는 DB 세션 미접근(D9).
- **A1 취소 시맨틱:** assignment당 새 Worker 인스턴스(`worker_factory()`). `_run_worker`가 그 워커를 보유하고 타임아웃 시 `flush_partial()` 호출. 워커 내부 `except BaseException` 금지. `_run_worker`는 모든 예외를 `WorkerResult(status="failed")`로 변환.
- **매직넘버 금지:** 전부 `settings.config.deep_analysis.*`. dev 프로파일은 `parallel_workers`/`max_depth`/`global_token_cap`를 오버라이드.
- **§11.10 순서 준수:** M2 AC를 통과하기 전 M3/M4 착수 금지.
- **DECISIONS 갱신:** M2에서 새 판단 발생 시 D11+로 기록.

## M2 완료 기준 (원 설계 §9)

- **AC-a:** 타임아웃 워커의 부분 클레임(partial)이 커밋된다.
- **AC-b:** cap 소진 질문이 SPLIT된다.
- **AC-c:** fail_streak 2회에 강제 SPLIT된다.
- **AC-d:** 전역 토큰 캡에서 정지한다.
- (전부 FakeWorker로 재현 — 원 설계 §10.)

## M2가 명시적으로 연기하는 것
- **§6.3.2 서브질문 심사(proposed_subquestions 채택):** M2 AC에 없음. 워커가 제안한 서브질문은 이벤트로 로깅만 하고 채택은 M3로 연기(LLM 심사 필요). SPLIT은 오케스트레이터 권한의 decompose로 트리를 키우므로 M2 AC 충족에 서브질문 채택 불필요.
- **실 Worker의 진정한 점진 클레임 버퍼링:** 현재 Worker는 단일 LLM 콜 구조라 타임아웃 시 blobs만 버퍼에 남고 claims는 비어 있다. M2 AC는 오케스트레이터 메커니즘(FakeWorker로 검증)이 대상이므로 실 워커 개조는 M2 범위 밖. Task 7에서 "flagged refinement"로 기록만.

---

## 파일 구조

- Modify: `neos/workflow/deep_analysis/ledger.py` — Budgeter/SPLIT용 읽기 + `record_abandon` + pass_completed payload에 verified 수 추가.
- Rewrite: `neos/workflow/deep_analysis/budgeter.py` — 점수/사다리/breadth pass/should_stop(score_floor). 인메모리 상태.
- Modify: `neos/workflow/deep_analysis/orchestrator.py` — 병렬 루프, `_run_worker`(timeout/partial/failed), `_partition`, `_do_split`/abandon, 순차 커밋.
- Modify: `neos/workflow/deep_analysis/service.py` + `Orchestrator.__init__` — dev 프로파일의 `parallel_workers`/`max_depth` 스레딩.
- Tests: `tests/workflow/deep_analysis/test_budgeter.py`(신규), `test_ledger_m2.py`(신규), `test_orchestrator_m2.py`(신규), 기존 `test_orchestrator_contract.py` 업데이트.

---

### Task 1: Ledger — Budgeter/SPLIT용 읽기 + record_abandon + verified 카운트

**Files:**
- Modify: `neos/workflow/deep_analysis/ledger.py`
- Test: `tests/workflow/deep_analysis/test_ledger_m2.py`

**Interfaces:**
- Produces (Ledger 신규 메서드):
  - `async gain_history(self, question_id: str, last_n: int = 3) -> list[int]` — 최근 `last_n`개 `pass_completed` 이벤트의 payload에서 `verified` 값을 시간 역순으로 반환.
  - `async verified_summaries(self, question_id: str) -> str` — 해당 질문의 verified 클레임 텍스트를 개행 결합(brief [3]/SPLIT decompose 입력용). 없으면 `"(없음)"`.
  - `async unverified_and_deadends(self, question_id: str) -> list[str]` — dead_end 이벤트 텍스트 + unverified 클레임 텍스트.
  - `async record_abandon(self, question_id: str) -> None` — `open→abandoned` 전이 + `abandoned` 이벤트.
  - `async remaining_budget(self, question_id: str) -> int` — `cap_tokens - spent_tokens`(음수면 0).
- Modify: `_upsert`/`commit_pass`의 `pass_completed` 이벤트 payload에 `"verified": <이번 패스 신규 verified 수>` 추가. (현재 `new_claims`만 있음 → gain_decay가 verified 기준이므로 필요.)

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/workflow/deep_analysis/test_ledger_m2.py
import pytest
from sqlalchemy import text as sql
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.models import WorkerResult, ProposedClaim, ProposedEvidence, ProposedBlob, Verdict
from neos.database.connection import db_manager

async def _run(s):
    return await create_run(s, "root?", "dev")

@pytest.mark.asyncio
async def test_gain_history_reads_verified_counts():
    async with await db_manager.get_session() as s:
        run_id = await _run(s)
        led = Ledger(s, run_id)
        qid = await led.open_question("q?", None, 1.0, 5000, 0)
        # 두 번의 pass: 1개 verified, 0개 verified
        blob = ProposedBlob(content_hash="hh", source_url="http://x", http_status=200, raw_text="body fact text")
        ev = ProposedEvidence(source_url="http://x", excerpt="body fact text", raw_ref="hh")
        await led._transition(qid, "investigating")
        r1 = WorkerResult(question_id=qid, status="completed", blobs=[blob],
                          claims=[ProposedClaim(text="a fact", confidence=0.55, evidence=[ev])], tokens_spent=100)
        await led.commit_pass(qid, r1, {"a fact": Verdict(ok=True)})
        await led._transition(qid, "investigating")
        r2 = WorkerResult(question_id=qid, status="partial", tokens_spent=50)
        await led.commit_pass(qid, r2, {})
        hist = await led.gain_history(qid, last_n=3)
        assert hist[0] == 0 and hist[1] == 1   # 최신순
        await s.rollback()

@pytest.mark.asyncio
async def test_record_abandon_transitions_and_logs():
    async with await db_manager.get_session() as s:
        run_id = await _run(s)
        led = Ledger(s, run_id)
        qid = await led.open_question("q?", None, 0.1, 100, 4)
        await led.record_abandon(qid)
        q = await led.get_question(qid)
        assert q.status == "abandoned"
        row = await s.execute(sql("SELECT COUNT(*) FROM deep_analysis_events WHERE run_id=:r AND kind='abandoned'"), {"r": run_id})
        assert row.scalar() == 1
        await s.rollback()

@pytest.mark.asyncio
async def test_remaining_budget():
    async with await db_manager.get_session() as s:
        run_id = await _run(s)
        led = Ledger(s, run_id)
        qid = await led.open_question("q?", None, 1.0, 1000, 0)
        await led._transition(qid, "investigating")
        await led.commit_pass(qid, WorkerResult(question_id=qid, status="partial", tokens_spent=300), {})
        assert await led.remaining_budget(qid) == 700
        await s.rollback()
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/workflow/deep_analysis/test_ledger_m2.py -v`
Expected: FAIL — `AttributeError: 'Ledger' object has no attribute 'gain_history'`

- [ ] **Step 3: Ledger 확장**

`commit_pass`에서 verified 카운트 집계 — `verified_any` 부근을 카운터로 교체:

```python
        verified_count = 0
        for proposed_claim in result.claims:
            claim_id, evidence_rows = await self._upsert_claim(question_id, proposed_claim)
            verdict = verdicts.get(claim_id) or verdicts.get(proposed_claim.text)
            if await self._record_verdict(question_id, claim_id, evidence_rows, verdict):
                verified_count += 1
        verified_any = verified_count > 0
```

`pass_completed` 로그 payload에 verified 추가:

```python
        await self.log(
            "pass_completed",
            question_id,
            {
                "status": result.status,
                "new_claims": len(result.claims),
                "verified": verified_count,
                "tokens": result.tokens_spent,
            },
        )
```

Ledger 클래스에 메서드 추가:

```python
    async def gain_history(self, question_id: str, last_n: int = 3) -> list[int]:
        result = await self.db.execute(
            select(DAEvent.payload)
            .where(
                DAEvent.run_id == self.run_id,
                DAEvent.qid == question_id,
                DAEvent.kind == "pass_completed",
            )
            .order_by(DAEvent.seq.desc())
            .limit(last_n)
        )
        counts: list[int] = []
        for payload in result.scalars():
            try:
                counts.append(int(json.loads(payload).get("verified", 0)))
            except (ValueError, TypeError):
                counts.append(0)
        return counts

    async def verified_summaries(self, question_id: str) -> str:
        pairs = await self.verified_claims(question_id)
        if not pairs:
            return "(없음)"
        return "\n".join(f"- {claim.text}" for claim, _ in pairs)

    async def unverified_and_deadends(self, question_id: str) -> list[str]:
        out: list[str] = []
        events = await self.db.execute(
            select(DAEvent.payload).where(
                DAEvent.run_id == self.run_id,
                DAEvent.qid == question_id,
                DAEvent.kind == "dead_end",
            )
        )
        for payload in events.scalars():
            try:
                out.append(str(json.loads(payload).get("text", "")))
            except (ValueError, TypeError):
                continue
        claims = await self.db.execute(
            select(DAClaim.text).where(
                DAClaim.run_id == self.run_id,
                DAClaim.question_id == question_id,
                DAClaim.status == "unverified",
            )
        )
        out.extend(str(t) for t in claims.scalars())
        return out

    async def record_abandon(self, question_id: str) -> None:
        await self._transition(question_id, "abandoned")
        await self.log("abandoned", question_id, {})

    async def remaining_budget(self, question_id: str) -> int:
        question = await self.get_question(question_id)
        if question is None:
            raise KeyError(question_id)
        return max(0, question.cap_tokens - question.spent_tokens)
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/workflow/deep_analysis/test_ledger_m2.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 기존 Ledger 테스트 회귀 확인 + 커밋**

Run: `pytest tests/workflow/deep_analysis/test_ledger.py -v`
Expected: PASS (payload에 verified 추가는 기존 테스트에 무해)

```bash
git add neos/workflow/deep_analysis/ledger.py tests/workflow/deep_analysis/test_ledger_m2.py
git commit -m "feat(deep-analysis): add Ledger reads for budgeter/split and verified-count events"
```

---

### Task 2: Budgeter 점수 함수 (순수, 인메모리 상태)

**Files:**
- Rewrite: `neos/workflow/deep_analysis/budgeter.py`
- Test: `tests/workflow/deep_analysis/test_budgeter.py`

**Interfaces:**
- Consumes: Task 1 `gain_history`, settings.
- Produces:
  - `class Budgeter(*, score_floor, aging_per_round, breadth_pass_ratio, global_token_cap, max_depth, parallel_workers)` — 전부 주입(기본은 settings). 인메모리 상태: `self._round = 0`, `self._last_selected: dict[str, int] = {}`.
  - `def gain_decay(self, counts: list[int]) -> float` — 순수. `counts` 평균 g: g>=2→1.0, g==1→0.6, g==0→0.3, 빈 리스트→1.0.
  - `def aging(self, qid: str) -> float` — `(self._round - last_selected) × aging_per_round`, 미선택이면 `self._round × aging_per_round`.
  - `async score(self, ledger, question) -> float` — `value_est × (1 - confidence) × gain_decay(gain_history) + aging`.
  - `def ladder(self, question) -> Effort` — §6.2 사다리(순수). SPLIT/DIG/SCOUT 반환.

- [ ] **Step 1: 실패 테스트 작성 (순수 함수 전수)**

```python
# tests/workflow/deep_analysis/test_budgeter.py
import pytest
from types import SimpleNamespace
from neos.workflow.deep_analysis.budgeter import Budgeter
from neos.workflow.deep_analysis.models import Effort

def _q(**kw):
    base = dict(id="q1", confidence=0.0, value_est=1.0, spent_tokens=0,
                cap_tokens=2000, fail_streak=0, depth=1, status="open")
    base.update(kw)
    return SimpleNamespace(**base)

def test_gain_decay_buckets():
    b = Budgeter()
    assert b.gain_decay([2, 3]) == 1.0
    assert b.gain_decay([1, 1]) == 0.6
    assert b.gain_decay([0, 0]) == 0.3
    assert b.gain_decay([]) == 1.0

def test_ladder_fail_streak_forces_split():
    b = Budgeter()
    assert b.ladder(_q(fail_streak=2)) == Effort.SPLIT

def test_ladder_cap_exhausted_forces_split():
    b = Budgeter()
    assert b.ladder(_q(spent_tokens=2000, cap_tokens=2000)) == Effort.SPLIT

def test_ladder_low_confidence_after_scout_digs():
    b = Budgeter()
    assert b.ladder(_q(confidence=0.2, spent_tokens=500)) == Effort.DIG

def test_ladder_default_scout():
    b = Budgeter()
    assert b.ladder(_q()) == Effort.SCOUT

def test_aging_increases_with_rounds():
    b = Budgeter(aging_per_round=0.05)
    b._round = 4
    assert abs(b.aging("never_selected") - 0.20) < 1e-9
    b._last_selected["q1"] = 2
    assert abs(b.aging("q1") - 0.10) < 1e-9
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/workflow/deep_analysis/test_budgeter.py -v`
Expected: FAIL

- [ ] **Step 3: Budgeter 재작성 (select/should_stop은 Task 3에서 채움)**

```python
# neos/workflow/deep_analysis/budgeter.py
"""예산 기반 선택 + 정지 판단. 원 설계 §6.2. 상태(aging/라운드)는 인메모리(D1)."""
from __future__ import annotations

from neos.config.settings import settings

from .models import Effort


class Budgeter:
    def __init__(
        self,
        *,
        score_floor: float | None = None,
        aging_per_round: float | None = None,
        breadth_pass_ratio: float | None = None,
        global_token_cap: int | None = None,
        max_depth: int | None = None,
        parallel_workers: int | None = None,
    ) -> None:
        config = settings.config.deep_analysis
        self.score_floor = config.score_floor if score_floor is None else score_floor
        self.aging_per_round = (
            config.aging_per_round if aging_per_round is None else aging_per_round
        )
        self.breadth_pass_ratio = (
            config.breadth_pass_ratio if breadth_pass_ratio is None else breadth_pass_ratio
        )
        self.global_token_cap = (
            settings.DEEP_ANALYSIS_GLOBAL_TOKEN_CAP
            if global_token_cap is None
            else global_token_cap
        )
        self.max_depth = config.max_depth if max_depth is None else max_depth
        self.parallel_workers = (
            config.parallel_workers if parallel_workers is None else parallel_workers
        )
        self._round = 0
        self._last_selected: dict[str, int] = {}

    def gain_decay(self, counts: list[int]) -> float:
        if not counts:
            return 1.0
        g = sum(counts) / len(counts)
        if g >= 2:
            return 1.0
        if g >= 1:
            return 0.6
        return 0.3

    def aging(self, question_id: str) -> float:
        last = self._last_selected.get(question_id)
        elapsed = self._round if last is None else (self._round - last)
        return elapsed * self.aging_per_round

    async def score(self, ledger, question) -> float:
        history = await ledger.gain_history(question.id, last_n=3)
        base = question.value_est * (1.0 - question.confidence) * self.gain_decay(history)
        return base + self.aging(question.id)

    def ladder(self, question) -> Effort:
        if question.fail_streak >= 2:
            return Effort.SPLIT
        if question.spent_tokens >= question.cap_tokens:
            return Effort.SPLIT
        if question.confidence < 0.3 and question.spent_tokens > 0:
            return Effort.DIG
        return Effort.SCOUT
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/workflow/deep_analysis/test_budgeter.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/deep_analysis/budgeter.py tests/workflow/deep_analysis/test_budgeter.py
git commit -m "feat(deep-analysis): add budgeter score function, gain_decay, aging, ladder"
```

---

### Task 3: Budgeter select (breadth pass + 점수 정렬) + should_stop(score_floor)

**Files:**
- Modify: `neos/workflow/deep_analysis/budgeter.py`
- Test: `tests/workflow/deep_analysis/test_budgeter_select.py`

**Interfaces:**
- Produces:
  - `async select(self, ledger, k: int | None = None) -> list[tuple[question, Effort]]` — 라운드 증가(`self._round += 1`). 첫 라운드(`self._round == 1`)는 breadth pass: 루트 직계 자식 전원 SCOUT(단 `total_spent < breadth_pass_ratio × global_token_cap`인 동안). 이후: open 질문을 score 내림차순 정렬 → 상위 k개 선택 → 각자 `ladder(q)`로 effort 결정 → `self._last_selected[qid] = self._round` 기록.
  - `async should_stop(self, ledger) -> bool` — `total_spent >= global_token_cap` OR (모든 open 질문의 score < score_floor).
- **주의:** select와 should_stop 모두 라운드 카운터를 건드리지 않도록 — 라운드 증가는 select 진입 시 한 번만. should_stop은 상태 불변.

- [ ] **Step 1: 실패 테스트 작성 (FakeLedger로 순수 검증)**

```python
# tests/workflow/deep_analysis/test_budgeter_select.py
import pytest
from types import SimpleNamespace
from neos.workflow.deep_analysis.budgeter import Budgeter
from neos.workflow.deep_analysis.models import Effort

def _q(qid, **kw):
    base = dict(id=qid, confidence=0.0, value_est=1.0, spent_tokens=0,
                cap_tokens=2000, fail_streak=0, depth=1, status="open", parent_id="root")
    base.update(kw); return SimpleNamespace(**base)

class FakeLedger:
    def __init__(self, questions, spent=0, root_id="root"):
        self._questions = questions; self._spent = spent; self._root_id = root_id
    async def open_questions(self): return [q for q in self._questions if q.status == "open"]
    async def children(self, qid): return [q for q in self._questions if q.parent_id == qid]
    async def root_question(self): return SimpleNamespace(id=self._root_id)
    async def gain_history(self, qid, last_n=3): return []
    async def total_spent(self): return self._spent

@pytest.mark.asyncio
async def test_first_round_breadth_pass_all_scout():
    qs = [_q("a"), _q("b"), _q("c")]
    b = Budgeter(global_token_cap=10000, breadth_pass_ratio=0.30)
    picks = await b.select(FakeLedger(qs, spent=0), k=2)
    assert len(picks) == 3 and all(e == Effort.SCOUT for _, e in picks)  # breadth = 전원

@pytest.mark.asyncio
async def test_second_round_top_k_by_score():
    qs = [_q("a", value_est=0.2), _q("b", value_est=0.9), _q("c", value_est=0.5)]
    b = Budgeter(global_token_cap=10000)
    await b.select(FakeLedger(qs), k=3)          # 1라운드 소진
    picks = await b.select(FakeLedger(qs), k=2)  # 2라운드
    ids = [q.id for q, _ in picks]
    assert ids == ["b", "c"]                      # score 내림차순 상위 2

@pytest.mark.asyncio
async def test_should_stop_on_global_cap():
    b = Budgeter(global_token_cap=1000)
    assert await b.should_stop(FakeLedger([_q("a")], spent=1000)) is True

@pytest.mark.asyncio
async def test_should_stop_when_all_below_floor():
    b = Budgeter(global_token_cap=10000, score_floor=0.05)
    # confidence 1.0 → base 0, aging 0(첫 판정) → score 0 < floor
    assert await b.should_stop(FakeLedger([_q("a", confidence=1.0)], spent=0)) is True
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/workflow/deep_analysis/test_budgeter_select.py -v`
Expected: FAIL — `AttributeError: ... 'select'` (스텁 시그니처 불일치/미구현)

- [ ] **Step 3: select/should_stop 구현** (budgeter.py에 메서드 추가)

```python
    async def select(self, ledger, k: int | None = None):
        k = self.parallel_workers if k is None else k
        self._round += 1
        open_questions = await ledger.open_questions()
        if not open_questions:
            return []

        # 첫 라운드: breadth pass (루트 직계 자식 전원 SCOUT, 30% 한도 내)
        if self._round == 1:
            spent = await ledger.total_spent()
            if spent < self.breadth_pass_ratio * self.global_token_cap:
                root = await ledger.root_question()
                children = await ledger.children(root.id) if root else []
                open_ids = {q.id for q in open_questions}
                breadth = [q for q in children if q.id in open_ids]
                if breadth:
                    for q in breadth:
                        self._last_selected[q.id] = self._round
                    return [(q, Effort.SCOUT) for q in breadth]

        scored = [(await self.score(ledger, q), q) for q in open_questions]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        chosen = [q for _score, q in scored[:k]]
        picks = []
        for q in chosen:
            self._last_selected[q.id] = self._round
            picks.append((q, self.ladder(q)))
        return picks

    async def should_stop(self, ledger) -> bool:
        spent = await ledger.total_spent()
        if spent >= self.global_token_cap:
            return True
        open_questions = await ledger.open_questions()
        if not open_questions:
            return True
        for q in open_questions:
            if (await self.score(ledger, q)) >= self.score_floor:
                return False
        return True
```

> **호환성 주의:** M1 오케스트레이터는 `should_stop(spent, cap, picks)` 3인자 시그니처를 호출한다. Task 5에서 오케스트레이터를 `should_stop(ledger)` 1인자로 갱신하므로, 이 태스크 커밋 직후 M1 오케스트레이터 계약 테스트는 일시적으로 깨진다 — Task 5까지 함께 리뷰(같은 브랜치).

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/workflow/deep_analysis/test_budgeter_select.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/deep_analysis/budgeter.py tests/workflow/deep_analysis/test_budgeter_select.py
git commit -m "feat(deep-analysis): add budgeter breadth pass, score-ranked select, score-floor stop"
```

---

### Task 4: Orchestrator — `_run_worker` (timeout/partial/failed, A1)

**Files:**
- Modify: `neos/workflow/deep_analysis/orchestrator.py`
- Test: `tests/workflow/deep_analysis/test_orchestrator_run_worker.py`

**Interfaces:**
- Consumes: Task 2/3 Budgeter, `Assignment`, worker `flush_partial`.
- Produces:
  - `async _run_worker(self, assignment: Assignment) -> WorkerResult` — assignment당 `worker = self.worker_factory()`. `asyncio.wait_for(worker.investigate(brief, effort, qid), timeout=wall_clock_cap)`. `TimeoutError`→`worker.flush_partial(qid)`(status=partial). 그 외 `Exception`→`WorkerResult(status="failed", fail_reason=str(e))`. wall_clock_cap는 `config.effort[effort.value].wall_clock_cap`.
- **A1 준수:** 워커 인스턴스를 지역 변수로 잡고, 타임아웃 시 그 인스턴스의 `flush_partial` 호출(공유/키잉 금지).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/workflow/deep_analysis/test_orchestrator_run_worker.py
import asyncio, pytest
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.models import Assignment, Effort, WorkerResult, ProposedClaim

class HangingWorker:
    """buffer에 클레임 1개 넣고 무한 대기 → 타임아웃 시 flush_partial이 그 클레임 반환."""
    def __init__(self): self._claims = [ProposedClaim(text="buffered", confidence=0.5)]
    async def investigate(self, brief, effort, qid):
        await asyncio.sleep(10)
        return WorkerResult(question_id=qid, status="completed")
    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial", claims=list(self._claims))

class BoomWorker:
    async def investigate(self, brief, effort, qid): raise RuntimeError("boom")
    def flush_partial(self, qid): return WorkerResult(question_id=qid, status="partial")

def _orch(factory):
    return Orchestrator(session=None, run_id="r", worker_factory=factory, grader=None,
                        ledger=object(), decompose_fn=lambda t: [])

@pytest.mark.asyncio
async def test_timeout_yields_partial_with_buffer(monkeypatch):
    orch = _orch(lambda: HangingWorker())
    # wall_clock_cap을 짧게: config 접근을 우회하기 위해 effort별 캡을 패치
    from neos.workflow.deep_analysis import orchestrator as mod
    monkeypatch.setattr(mod, "_wall_clock_cap", lambda effort: 0.05)
    r = await orch._run_worker(Assignment(question_id="q", brief="b", effort=Effort.SCOUT))
    assert r.status == "partial" and r.claims[0].text == "buffered"

@pytest.mark.asyncio
async def test_exception_becomes_failed():
    orch = _orch(lambda: BoomWorker())
    r = await orch._run_worker(Assignment(question_id="q", brief="b", effort=Effort.SCOUT))
    assert r.status == "failed" and "boom" in r.fail_reason
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/workflow/deep_analysis/test_orchestrator_run_worker.py -v`
Expected: FAIL

- [ ] **Step 3: 구현** (orchestrator.py 상단에 헬퍼 + 메서드 추가)

```python
# orchestrator.py — import 블록에 추가
import asyncio
from .models import Assignment, Effort, WorkerResult
```

```python
# 모듈 수준 헬퍼 (테스트에서 monkeypatch 가능하도록 함수로)
def _wall_clock_cap(effort: Effort) -> float:
    return float(settings.config.deep_analysis.effort[effort.value].wall_clock_cap)
```

```python
    async def _run_worker(self, assignment: Assignment) -> WorkerResult:
        worker = self.worker_factory()          # A1: assignment당 새 인스턴스
        try:
            return await asyncio.wait_for(
                worker.investigate(
                    assignment.brief,
                    assignment.effort,
                    assignment.question_id,
                ),
                timeout=_wall_clock_cap(assignment.effort),
            )
        except asyncio.TimeoutError:
            partial = worker.flush_partial(assignment.question_id)
            partial.status = "partial"
            return partial
        except Exception as exc:  # noqa: BLE001 — A1: 모든 예외를 failed로 변환
            return WorkerResult(
                question_id=assignment.question_id,
                status="failed",
                fail_reason=str(exc),
            )
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/workflow/deep_analysis/test_orchestrator_run_worker.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/deep_analysis/orchestrator.py tests/workflow/deep_analysis/test_orchestrator_run_worker.py
git commit -m "feat(deep-analysis): add _run_worker with timeout->partial and exception->failed (A1)"
```

---

### Task 5: Orchestrator — 병렬 루프 + `_partition` + SPLIT/abandon + 순차 커밋

**Files:**
- Modify: `neos/workflow/deep_analysis/orchestrator.py`
- Modify: `neos/workflow/deep_analysis/service.py` (dev 프로파일 parallel_workers/max_depth 스레딩)
- Test: `tests/workflow/deep_analysis/test_orchestrator_m2.py`
- Update: `tests/workflow/deep_analysis/test_orchestrator_contract.py` (should_stop 1인자, 병렬 루프에 맞게)

**Interfaces:**
- Produces:
  - `_partition(picks) -> tuple[list[Assignment], list[question]]` — effort가 SCOUT/DIG면 Assignment(brief 조립), SPLIT면 splits로.
  - `async _do_split(question)` — depth >= max_depth면 `ledger.record_abandon` + `abandoned` 이벤트; 아니면 decompose(질문 텍스트 + verified_summaries + dead_ends)로 2~4 자식 생성(value_est = 부모 × value_decay, cap = remaining_budget/자식수), `ledger.record_split`.
  - `run()` 루프 교체: `while not await budgeter.should_stop(ledger)`: `picks = await budgeter.select(ledger)`; if not picks: break; `_partition`; splits 처리; assignments를 `_transition(investigating)` 후 `asyncio.gather(*[_run_worker(a)])`; 결과를 **순차** 커밋(commit_blobs→grade→commit_pass); proposed_subquestions는 이벤트 로깅만(M3 연기).
- Budgeter는 dev 프로파일 반영: `Orchestrator.__init__`에 `parallel_workers`/`max_depth` 파라미터 추가, Budgeter에 전달.

- [ ] **Step 1: 실패 테스트 작성 (FakeWorker로 M2 AC 전부)**

```python
# tests/workflow/deep_analysis/test_orchestrator_m2.py
import asyncio, pytest
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.models import WorkerResult, ProposedClaim, ProposedEvidence, ProposedBlob, Verdict
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.database.connection import db_manager
from sqlalchemy import text as sql

class OkGrader:
    async def grade(self, claim): return Verdict(ok=True)

def _ok_result(qid, text="a fact"):
    blob = ProposedBlob(content_hash="hh", source_url="http://x", http_status=200, raw_text="body")
    ev = ProposedEvidence(source_url="http://x", excerpt="body", raw_ref="hh")
    return WorkerResult(question_id=qid, status="completed", blobs=[blob],
                        claims=[ProposedClaim(text=text, confidence=0.9, evidence=[ev])],
                        tokens_spent=100, self_assessment=0.9)

@pytest.mark.asyncio
async def test_ac_a_partial_claims_committed(monkeypatch):
    # 타임아웃 워커의 partial 클레임(+blob)이 커밋되는지
    from neos.workflow.deep_analysis import orchestrator as mod
    monkeypatch.setattr(mod, "_wall_clock_cap", lambda e: 0.05)
    class SlowPartial:
        def __init__(self): self._claims=[]; self._blobs=[ProposedBlob("hh","http://x",200,"body")]
        async def investigate(self, b, e, qid): await asyncio.sleep(10)
        def flush_partial(self, qid):
            return WorkerResult(question_id=qid, status="partial",
                                blobs=list(self._blobs), tokens_spent=10)
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        orch = Orchestrator(s, run_id, lambda: SlowPartial(), OkGrader(),
                            decompose_fn=lambda t: [{"text":"sub","value_est":0.8}],
                            global_token_cap=5000)
        await orch.run("root?")
        row = await s.execute(sql("SELECT COUNT(*) FROM deep_analysis_blobs WHERE run_id=:r"), {"r": run_id})
        assert row.scalar() >= 1   # partial blob 커밋됨
        await s.rollback()

@pytest.mark.asyncio
async def test_ac_c_fail_streak_forces_split():
    calls = {"n": 0}
    class Flaky:
        async def investigate(self, b, e, qid):
            calls["n"] += 1
            return WorkerResult(question_id=qid, status="failed", fail_reason="x")
        def flush_partial(self, qid): return WorkerResult(question_id=qid, status="partial")
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        # decompose로 자식 1개(depth1) → 실패 반복 → fail_streak 2 → SPLIT(자식 depth2)
        orch = Orchestrator(s, run_id, lambda: Flaky(), OkGrader(),
                            decompose_fn=lambda t: [{"text":"sub","value_est":0.9}],
                            global_token_cap=5000, max_depth=3)
        # split이 일어나면 decompose가 다시 호출되어 자식 생성 → split 이벤트 존재
        async def split_decompose(text, *a): return [{"text":"child","value_est":0.5}]
        orch._split_decompose = split_decompose
        await orch.run("root?")
        row = await s.execute(sql("SELECT COUNT(*) FROM deep_analysis_events WHERE run_id=:r AND kind='split'"), {"r": run_id})
        assert row.scalar() >= 2   # root 초기 split + fail_streak 유발 split
        await s.rollback()

@pytest.mark.asyncio
async def test_ac_d_stops_at_global_cap():
    class Big:
        async def investigate(self, b, e, qid):
            r = _ok_result(qid); r.tokens_spent = 4000; return r
        def flush_partial(self, qid): return WorkerResult(question_id=qid, status="partial")
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        orch = Orchestrator(s, run_id, lambda: Big(), OkGrader(),
                            decompose_fn=lambda t: [{"text":"s1","value_est":0.9},{"text":"s2","value_est":0.9}],
                            global_token_cap=5000)
        await orch.run("root?")
        total = await Ledger(s, run_id).total_spent()
        assert total >= 4000     # 캡 근처에서 정지(무한 루프 아님)
        await s.rollback()
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/workflow/deep_analysis/test_orchestrator_m2.py -v`
Expected: FAIL

- [ ] **Step 3: 구현** — `Orchestrator.__init__`에 `parallel_workers`/`max_depth`/`split_decompose_fn` 추가, `run()` 루프 교체, `_partition`/`_do_split` 추가.

`__init__` 파라미터 추가(기존 시그니처 뒤에):

```python
        parallel_workers: int | None = None,
        max_depth: int | None = None,
```

**decompose 호출부 정합성(중요):** 기존 `_ensure_root`는 `await self.decompose_fn(root_text)`로 awaitable을 강제한다. M2 계약 테스트가 sync/async decompose 스텁을 모두 쓸 수 있도록 두 호출부를 `_maybe_await`로 라우팅한다:
- `_ensure_root`: `subquestions = await _maybe_await(self.decompose_fn(root_text))`
- `_do_split`(아래): `children_specs = await _maybe_await(self._split_decompose(question.text))`

`__init__` 본문에서 Budgeter 생성 교체:

```python
        config = settings.config.deep_analysis
        self.parallel_workers = (
            config.parallel_workers if parallel_workers is None else parallel_workers
        )
        self.max_depth = config.max_depth if max_depth is None else max_depth
        self.budgeter = Budgeter(
            global_token_cap=self.global_token_cap,
            max_depth=self.max_depth,
            parallel_workers=self.parallel_workers,
        )
        self._split_decompose = self._default_split_decompose   # (text, summaries, dead_ends)
```

`_default_split_decompose` 추가 — §6.3.1대로 verified 요약 + dead_ends를 decompose 프롬프트에 주입:

```python
    async def _default_split_decompose(self, text, verified_summaries, dead_ends):
        config = settings.config.deep_analysis
        prompt = render(
            "decompose",
            question_text=text,
            prior_findings=verified_summaries,
            dead_ends="\n".join(dead_ends) if dead_ends else "(없음)",
        )
        data, _response = await call_json(
            config.models.dig,
            prompt,
            max_tokens=config.decompose_max_tokens,
            client=self.llm_client,
            cassette=self.cassette,
        )
        return list(data.get("subquestions", []))[:4]
```

`run()`의 while 루프 교체:

```python
            while not await self.budgeter.should_stop(self.ledger):
                picks = await self.budgeter.select(self.ledger)
                if not picks:
                    break
                assignments, splits = self._partition(picks)

                for question in splits:
                    await self._do_split(question)
                await self._checkpoint()

                for assignment in assignments:
                    await self.ledger._transition(assignment.question_id, "investigating")
                results = await asyncio.gather(
                    *[self._run_worker(a) for a in assignments]
                )
                for result in results:                    # P2: 순차 커밋
                    await self.ledger.commit_blobs(result.blobs)
                    verdicts = {}
                    for claim in result.claims:
                        verdicts[claim.text] = await self.grader.grade(claim)
                    await self.ledger.commit_pass(result.question_id, result, verdicts)
                    for subq in result.proposed_subquestions:   # M3 연기: 로깅만
                        await self.ledger.log("subq_proposed", result.question_id, {"text": subq})
                    await self._emit("pass_completed", {
                        "qid": result.question_id, "status": result.status,
                        "claims": len(result.claims), "tokens": result.tokens_spent})
                await self._checkpoint()
```

`_partition`/`_do_split` 추가:

```python
    def _partition(self, picks):
        assignments, splits = [], []
        config = settings.config.deep_analysis
        for question, effort in picks:
            if effort == Effort.SPLIT:
                splits.append(question)
                continue
            brief = render(
                "worker_brief",
                question_text=question.text,
                verified_summaries="(없음)",
                dead_ends="(없음)",
                repair_count=0,
                repairs="(없음)",
                token_cap=config.effort[effort.value].token_cap,
            )
            assignments.append(Assignment(question.id, brief, effort))
        return assignments, splits

    async def _do_split(self, question):
        if question.depth >= self.max_depth:
            await self.ledger.record_abandon(question.id)
            await self._emit("abandoned", {"qid": question.id})
            return
        summaries = await self.ledger.verified_summaries(question.id)
        dead_ends = await self.ledger.unverified_and_deadends(question.id)
        children_specs = await _maybe_await(
            self._split_decompose(question.text, summaries, dead_ends)
        )
        children_specs = list(children_specs)[:4] or [{"text": question.text, "value_est": 0.5}]
        remaining = await self.ledger.remaining_budget(question.id)
        config = settings.config.deep_analysis
        child_cap = max(1, remaining // max(1, len(children_specs)))
        child_ids = []
        for spec in children_specs:
            child_id = await self.ledger.open_question(
                str(spec["text"]),
                question.id,
                value_est=question.value_est * config.value_decay,
                cap_tokens=child_cap,
                depth=question.depth + 1,
            )
            child_ids.append(child_id)
        await self.ledger.record_split(question.id, child_ids)
        await self._emit("split", {"qid": question.id, "children": child_ids})
```

> **주의:** `_do_split`의 decompose는 M2에서 LLM 없이도 테스트되도록 `self._split_decompose`를 주입 가능하게 둔다(기본은 `decompose_fn`). AC-c 테스트는 이를 스텁한다. cap 소진/연속 실패로 SPLIT에 진입한 질문은 `record_split`으로 터미널 전이하므로 재선택 풀에서 빠진다(무한 루프 방지).

`service.py`의 `build_orchestrator`에서 dev 프로파일 스레딩 추가(Orchestrator 생성 인자):

```python
    parallel_workers = (
        config.dev_profile.parallel_workers if profile == "dev" else config.parallel_workers
    )
    max_depth = config.dev_profile.max_depth if profile == "dev" else config.max_depth
```
그리고 `Orchestrator(...)` 호출에 `parallel_workers=parallel_workers, max_depth=max_depth,` 전달.

- [ ] **Step 4: 통과 확인 + 기존 계약 테스트 갱신**

`test_orchestrator_contract.py`에서 `should_stop`을 직접 호출/검증하던 부분이 있으면 1인자(ledger)로 갱신. run() end-to-end는 그대로 통과해야 함.

Run: `pytest tests/workflow/deep_analysis/test_orchestrator_m2.py tests/workflow/deep_analysis/test_orchestrator_contract.py -v`
Expected: PASS (M2 AC-a/c/d + 기존 계약)

- [ ] **Step 5: 커밋**

```bash
git add neos/workflow/deep_analysis/orchestrator.py neos/workflow/deep_analysis/service.py tests/workflow/deep_analysis/test_orchestrator_m2.py tests/workflow/deep_analysis/test_orchestrator_contract.py
git commit -m "feat(deep-analysis): parallel worker loop with SPLIT/abandon and sequential commit (M2)"
```

---

### Task 6: AC-b (cap 소진 → SPLIT) 통합 검증 + 회귀 + DECISIONS

**Files:**
- Test: `tests/workflow/deep_analysis/test_orchestrator_m2_split.py`
- Modify: `neos/workflow/deep_analysis/DECISIONS.md` (D11)
- Run: 전체 회귀

**Interfaces:** 신규 없음. AC-b를 독립 검증하고 전체 스위트 회귀.

- [ ] **Step 1: 실패 테스트 작성 (AC-b: cap 소진 질문이 SPLIT)**

```python
# tests/workflow/deep_analysis/test_orchestrator_m2_split.py
import pytest
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.models import WorkerResult, ProposedClaim, ProposedEvidence, ProposedBlob, Verdict
from neos.workflow.deep_analysis.ledger import create_run
from neos.database.connection import db_manager
from sqlalchemy import text as sql

class OkGrader:
    async def grade(self, claim): return Verdict(ok=True)

@pytest.mark.asyncio
async def test_ac_b_cap_exhausted_question_splits():
    # 자식 cap을 작게 만들고, 워커가 cap 이상 토큰을 쓰게 해 다음 라운드 ladder가 SPLIT
    class Spender:
        async def investigate(self, b, e, qid):
            blob = ProposedBlob("hh","http://x",200,"body")
            ev = ProposedEvidence("http://x","body","hh")
            # confidence 낮게 유지해 resolved 전이를 막고 open 복귀 → 재선택 → cap 소진 판정
            return WorkerResult(question_id=qid, status="completed", blobs=[blob],
                                claims=[ProposedClaim("f", 0.3, [ev])], tokens_spent=100000,
                                self_assessment=0.1)
        def flush_partial(self, qid): return WorkerResult(question_id=qid, status="partial")
    async with await db_manager.get_session() as s:
        run_id = await create_run(s, "root?", "dev")
        orch = Orchestrator(s, run_id, lambda: Spender(), OkGrader(),
                            decompose_fn=lambda t: [{"text":"sub","value_est":0.9}],
                            global_token_cap=500000, max_depth=3)
        orch._split_decompose = (lambda text, *a: [{"text":"child","value_est":0.4}])
        await orch.run("root?")
        # 자식(depth1)이 cap 소진 후 SPLIT되어 손자(depth2) 생성
        row = await s.execute(sql("SELECT MAX(depth) FROM deep_analysis_questions WHERE run_id=:r"), {"r": run_id})
        assert row.scalar() >= 2
        await s.rollback()
```

- [ ] **Step 2: 실패 확인 → Step 3: (Task 5 구현으로 이미 통과 가능) 확인**

Run: `pytest tests/workflow/deep_analysis/test_orchestrator_m2_split.py -v`
Expected: PASS (Task 5의 SPLIT 경로가 AC-b를 충족)

- [ ] **Step 4: DECISIONS D11 기록**

`DECISIONS.md`에 추가:

```markdown
## D11. §6.3.2 서브질문 채택은 M3로 연기, M2는 로깅만

**결정:** 워커의 `proposed_subquestions`는 M2에서 `subq_proposed` 이벤트로 로깅만 하고 채택(트리 삽입)하지 않는다.
**근거:** M2 AC(partial/SPLIT/cap/global-cap)에 서브질문 채택은 없다. 채택은 LLM 심사(중복 제거 + value_est 부여, §6.3.2)를 요구하므로 에이전틱 채점이 도입되는 M3와 함께 구현하는 것이 응집적이다. SPLIT(오케스트레이터 권한 decompose)이 트리를 키우므로 M2 AC 충족에 서브질문 채택은 불필요.
**이탈:** 원 설계 §6.3 메인 루프의 `_review_subquestions`를 M2에서 부분 구현(로깅)으로 축소.
**영향:** M3에서 `subq_proposed` 이벤트를 소비해 채택 로직을 붙인다. 로깅이 이미 있으므로 관측 연속성 유지.

## D12. SPLIT decompose는 주입 가능 함수로 분리

**결정:** `_do_split`의 자식 생성 decompose를 `self._split_decompose(text, verified_summaries, dead_ends)` 시임으로 분리한다(기본=`_default_split_decompose`, LLM 호출). FakeWorker 계약 테스트는 이 속성을 sync/async 스텁으로 오버라이드해 LLM 없이 SPLIT 경로를 검증한다. `_ensure_root`/`_do_split` 두 decompose 호출부는 `_maybe_await`로 감싸 sync/async 스텁을 모두 허용한다.
**근거:** 원 설계 §10 "M2 AC 전부 FakeWorker로 재현". SPLIT은 LLM decompose를 호출하므로 주입점이 없으면 계약 테스트가 불가능. §6.3.1대로 decompose 입력에 verified 요약 + dead_ends를 포함한다.
**이탈:** 없음(테스트 가능성 위한 구조적 분리 + §6.3.1 충실).
**영향:** 프로덕션에서는 `_default_split_decompose`(LLM)가 쓰인다.
```

- [ ] **Step 5: 전체 회귀 + 커밋**

Run: `pytest tests/workflow/deep_analysis/ -v`
Expected: PASS (M0/M1/M2 전체)

```bash
git add tests/workflow/deep_analysis/test_orchestrator_m2_split.py neos/workflow/deep_analysis/DECISIONS.md
git commit -m "test(deep-analysis): verify cap-exhaustion split (AC-b); record D11/D12"
```

**M2 완료 게이트:** Task 1–6 통과 = AC-a(partial 커밋) + AC-b(cap→SPLIT) + AC-c(fail_streak→SPLIT) + AC-d(global-cap 정지). M3(에이전틱 채점 + feedback 순환) 착수 가능.

---

## 자체 리뷰 (원 설계 §9 M2 대비)

**1. AC 커버리지:**
- AC-a partial 커밋 → Task 4(`_run_worker` timeout→flush_partial) + Task 5(순차 커밋) + test_orchestrator_m2 `test_ac_a`.
- AC-b cap→SPLIT → Task 2 ladder(spent>=cap) + Task 5 `_do_split` + Task 6 test.
- AC-c fail_streak→SPLIT → Ledger fail_streak++(기존) + Task 2 ladder(fail_streak>=2) + Task 5 + test_ac_c.
- AC-d global-cap 정지 → Task 3 should_stop + test_ac_d.
- §6.2 breadth pass → Task 3. score/gain_decay/aging → Task 2. depth cap abandon → Task 5 `_do_split`.

**2. 플레이스홀더 스캔:** 없음. SPLIT decompose는 주입 함수(D12)로 테스트 가능. 실 Worker 점진 버퍼링은 명시적 연기(범위 밖, flagged).

**3. 타입 일관성:** `Budgeter.select(ledger, k=None)`, `should_stop(ledger)`(1인자 — Task 5에서 오케스트레이터 갱신), `_run_worker(Assignment)->WorkerResult`, `_partition(picks)->(assignments, splits)`, `_do_split(question)`, Ledger `gain_history`/`record_abandon`/`remaining_budget`/`verified_summaries`/`unverified_and_deadends` — 태스크 간 시그니처 일치.

**4. 회귀 리스크:** `should_stop` 시그니처 변경(3인자→1인자)은 M1 오케스트레이터를 깨뜨리므로 Task 3–5를 한 브랜치에서 함께 리뷰(Task 3에 명시). Ledger `pass_completed` payload 확장은 기존 테스트에 무해(추가 키).

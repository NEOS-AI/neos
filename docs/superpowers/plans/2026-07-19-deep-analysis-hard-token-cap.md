# Deep Analysis Hard Token Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `deep_analysis.global_token_cap` a durable hard upper bound for every provider LLM token used by a deep-analysis run, including decomposition, workers, grading, reduction, and report generation.

**Architecture:** Add a run-scoped reservation ledger in `deep_analysis/token_budget.py`, install it through a context variable during orchestration, and enforce it at the central `llm.py` provider boundary. Persist reservation transitions in the existing append-only deep-analysis event log so resume treats interrupted calls as fully spent, then degrade gracefully when no further call can be funded.

**Tech Stack:** Python 3.12, asyncio, contextvars, SQLAlchemy async ORM, pytest, existing deep-analysis cassette and event ledger

## Global Constraints

- The sum of settled actual usage and outstanding reservations must never exceed `global_token_cap`.
- Reserve before provider dispatch and checkpoint the reserve event before dispatch.
- Treat an orphaned durable reservation as fully consumed on resume.
- Do not clamp provider-reported actual usage; raise `TokenBudgetContractError` if it exceeds the reservation.
- Calls outside an active budget scope retain current behavior.
- Preserve existing cassette payload field names and keys when the requested `max_tokens` is not reduced.
- Budget exhaustion completes with the strongest deterministic result available; it is not a failed run.
- Preserve unrelated dirty worktree files.

---

## File structure

- Create `neos/workflow/deep_analysis/token_budget.py`: pure reservation state machine, context scope, exceptions, request bound calculation.
- Modify `neos/workflow/deep_analysis/llm.py`: single enforcement boundary around provider and cassette calls.
- Modify `neos/workflow/deep_analysis/ledger.py`: durable budget event recovery.
- Modify `neos/workflow/deep_analysis/orchestrator.py`: create/recover/scope the budget, stop scheduling, emit exhaustion once.
- Modify `neos/workflow/deep_analysis/budgeter.py`: use the shared budget for global stop decisions.
- Modify `neos/workflow/deep_analysis/worker.py`: convert budget exhaustion to partial worker output.
- Modify `neos/workflow/deep_analysis/graders/agentic.py`: attach stage metadata to agentic claim calls.
- Modify `neos/workflow/deep_analysis/graders/report.py`: retain deterministic report verdict when the agentic call cannot reserve.
- Modify `neos/workflow/deep_analysis/synthesizer.py`: deterministic node/report fallbacks.
- Create `tests/workflow/deep_analysis/test_token_budget.py`: reservation concurrency and recovery-independent unit contracts.
- Modify `tests/workflow/deep_analysis/test_llm.py`: provider-boundary and cassette contracts.
- Modify `tests/workflow/deep_analysis/test_ledger.py`: event recovery contract.
- Create `tests/workflow/deep_analysis/test_orchestrator_token_budget.py`: full-run cap, exhaustion, and resume behavior.
- Modify focused component tests for graceful fallback.
- Modify `docs/TODO_260729.md`: mark section 4 complete and promote section 7.

### Task 1: Implement the pure reservation state machine

**Files:**
- Create: `neos/workflow/deep_analysis/token_budget.py`
- Create: `tests/workflow/deep_analysis/test_token_budget.py`

**Interfaces:**
- Produces: `TokenBudgetExhausted(RuntimeError)`
- Produces: `TokenBudgetContractError(RuntimeError)`
- Produces: `TokenReservation(id: str, reserved_tokens: int, input_bound: int, max_output_tokens: int, stage: str, model: str)`
- Produces: `TokenBudget(cap_tokens: int, consumed_tokens: int = 0, outstanding: Mapping[str, int] | None = None, persist: PersistCallback | None = None)`
- Produces: `TokenBudget.reserve(request: Any, requested_output_tokens: int, *, stage: str, model: str) -> TokenReservation`
- Produces: `TokenBudget.settle(reservation: TokenReservation, actual_tokens: int) -> None`
- Produces: `TokenBudget.release(reservation: TokenReservation) -> None`
- Produces: `TokenBudget.abandon(reservation: TokenReservation) -> None`
- Produces: `TokenBudget.exhausted`, `remaining_tokens`, `consumed_tokens`, and `reserved_tokens` integer properties
- Produces: `active_token_budget() -> TokenBudget | None`
- Produces: `token_budget_scope(budget: TokenBudget)` context manager

- [ ] **Step 1: Write failing budget tests**

Cover these concrete cases with async pytest tests:

```python
async def test_concurrent_reservations_never_exceed_cap():
    budget = TokenBudget(100)
    results = await asyncio.gather(
        *(budget.reserve("x" * 10, 30, stage="worker", model="m") for _ in range(4)),
        return_exceptions=True,
    )
    accepted = [r for r in results if isinstance(r, TokenReservation)]
    assert sum(r.reserved_tokens for r in accepted) <= 100
    assert any(isinstance(r, TokenBudgetExhausted) for r in results)


async def test_settle_refunds_unused_capacity():
    budget = TokenBudget(100)
    reservation = await budget.reserve("x", 50, stage="worker", model="m")
    before = budget.remaining_tokens
    await budget.settle(reservation, 10)
    assert budget.consumed_tokens == 10
    assert budget.remaining_tokens > before


async def test_contract_error_when_actual_exceeds_reservation():
    budget = TokenBudget(100)
    reservation = await budget.reserve("x", 10, stage="worker", model="m")
    with pytest.raises(TokenBudgetContractError):
        await budget.settle(reservation, reservation.reserved_tokens + 1)
```

Also assert persistence event order for reserve/settle/release and context isolation for two concurrently scoped budgets. A reservation can remain outstanding intentionally; add `abandon()` to preserve it as fully consumed after ambiguous provider dispatch.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_token_budget.py -q`

Expected: collection fails because `deep_analysis.token_budget` does not exist.

- [ ] **Step 3: Implement the minimal state machine**

Use an `asyncio.Lock`, UUID reservation IDs, an async persistence callback with signature
`Callable[[str, dict[str, Any]], Awaitable[None]]`, and a `ContextVar[TokenBudget | None]`.
Canonicalize request bounds with:

```python
def conservative_input_bound(request: Any) -> int:
    encoded = json.dumps(
        request,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return len(encoded) + 64
```

`reserve()` must compute input bound, require at least one output token, reduce output to available capacity, persist `token_budget_reserved` while holding the lock, and only then expose the reservation. `settle()` and `release()` persist their terminal event before changing reusable capacity. `abandon()` leaves the reservation outstanding and therefore fully charged.

- [ ] **Step 4: Run unit tests and commit**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_token_budget.py -q`

Expected: all tests pass.

Commit:

```bash
git add neos/workflow/deep_analysis/token_budget.py tests/workflow/deep_analysis/test_token_budget.py
git commit -m "feat: add durable token reservation state machine"
```

### Task 2: Enforce reservations at the central LLM boundary

**Files:**
- Modify: `neos/workflow/deep_analysis/llm.py`
- Modify: `tests/workflow/deep_analysis/test_llm.py`

**Interfaces:**
- Consumes: `active_token_budget`, `TokenBudget.reserve`, `settle`, `release`
- Extends: `call_messages(..., stage: str = "llm")`
- Extends: `call_llm(..., stage: str = "llm")`
- Extends: `call_json(..., stage: str = "llm")`

- [ ] **Step 1: Write failing adapter tests**

Add tests proving that a scoped call reduces provider `max_tokens`, settles actual usage, does not dispatch when the input bound cannot fit, releases on a failure before dispatch, leaves a fully charged outstanding reservation on provider exception/cancellation, budgets each JSON retry separately, and preserves unscoped behavior. Add a cassette test that compares the remembered payload keys to the existing set.

Use a capturing fake client and install a small `TokenBudget` with `token_budget_scope`; assert the fake client call count is zero for exhaustion.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_llm.py -q`

Expected: new scoped-budget assertions fail because calls bypass `TokenBudget`.

- [ ] **Step 3: Add one shared budgeted dispatch helper**

Implement a private helper that:

1. reads `active_token_budget()`;
2. builds a request-bound object from model/messages/tools;
3. reserves and substitutes `reservation.max_output_tokens` for provider/cassette `max_tokens`;
4. settles with response usage on success; and
5. leaves the reservation outstanding and re-raises on `BaseException` after dispatch, including cancellation.

Both `call_messages()` and `call_llm()` must use this helper. `call_json()` forwards `stage`, and every retry re-enters the helper.

- [ ] **Step 4: Run adapter and cassette tests**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_llm.py tests/workflow/deep_analysis/test_cassette.py tests/workflow/deep_analysis/test_discovery.py -q`

Expected: all pass and existing cassette keys remain stable outside a constrained budget.

- [ ] **Step 5: Commit**

```bash
git add neos/workflow/deep_analysis/llm.py tests/workflow/deep_analysis/test_llm.py
git commit -m "feat: enforce token reservations at LLM boundary"
```

### Task 3: Recover durable token state from the event ledger

**Files:**
- Modify: `neos/workflow/deep_analysis/ledger.py`
- Modify: `tests/workflow/deep_analysis/test_ledger.py`

**Interfaces:**
- Produces: `Ledger.token_budget_state() -> tuple[int, dict[str, int]]`
- Consumes event kinds: `token_budget_reserved`, `token_budget_settled`, `token_budget_released`

- [ ] **Step 1: Write failing recovery tests**

Insert reserve/settle/release events for one run and unrelated events for another. Assert settled actual usage is summed, released reservations cost zero, and an orphaned reservation is returned in the outstanding mapping at full reservation value. Include malformed/duplicate terminal events and require first valid terminal event to win without crashing recovery.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_ledger.py -q`

Expected: failure because `token_budget_state` is missing.

- [ ] **Step 3: Implement run-scoped ordered replay**

Select `kind, payload` for the three event kinds ordered by `DAEvent.seq`. Decode defensively, track reservations by ID, move settled actual usage into `consumed`, remove released entries, and ignore malformed or duplicate terminal records.

- [ ] **Step 4: Run tests and commit**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_ledger.py -q`

Expected: all pass.

```bash
git add neos/workflow/deep_analysis/ledger.py tests/workflow/deep_analysis/test_ledger.py
git commit -m "feat: recover durable deep analysis token budget"
```

### Task 4: Scope the budget across orchestration and global stopping

**Files:**
- Modify: `neos/workflow/deep_analysis/orchestrator.py`
- Modify: `neos/workflow/deep_analysis/budgeter.py`
- Create: `tests/workflow/deep_analysis/test_orchestrator_token_budget.py`
- Modify: `tests/workflow/deep_analysis/test_budgeter.py`

**Interfaces:**
- Consumes: `Ledger.token_budget_state()` and `token_budget_scope()`
- Produces: `Orchestrator.token_budget: TokenBudget`
- Produces: one durable/emitted `token_budget_exhausted` event per run
- Changes: `Budgeter(..., token_budget: TokenBudget | None = None)`

- [ ] **Step 1: Write failing orchestration tests**

Create fake LLM clients whose responses report fixed usage and run multiple parallel questions. Assert total `token_budget_settled.actual_tokens` plus orphaned reservations never exceeds the cap. Add resume coverage starting from one orphaned reserve event, and assert no new provider call occurs when it consumes the remainder. Add a budgeter unit test showing shared budget exhaustion stops even when `ledger.total_spent()` is below cap.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_orchestrator_token_budget.py tests/workflow/deep_analysis/test_budgeter.py -q`

Expected: failures because the orchestrator does not create a scope and budgeter still reads worker-only totals.

- [ ] **Step 3: Install and persist the run budget**

At the start of `run()`, recover `(consumed, outstanding)`, construct `TokenBudget`, and use `with token_budget_scope(self.token_budget)` around recovery/root creation/rounds/finalization. The persistence callback must call `ledger.log(kind, None, payload)` and `_checkpoint()`.

Catch the first `TokenBudgetExhausted` at the orchestration boundary, log and emit one `token_budget_exhausted` payload, set an in-memory flag, and continue to deterministic finalization. Pass `self.token_budget` to `Budgeter`; `should_stop()` uses its exhausted/remaining state when present and retains the old ledger fallback for isolated callers.

- [ ] **Step 4: Add stage labels to orchestrator calls**

Pass `stage="decompose"` and `stage="split_decompose"` to the two direct `call_json` sites. Add cap/consumed/reserved/exhausted fields to completed and failure observability payloads.

- [ ] **Step 5: Run tests and commit**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_orchestrator_token_budget.py tests/workflow/deep_analysis/test_budgeter.py tests/workflow/deep_analysis/test_orchestrator_resume.py -q`

Expected: all pass.

```bash
git add neos/workflow/deep_analysis/orchestrator.py neos/workflow/deep_analysis/budgeter.py tests/workflow/deep_analysis/test_orchestrator_token_budget.py tests/workflow/deep_analysis/test_budgeter.py
git commit -m "feat: scope hard token cap across deep analysis runs"
```

### Task 5: Add component-level graceful degradation

**Files:**
- Modify: `neos/workflow/deep_analysis/worker.py`
- Modify: `neos/workflow/deep_analysis/graders/agentic.py`
- Modify: `neos/workflow/deep_analysis/graders/report.py`
- Modify: `neos/workflow/deep_analysis/synthesizer.py`
- Modify: `tests/workflow/deep_analysis/test_worker.py`
- Modify: `tests/workflow/deep_analysis/test_agentic_grader.py`
- Modify: `tests/workflow/deep_analysis/test_report_grader.py`
- Modify: `tests/workflow/deep_analysis/test_synthesizer.py`

**Interfaces:**
- Consumes: `TokenBudgetExhausted`
- Produces: `Synthesizer.deterministic_report(...) -> str`

- [ ] **Step 1: Write failing exhaustion tests**

Use fake calls that raise `TokenBudgetExhausted` and assert:

- worker `investigate()` returns `flush_partial()` data with `status="partial"`;
- orchestrator `_grade()` returns the already successful deterministic verdict when its optional agentic tier exhausts the budget;
- report grader returns its deterministic verdict;
- node reduction returns a caveated child-summary fallback;
- final assembly returns Markdown containing `## 요약`, `## 본문`, `## 한계와 미확인 사항`, and `## 출처`, plus the token-cap limitation.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_worker.py tests/workflow/deep_analysis/test_agentic_grader.py tests/workflow/deep_analysis/test_report_grader.py tests/workflow/deep_analysis/test_synthesizer.py -q`

Expected: new tests fail with uncaught `TokenBudgetExhausted`.

- [ ] **Step 3: Implement minimal fallbacks and stage labels**

Catch only `TokenBudgetExhausted`; do not broaden existing exception handling. Preserve accumulated worker state. In `Orchestrator._grade()`, retain the deterministic verdict when the optional agentic tier exhausts. In `ReportGrader`, retain the deterministic report verdict. In synthesizer, render deterministic verified content and caveats without calling an LLM. Label component calls `discovery`, `worker_analysis`, `worker_repair`, `claim_grading`, `node_reduction`, `report_assembly`, and `report_grading`.

- [ ] **Step 4: Run component and orchestration tests**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_worker.py tests/workflow/deep_analysis/test_agentic_grader.py tests/workflow/deep_analysis/test_report_grader.py tests/workflow/deep_analysis/test_synthesizer.py tests/workflow/deep_analysis/test_orchestrator_token_budget.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add neos/workflow/deep_analysis/worker.py neos/workflow/deep_analysis/graders/agentic.py neos/workflow/deep_analysis/graders/report.py neos/workflow/deep_analysis/synthesizer.py tests/workflow/deep_analysis
git commit -m "feat: degrade gracefully at deep analysis token cap"
```

### Task 6: Reconcile documentation and verify the complete change

**Files:**
- Modify: `docs/TODO_260729.md`
- Verify: all changed deep-analysis files

**Interfaces:**
- Consumes: verified hard-cap implementation
- Produces: section 4 resolution and section 7 as the next implementation priority

- [ ] **Step 1: Update section 4 and the priority table**

Record that the cap now covers all central deep-analysis LLM calls, uses durable pre-dispatch reservations, fails closed on orphaned reservations, and degrades to deterministic output. Promote §7 verified-ratio diagnosis to priority 1 and keep §5, §15, §6, §8 in their relative order.

- [ ] **Step 2: Run focused hard-cap verification**

Run:

```bash
.venv/bin/pytest tests/workflow/deep_analysis/test_token_budget.py tests/workflow/deep_analysis/test_llm.py tests/workflow/deep_analysis/test_ledger.py tests/workflow/deep_analysis/test_orchestrator_token_budget.py -q
```

Expected: all pass.

- [ ] **Step 3: Run the full deep-analysis suite**

Run: `.venv/bin/pytest tests/workflow/deep_analysis -q`

Expected: all pass.

- [ ] **Step 4: Run CI backend boundaries**

Run sequentially:

```bash
.venv/bin/pytest tests/workflow -q
.venv/bin/pytest tests/api -q
```

Expected: workflow and API suites pass. Record infrastructure failures exactly; do not describe unavailable tests as passing.

- [ ] **Step 5: Validate diff and documentation**

Run:

```bash
git diff --check
rg -n "§4|하드 상한|다음 권고 순서" docs/TODO_260729.md
git status --short
```

Expected: no whitespace errors; only planned files plus pre-existing user changes are present.

- [ ] **Step 6: Commit documentation**

```bash
git add docs/TODO_260729.md
git commit -m "docs: close deep analysis token cap task"
```

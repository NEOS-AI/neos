# Deep Analysis Truncation Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record an append-only event whenever an LLM response is cut off at `max_tokens`, so silent truncation stops being invisible.

**Architecture:** `LLMResponse.stop_reason` is already captured and never read. The budgeted dispatch path already writes events through `TokenBudget`, and both the budget and the response are in scope immediately after settlement — so one event write there covers every deep-analysis LLM call.

**Tech Stack:** Python 3.12, pytest, Ruff, PostgreSQL.

## Why this exists

A truncated response fails JSON parsing and yields nothing. In the 07-31 baseline, 28 of 97 LLM calls stopped at `max_tokens` and 18 were mid-claim — every claim in them lost. That cost an entire baseline run, and it was only discovered because a cassette happened to have been recorded. Nothing in `deep_analysis/` inspects `stop_reason` (`llm.py:148` captures it; no reader exists).

Without this, the next silent truncation is equally invisible.

## Global Constraints

- **`deep_analysis_events` is append-only** (D8). INSERT only — never update or delete.
- **Observation only.** Do not change any threshold, prompt, model, cap, sampling rate, retry, or parsing behaviour. Nothing about what the pipeline *does* may change — only what it records.
- **Zero added LLM or network cost.** The event is written from data already in hand.
- **No response text in the payload.** Stage, model, and token counts only. Truncated text is exactly where a half-formed claim would sit, and it has no diagnostic value beyond the counts.
- **Do not touch** `worker.py`, `orchestrator.py`, `fetch.py`, `claim_entailment.py`, `discard_recall.py`, or any grader.
- **No new dependencies. No network or LLM in tests.**
- No `Co-Authored-By` trailer.
- Test command: `HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest ... -q -o log_cli=false --disable-warnings`.

## Out of Scope

- Fixing `worker_repair`, which still caps at the effort budget and has the same truncation defect. Deliberately deferred so the pending attribution sample keeps one variable.
- Any live run.
- Retrying or raising on truncation. This plan makes truncation *visible*, not handled — changing behaviour would confound the next measurement.

## File Structure

| File | Responsibility |
|---|---|
| `neos/workflow/deep_analysis/token_budget.py` | A public method to record a truncation event |
| `neos/workflow/deep_analysis/llm.py` | Call it after settlement when `stop_reason == "max_tokens"` |
| `tests/workflow/deep_analysis/test_llm.py` | Prove the event fires on truncation and not otherwise |
| `docs/DEEP_ANALYSIS_HARNESS_DESIGN.md` | Add the new kind to the event catalogue |

---

### Task 1: Emit `llm_truncated` from the budgeted dispatch

**Files:**
- Modify: `neos/workflow/deep_analysis/token_budget.py`
- Modify: `neos/workflow/deep_analysis/llm.py` (right after `budget.settle(...)`, ~line 210-214)
- Modify: `docs/DEEP_ANALYSIS_HARNESS_DESIGN.md` (event-kind catalogue, ~line 158-160)
- Test: `tests/workflow/deep_analysis/test_llm.py`

**Interfaces:**
- Produces: `TokenBudget.record_truncation(*, stage: str, model: str, max_output_tokens: int, output_tokens: int) -> None`
- Produces: `deep_analysis_events` rows with `kind="llm_truncated"` and payload `{"stage", "model", "max_output_tokens", "output_tokens"}`

- [ ] **Step 1: Read the seam before writing anything**

Confirm all four:

1. `neos/workflow/deep_analysis/token_budget.py` has `async def _persist_event(self, kind, payload)` (~line 180) which forwards to `self._persist` when set.
2. `TokenBudget.reserve` already emits `"token_budget_reserved"` through it (~line 116).
3. `neos/workflow/deep_analysis/llm.py` calls `await budget.settle(reservation, ...)` and then `return response` (~lines 210-214), with both `budget` and `response` in scope.
4. `LLMResponse` has a `stop_reason` field (`llm.py:33`), populated at `llm.py:148`.

If any differs, stop and report — the plan's premise would be wrong.

Also determine what the reservation object exposes for `stage`, `model`, and `max_output_tokens` (see `TokenReservation` construction ~line 107-114) — you need those for the payload and should take them from the reservation rather than re-deriving.

- [ ] **Step 2: Write the failing tests**

In `tests/workflow/deep_analysis/test_llm.py`. Read that file first and reuse its existing fakes for the client and the budget — do not invent new ones if a suitable fake exists.

The tests must cover three cases:

```python
async def test_truncated_response_records_an_llm_truncated_event():
    # A response stopped at max_tokens must leave a durable trace: this bug
    # cost a whole baseline run precisely because nothing recorded it.
    # ... arrange a budget whose _persist captures (kind, payload) pairs,
    #     and a fake client returning stop_reason="max_tokens"
    events = [...]  # captured (kind, payload)

    assert any(kind == "llm_truncated" for kind, _ in events)
    payload = next(p for k, p in events if k == "llm_truncated")
    assert payload["stage"] == "worker_analysis"
    assert payload["max_output_tokens"] > 0
    assert payload["output_tokens"] > 0
    # No response text may reach the event.
    assert "text" not in payload
    assert "content" not in payload


async def test_completed_response_records_no_truncation_event():
    # stop_reason="end_turn" must produce nothing.
    assert not any(kind == "llm_truncated" for kind, _ in events)


async def test_truncation_event_does_not_replace_settlement():
    # The budget must still settle on the real usage; the new event is
    # additive, not a substitute.
    assert any(kind == "token_budget_settled" for kind, _ in events)
```

Fill in the arrange blocks from the file's existing patterns. If `test_llm.py` has no budget fake, build the smallest one that captures `_persist` calls — the assertions above are what matter.

- [ ] **Step 3: Run tests to verify they fail**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_llm.py -q -o log_cli=false --disable-warnings
```
Expected: FAIL — no `llm_truncated` event exists yet.

- [ ] **Step 4: Add the recorder to `TokenBudget`**

In `neos/workflow/deep_analysis/token_budget.py`, beside the other event-emitting code:

```python
    async def record_truncation(
        self,
        *,
        stage: str,
        model: str,
        max_output_tokens: int,
        output_tokens: int,
    ) -> None:
        """Record that a response was cut off at its output ceiling.

        A truncated response fails JSON parsing and yields nothing, so the
        work it represents is lost silently. Nothing read ``stop_reason``
        before this; a whole baseline run was spent before the loss was
        noticed, and only because a cassette happened to exist.

        Payload carries counts and identifiers only — never response text.
        """
        await self._persist_event(
            "llm_truncated",
            {
                "stage": stage,
                "model": model,
                "max_output_tokens": max_output_tokens,
                "output_tokens": output_tokens,
            },
        )
```

- [ ] **Step 5: Call it from the dispatch**

In `neos/workflow/deep_analysis/llm.py`, immediately after the existing `await budget.settle(...)` and before `return response`:

```python
    if response.stop_reason == "max_tokens":
        await budget.record_truncation(
            stage=reservation.stage,
            model=reservation.model,
            max_output_tokens=reservation.max_output_tokens,
            output_tokens=response.output_tokens,
        )
```

Take `stage`, `model`, and `max_output_tokens` from `reservation` — they are already correct there and re-deriving risks drift. Verify those attribute names against `TokenReservation` before using them.

**Settlement must stay first.** If the event write ever fails, the budget must already be settled — never trade accounting correctness for observability.

- [ ] **Step 6: Run tests to verify they pass**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_llm.py -q -o log_cli=false --disable-warnings
```
Expected: PASS.

- [ ] **Step 7: Prove the test bites**

Comment out the `if response.stop_reason == "max_tokens":` block, confirm the truncation test FAILS, then restore and verify with `git diff` that the restore is exact.

Record this in your report. Four tests on this project have shipped green while proving nothing, and a break-check caught every one.

- [ ] **Step 8: Add the kind to the catalogue**

`docs/DEEP_ANALYSIS_HARNESS_DESIGN.md` lists the canonical `deep_analysis_events` kinds around line 158-160. Add `llm_truncated` with a one-line description matching the surrounding style. It is permanent and always-on, like `claim_discarded`.

- [ ] **Step 9: Full suite and lint**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/ -q -o log_cli=false --disable-warnings

/Users/ywsung/Desktop/neos/.venv/bin/ruff check \
  neos/workflow/deep_analysis/ tests/workflow/deep_analysis/
```

Baseline is **420 passed, 0 failed**. Expect 420 plus your new tests.

**If a pre-existing test breaks, report it rather than adjusting it** — a test that counted events by total, or asserted an exact event sequence, is telling you something about another consumer.

- [ ] **Step 10: Commit**

```bash
git add neos/workflow/deep_analysis/token_budget.py neos/workflow/deep_analysis/llm.py \
        tests/workflow/deep_analysis/test_llm.py docs/DEEP_ANALYSIS_HARNESS_DESIGN.md
git commit -m "feat(deep-analysis): record when an LLM response is truncated"
```

---

## Done When

- A response with `stop_reason == "max_tokens"` writes one `llm_truncated` event carrying stage, model, and both token counts — and no response text.
- A completed response writes none.
- Settlement still happens first and is unaffected.
- The new test fails without the change.
- The event catalogue lists the kind.
- Full suite green, Ruff clean, and no pipeline behaviour changed.

## What This Buys The Next Run

The pending comparison sample can be checked for truncation directly from the event log instead of requiring a cassette: count `llm_truncated` by stage. Against the 07-31 baseline's 28 truncations (18 claim-bearing, all at 2000 tokens), the `worker_analysis` share should fall to near zero. Any remaining truncations at other stages — `worker_repair` especially, which still caps at the effort budget — become visible rather than inferred.

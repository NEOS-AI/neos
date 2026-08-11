# Deep Analysis Entailment Ceiling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the claim-entailment response being truncated, which silently skips the discard filter for an entire batch of claims.

**Architecture:** `_ENTAILMENT_MAX_OUTPUT_TOKENS = 1200` is a module-level literal in `worker.py`. Move it to configuration and raise it to a value calibrated from real entailment responses.

**Tech Stack:** Python 3.12, pytest, Ruff.

## Evidence

From the 08-02 sample (`20260802T052306Z`), via the `llm_truncated` event log and the recorded cassette:

- **1 of 18 `claim_entailment` calls truncated at exactly 1200** — a 5.6% rate, higher than the judge ceiling's 1.5% that was just fixed.
- 17 completed responses used **97–923** output tokens (median 358). The tail was already approaching the ceiling.
- The truncated response carried only **183 characters** of text for its 1200 tokens (~45 text tokens) — the rest was adaptive thinking, which counts against `max_tokens` but is stripped from content (`llm.py:137` hardcodes `thinking_enabled=True`).

**Why this is worse than lost work.** On truncation, `parse_json` raises and `worker.py:377-381` does `return claims` — **the entire batch bypasses the entailment discard filter.** Claims that entailment would have discarded or narrowed pass through untouched, and nothing records that it happened.

**This will get worse, not better.** Entailment batches scale with the number of claims a worker produces, and the worker-truncation fix just tripled claim production (dev 3→9, total graded 26→73). Larger batches mean longer responses against the same ceiling.

## Global Constraints

- **Change exactly one variable: the entailment output ceiling.** Do not change entailment logic, the prompt, the model, grader thresholds, sampling, or `apply_entailment_results`.
- **Do NOT change the fail-open at `worker.py:377-381`.** Returning the original batch on a parse failure is deliberate (a bad entailment response must not destroy claims). This removes a *cause* of it firing, not the behaviour.
- **No magic numbers.** The literal moves into `neos/config/schema.py`.
- **Do not touch** `fetch.py`, `llm.py`, `token_budget.py`, `graders/`, `discard_recall.py`, or `claim_entailment.py`.
- **No new dependencies. No network or LLM in tests.**
- No `Co-Authored-By` trailer.
- Test command: `HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest ... -q -o log_cli=false --disable-warnings`.

## Out of Scope

- `worker_analysis` still truncating at 4000 (12 occurrences) — separate ceiling, separate calibration.
- `report.py:136 max_tokens=400`, which fail-opens unconditionally and gates the whole report.
- Budget-clamped truncations at odd values — raising a ceiling cannot fix those.
- Propagating `stop_reason` so callers can distinguish "truncated" from "garbage". That is the durable fix for this whole class and deserves its own plan; ceilings only move the cliff.
- Any live run.

## Calibration

Completed responses: 97–923 output tokens, max **923** — censored by the 1200 ceiling. The truncated case spent roughly **1155 tokens on thinking alone**.

So the budget must accommodate two things at once: thinking (observed up to ~1155) and the results array (observed up to ~923 including thinking, so text alone is smaller). Sizing for both plus headroom gives **3000** — about 3.2× the largest completed response.

Deliberately generous, for the same asymmetry as the judge ceiling: an unused ceiling costs nothing because `settle` records only actual usage, while an undersized one silently disables the discard filter for a whole batch. Do not optimise it downward.

## File Structure

| File | Responsibility |
|---|---|
| `neos/config/schema.py` | `entailment_max_output_tokens` setting |
| `neos/workflow/deep_analysis/worker.py` | Use it; delete the module-level literal |
| `scripts/deep_analysis_funnel_sample.py` | Record it in the config fingerprint |
| `tests/workflow/deep_analysis/test_worker_entailment.py:148` | Assert against config, not a literal |

---

### Task 1: Configurable entailment output ceiling

**Files:**
- Modify: `neos/config/schema.py` (`DeepAnalysisConfig`)
- Modify: `neos/workflow/deep_analysis/worker.py:36` (delete constant) and `:362` (use config)
- Modify: `scripts/deep_analysis_funnel_sample.py` (`_fingerprint`)
- Modify: `tests/workflow/deep_analysis/test_worker_entailment.py:148`

**Interfaces:**
- Produces: `settings.config.deep_analysis.entailment_max_output_tokens: int`

- [ ] **Step 1: Confirm the call site and the existing test**

Confirm `_ENTAILMENT_MAX_OUTPUT_TOKENS = 1200` at `worker.py:36`, used at `worker.py:362` inside `_refine_claims`'s `call_llm(...)`. Confirm the parse-failure path a few lines below does `return claims`.

**Also confirm `tests/workflow/deep_analysis/test_worker_entailment.py:148` currently asserts `llm.max_tokens[1] == 1200`.** That test legitimately pins this ceiling — it is expected to change, and Step 5 rewrites it to read config instead of a literal so it never needs touching again. This is the one pre-existing test you *should* update; report anything else that breaks rather than adjusting it.

- [ ] **Step 2: Add the setting**

In `neos/config/schema.py` on `DeepAnalysisConfig`, beside `judge_max_output_tokens`:

```python
    # One batched entailment call decides keep/narrow/discard for every claim a
    # worker produced. On truncation, parse_json raises and worker.py returns
    # the original batch — the whole batch bypasses the discard filter, and
    # nothing records it. At 1200, one of eighteen calls in sample
    # 20260802T052306Z was cut; completed responses ran 97-923 tokens.
    # As with the judge ceiling, adaptive thinking (llm.py:137) consumes most
    # of the budget invisibly — the truncated call spent ~1155 tokens on
    # thinking for 183 characters of text. Batches also grow with claim
    # production, which recently tripled, so this ceiling binds more over time.
    entailment_max_output_tokens: int = 3000
```

- [ ] **Step 3: Write the failing test**

Rewrite `tests/workflow/deep_analysis/test_worker_entailment.py:148`'s assertion to read the config value, and add a second assertion pinning that the ceiling is no longer the old literal:

```python
    assert llm.max_tokens[1] == settings.config.deep_analysis.entailment_max_output_tokens
    assert llm.max_tokens[1] > 1200  # the old literal must no longer bind
```

Import `settings` from `neos.config.settings` if the file does not already. Confirm index `[1]` is still the entailment call — the file's `ScriptedLLM` records `max_tokens` per call in order, and index 0 is the worker analysis. Verify rather than assume.

- [ ] **Step 4: Run to verify it fails**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_worker_entailment.py -q -o log_cli=false --disable-warnings
```
Expected: FAIL with `assert 1200 == 3000`.

- [ ] **Step 5: Use the setting**

`_refine_claims` does **not** currently have config in scope. `worker.py`'s established pattern is a method-local `config = settings.config.deep_analysis` (see lines 125, 179, 436) — follow it, and `settings` is already imported in the module.

```python
        config = settings.config.deep_analysis
        ...
                max_tokens=config.entailment_max_output_tokens,
```

Then **delete `_ENTAILMENT_MAX_OUTPUT_TOKENS` from line 36** — leaving it would be a dead magic number. Confirm no other reference exists (`grep -rn "_ENTAILMENT_MAX_OUTPUT_TOKENS"`).

- [ ] **Step 6: Run to verify it passes**

Same command as Step 4. Expected: PASS.

- [ ] **Step 7: Prove the test bites**

Set the call site back to a literal `1200`, confirm the test FAILS, restore, and verify with `git diff` that the restore is exact. Record it.

Six tests on this project have shipped green while proving nothing; a break-check caught every one.

- [ ] **Step 8: Record it in the fingerprint**

In `scripts/deep_analysis_funnel_sample.py`'s `_fingerprint()`, beside `judge_max_output_tokens`:

```python
        "entailment_max_output_tokens": config.entailment_max_output_tokens,
```

- [ ] **Step 9: Full suite and lint**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/ -q -o log_cli=false --disable-warnings

/Users/ywsung/Desktop/neos/.venv/bin/ruff check \
  neos/workflow/deep_analysis/ neos/config/schema.py \
  scripts/deep_analysis_funnel_sample.py tests/workflow/deep_analysis/
```

Baseline is **424 passed, 0 failed**.

- [ ] **Step 10: Commit**

```bash
git add neos/config/schema.py neos/workflow/deep_analysis/worker.py \
        scripts/deep_analysis_funnel_sample.py \
        tests/workflow/deep_analysis/test_worker_entailment.py
git commit -m "fix(deep-analysis): stop truncation disabling the entailment filter"
```

---

## Done When

- The entailment call's ceiling comes from config; the module literal is gone.
- The test reads the config value and fails at the old 1200.
- The fingerprint records it.
- The parse-failure fail-open is unchanged.
- Full suite green, Ruff clean, nothing else touched.

## Verifying The Effect

Needs a separate authorised run. From the event log: `llm_truncated` with `stage="claim_entailment"` (was 1 of 18) should reach zero. Watch also whether `claim_discarded` becomes non-zero — a skipped filter is one candidate explanation for it sitting at 0 across two samples, though not established as the cause.

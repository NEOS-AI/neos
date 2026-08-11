# Deep Analysis Worker Output Truncation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the worker's analysis response being truncated mid-JSON, which silently discards every claim it was producing.

**Architecture:** The worker caps its analysis response at `min(effort.token_cap, worker_max_output_tokens)`. `effort.token_cap` is a *budget* concept, not a per-response output allowance, and for SCOUT it is 2000 — below what a claim-bearing response needs. The fix stops using the budget cap as an output limit for that one call.

**Tech Stack:** Python 3.12, pytest, Ruff.

## Evidence

From the 07-31 baseline run's recorded cassette (395 entries, no tokens spent to analyse):

- **28 of 97 LLM calls stopped at `max_tokens`.**
- **18 of those were producing claims**, every one cut at exactly **2000 output tokens** — the SCOUT `effort.token_cap`.
- A truncated sample, cut mid-evidence: `{"status": "partial", "claims": [{"text": "제53조 제2항의 오픈소스 예외는…", "confidence": 0.6, "evidence": [{"sou`
- Successful claim-bearing responses used **242–1861 output tokens** (median 849) and carried 0–5 claims. The ceiling sits right at the boundary: what fits, fits barely; what doesn't, loses everything.

Truncated JSON fails to parse, so the worker returns no claims at all. This is why the 07-31 baseline produced 3 dev claims against prompt-v3's 38, and why fixing extraction and fetch blocking did not restore claim production.

## Global Constraints

- **Change exactly one variable.** No extraction, grader threshold, prompt, model, sampling, cap, retry, or entailment changes. The next sample must attribute any claim recovery to this alone.
- **Do not change `effort.token_cap` values.** They are the effort budget and are used elsewhere (`orchestrator.py:428`). This plan changes only which value bounds one LLM response.
- **`worker_max_output_tokens` (currently 4000) is the ceiling** and already exists in `neos/config/schema.py:757`. Do not raise it in this plan — 4000 gives more than 2× the observed successful maximum of 1861.
- **Only the `worker_analysis` call.** Three sites use `min(effort_config.token_cap, config.worker_max_output_tokens)` and they are NOT interchangeable — verified:
  - `worker.py:132` — the `run_discovery(...)` call. **Not this one.**
  - `worker.py:243-252` — `call_json(..., stage="worker_analysis")`, whose result is read at line 256 as `data.get("claims", [])`. **This is the one to change.**
  - `worker.py:456-465` — `stage="worker_repair"`. Same defect class, but changing it too would be a second variable. **Leave it**, and note it in your report as known-and-deferred.
- **No magic numbers.** Limits come from settings.
- **No network or LLM in tests.**
- No `Co-Authored-By` trailer.
- Test command: `HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest ... -q -o log_cli=false --disable-warnings`.

## Out of Scope

- Making truncation visible (an event or counter when `stop_reason == "max_tokens"`). Genuinely valuable — this bug was invisible for the entire session and only the cassette exposed it — but it is a second change.
- Any live run. Measuring the effect needs a separate authorised sample.

## File Structure

| File | Responsibility |
|---|---|
| `neos/workflow/deep_analysis/worker.py` | Use the output ceiling, not the effort budget, for the `worker_analysis` call (line ~243-252) |
| `tests/workflow/deep_analysis/test_worker*.py` | Prove the analysis call is not bounded by the SCOUT budget cap |

---

### Task 1: Stop bounding the analysis response by the effort budget

**Files:**
- Modify: `neos/workflow/deep_analysis/worker.py` — the `max_tokens` argument of the `stage="worker_analysis"` call (~line 243-252)
- Test: an existing worker test file — pick the one that already exercises `investigate` with a fake LLM (`tests/workflow/deep_analysis/test_worker_entailment.py` has `ScriptedLLM` and records `max_tokens` per call)

**Interfaces:**
- No new public interface. Behaviour change: the analysis call's `max_tokens` becomes `settings.config.deep_analysis.worker_max_output_tokens`.

- [ ] **Step 1: Confirm the call site and the recorded limit**

Find the `call_json(...)` invocation with `stage="worker_analysis"` (around line 243) and confirm its `max_tokens` currently reads:

```python
            max_tokens=min(
                effort_config.token_cap,
                config.worker_max_output_tokens,
            ),
```

Confirm the very next block reads claims from it (`data.get("claims", [])`, ~line 256) — that is what makes this the claim-producing call.

Also confirm `worker_max_output_tokens: int = 4000` (`neos/config/schema.py:757`) and `token_cap=2000` for `scout`.

**Do not go by line number alone** — an earlier draft of this plan pointed at line 132, which is the discovery call, not the analysis call. Anchor on `stage="worker_analysis"`.

- [ ] **Step 2: Write the failing test**

`tests/workflow/deep_analysis/test_worker_entailment.py` already has a `ScriptedLLM` that appends every call's `max_tokens` to `self.max_tokens`, plus `Search`, `Fetch`, and the `Worker(...).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")` pattern. Reuse them; do not write a second fake.

```python
@pytest.mark.asyncio
async def test_scout_analysis_is_not_capped_by_the_effort_budget():
    # effort.token_cap is a budget, not a per-response output allowance.
    # SCOUT's 2000 truncated claim-bearing responses mid-JSON, losing every
    # claim in them. The analysis call must use the output ceiling instead.
    llm = ScriptedLLM(json.dumps({"results": [{"index": 0, "action": "keep"},
                                              {"index": 1, "action": "keep"},
                                              {"index": 2, "action": "keep"}]}))

    await Worker(
        Search(), fetch_fn=Fetch(), llm_client=llm
    ).investigate("Q\n{fetched_evidence}", Effort.SCOUT, "q")

    analysis_max_tokens = llm.max_tokens[0]
    assert analysis_max_tokens == settings.config.deep_analysis.worker_max_output_tokens
    assert analysis_max_tokens > settings.config.deep_analysis.effort["scout"].token_cap
```

Import `settings` from `neos.config.settings` if the file does not already.

Confirm `llm.max_tokens[0]` really is the analysis call and not something earlier — inspect `ScriptedLLM`'s ordering before relying on the index. If the analysis call is not first, use the correct index and say so in your report.

- [ ] **Step 3: Run the test to verify it fails**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_worker_entailment.py -q -o log_cli=false --disable-warnings
```
Expected: FAIL with `assert 2000 == 4000`.

- [ ] **Step 4: Make the change**

At the `stage="worker_analysis"` call:

```python
            # effort.token_cap is the effort's BUDGET, not a per-response
            # output allowance. Using it here truncated claim-bearing
            # responses mid-JSON at SCOUT's 2000 tokens — 18 of them in the
            # 20260731T130316Z sample — and a truncated response parses to
            # zero claims, so every claim in it was silently lost. The budget
            # is still enforced, by the token budget layer.
            max_tokens=config.worker_max_output_tokens,
```

Do not touch the discovery call (~132) or the `worker_repair` call (~456), and do not change any `token_cap` value.

- [ ] **Step 5: Run the test to verify it passes**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_worker_entailment.py -q -o log_cli=false --disable-warnings
```
Expected: PASS.

- [ ] **Step 6: Prove the test bites**

Revert line 132 to `min(effort_config.token_cap, config.worker_max_output_tokens)`, re-run, confirm FAIL, then restore. Verify with `git diff -- neos/workflow/deep_analysis/worker.py` that the restore is exact.

Record this in your report. Three tests on this project have shipped green while proving nothing; the break-check is what caught each one.

- [ ] **Step 7: Confirm the budget is still enforced**

The concern with removing a cap is unbounded spend. Show it is bounded elsewhere: find where the run-level token budget reserves against LLM calls (`neos/workflow/deep_analysis/token_budget.py`, and `TokenBudgetExhausted` handling in `worker.py`), and state in your report which mechanism still bounds total spend now that the per-response `min()` is gone.

If you cannot find such a mechanism, stop and report `BLOCKED` — that would mean this change removes the only bound, and I need to know before it lands.

- [ ] **Step 8: Full suite and lint**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/ -q -o log_cli=false --disable-warnings

/Users/ywsung/Desktop/neos/.venv/bin/ruff check \
  neos/workflow/deep_analysis/ tests/workflow/deep_analysis/
```

Baseline is **419 passed, 0 failed**. Expect 419 plus your new test.

**If a pre-existing test asserts the old 2000 limit, do not silently update it.** Report it — a test pinning the truncating behaviour is worth knowing about.

- [ ] **Step 9: Commit**

```bash
git add neos/workflow/deep_analysis/worker.py tests/workflow/deep_analysis/test_worker_entailment.py
git commit -m "fix(deep-analysis): stop the effort budget truncating worker claims"
```

---

## Done When

- The analysis call's `max_tokens` is the output ceiling, not the effort budget.
- The new test fails without the change.
- Total spend is still bounded, and the report names the mechanism.
- Full suite green, Ruff clean, no `token_cap` value changed.

## Verifying The Effect

Needs a separate authorised run. Against the 07-31 baseline: **dev proposed/graded (was 3/3)** and **truncated LLM calls in the new cassette (was 28/97, 18 claim-bearing)**. One variable changed, so recovery is attributable to this. Note the comparison requires a **re-recorded** cassette — replaying 07-31's returns the old truncated responses.


## Plan Correction (2026-08-01, before execution)

An earlier draft of this plan named `worker.py:132` as the truncating site. That
is the `run_discovery(...)` call. The claim-producing call is
`call_json(..., stage="worker_analysis")` at ~243-252, whose result is read as
`data.get("claims", [])` at ~256. Validating the plan's premises against the
code caught this before any work started; the plan now anchors on the `stage=`
string rather than a line number.

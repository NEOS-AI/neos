# Deep Analysis Judge Ceiling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the agentic judge's response being truncated, which converts a rejection into an acceptance.

**Architecture:** The judge call hardcodes `max_tokens=300`. Move that to configuration and raise it to a value calibrated from real judge responses.

**Tech Stack:** Python 3.12, pytest, Ruff.

## Evidence

From the 08-02 sample (`20260802T052306Z`), read from the `llm_truncated` event log and the recorded cassette:

- **4 `claim_grading` responses were truncated at exactly 300 output tokens.**
- 66 completed judge responses used **60–282** output tokens, median 104. The tail was already pressed against the ceiling.
- A truncated response, cut mid-`rationale`:
  `{"label": "CONTRADICTS", "rationale": "증거는 범용 AI 모델 제공자가 다운스트림…`

**Why this matters more than lost work.** Truncated JSON raises `JSONParseError`, which `graders/agentic.py:92-93` turns into `_judge_failed(...)`. For a **non-mandatory** claim (`value_est × confidence < agentic_threshold`, default 0.35), `_judge_failed` returns `Verdict(ok=True, label=None)` — the D14 fail-open. So a judge that said **CONTRADICTS** is recorded as a pass.

Up to 4 of that sample's 70 verified claims may be judge rejections that were flipped by a token limit.

## Global Constraints

- **Change exactly one variable: the judge's output ceiling.** Do not change `agentic_threshold`, `agentic_sample_rate`, the judge prompt, the judge model, or any grader logic.
- **Do NOT change the D14 fail-open behaviour** in `_judge_failed`. It is deliberate policy and touching it is a separate decision with its own consequences. This plan removes a *cause* of the fail-open firing, not the fail-open itself.
- **No magic numbers.** The ceiling moves from a literal into `neos/config/schema.py`.
- **Do not touch** `worker.py`, `fetch.py`, `llm.py`, `token_budget.py`, `claim_entailment.py`, or `discard_recall.py`.
- **No new dependencies. No network or LLM in tests.**
- No `Co-Authored-By` trailer.
- Test command: `HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest ... -q -o log_cli=false --disable-warnings`.

## Out of Scope

- `worker_analysis` still truncating at its 4000 ceiling (12 occurrences) — a separate ceiling with its own calibration.
- Budget-clamped truncations (7+ occurrences at odd values like 106, 487, 983). Raising a ceiling cannot fix those; they are the `dev` profile's 20,000 global cap genuinely running out.
- `worker_repair`, which still caps at the effort budget.
- Any live run.

## Calibration

Observed completed judge responses: min 60, median 104, **max 282** — and that maximum is *censored*, since anything longer was cut at 300. The `rationale` field is free-form Korean text, so the tail is genuinely variable.

**800** is roughly 2.8× the observed (censored) maximum and ~7.7× the median. It is deliberately generous relative to the data because the cost of being wrong is asymmetric: an over-large ceiling costs nothing when unused (`settle` records only actual usage, and unused reservation is released), while an under-sized one silently flips verdicts.

## File Structure

| File | Responsibility |
|---|---|
| `neos/config/schema.py` | `judge_max_output_tokens` setting |
| `neos/workflow/deep_analysis/graders/agentic.py` | Accept `max_output_tokens` by injection; use it instead of the literal 300 |
| `neos/workflow/deep_analysis/service.py:73` | Pass the config value (production) |
| `scripts/deep_analysis_discard_recall.py:134` | Pass the config value (phase-2 scoring) |
| `scripts/deep_analysis_funnel_sample.py` | Record it in the config fingerprint |
| `tests/workflow/deep_analysis/test_agentic_grader.py` | Prove the judge call uses the injected ceiling; update constructions |
| `tests/workflow/deep_analysis/test_discard_recall_scoring.py:245` | Update construction |

---

### Task 1: Configurable judge output ceiling

**Files:**
- Modify: `neos/config/schema.py` (`DeepAnalysisConfig`)
- Modify: `neos/workflow/deep_analysis/graders/agentic.py:87`
- Modify: `scripts/deep_analysis_funnel_sample.py` (`_fingerprint`)
- Test: `tests/workflow/deep_analysis/test_agentic_grader.py`

**Interfaces:**
- Produces: `settings.config.deep_analysis.judge_max_output_tokens: int`

- [ ] **Step 1: Confirm the call site**

`neos/workflow/deep_analysis/graders/agentic.py` around line 84-91 should read:

```python
            data, _ = await call_json(
                self.judge_model,
                prompt,
                max_tokens=300,
                client=self.llm_client,
                cassette=self.cassette,
                stage="claim_grading",
            )
```

and the next lines should catch `JSONParseError` into `self._judge_failed(mandatory, "judge_unparseable")`. If either differs, stop and report.

- [ ] **Step 2: Add the setting**

In `neos/config/schema.py`, on `DeepAnalysisConfig` beside the other deep-analysis limits:

```python
    # The judge returns {"label", "rationale"}; the rationale is free-form
    # Korean and variable in length. At the previous hardcoded 300, four
    # responses in sample 20260802T052306Z were cut mid-rationale — and a
    # truncated response raises JSONParseError, which _judge_failed turns
    # into a D14 fail-open pass for non-mandatory claims. One of those had
    # already emitted "label": "CONTRADICTS", so a rejection became an
    # acceptance. Completed responses measured 60-282 tokens (median 104),
    # a maximum censored by the old ceiling.
    judge_max_output_tokens: int = 800
```

- [ ] **Step 3: Write the failing test**

In `tests/workflow/deep_analysis/test_agentic_grader.py`. Read that file first and reuse its existing fakes — it already constructs `AgenticGrader` and a fake client. Do not invent a second fake.

```python
@pytest.mark.asyncio
async def test_judge_call_uses_the_configured_output_ceiling():
    # A truncated judge response raises JSONParseError, which _judge_failed
    # fail-opens to ok=True for non-mandatory claims — turning a CONTRADICTS
    # verdict into a pass. The ceiling must come from config, not a literal.
    # ... arrange a fake client that records max_tokens per call, and a claim
    #     that reaches the judge (mandatory, so the sampling gate is bypassed)

    assert recorded_max_tokens == settings.config.deep_analysis.judge_max_output_tokens
    assert recorded_max_tokens > 300  # the old literal must no longer bind
```

Fill in the arrange block from the file's existing patterns. Make the claim **mandatory** (`value_est × confidence >= agentic_threshold`, default 0.35) so it is definitely judged — otherwise the sampling gate may skip the call and the assertion never runs. Verify that by reading `is_mandatory`.

- [ ] **Step 4: Run the test to verify it fails**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_agentic_grader.py -q -o log_cli=false --disable-warnings
```
Expected: FAIL with `assert 300 == 800`.

- [ ] **Step 5: Use the setting**

**Verified: `agentic.py` imports no settings at all, and takes every limit by
constructor injection** — `judge_model`, `threshold`, `sample_rate` are all
keyword-only with **no defaults**. Follow that convention exactly; do not add a
global settings read to this module.

Add a required keyword-only parameter:

```python
class AgenticGrader:
    def __init__(self, *, judge_model, threshold, sample_rate, max_output_tokens,
                 llm_client=None, cassette=None, sampler=None):
        ...
        self.max_output_tokens = max_output_tokens
```

and use it at the call site:

```python
                max_tokens=self.max_output_tokens,
```

**No default.** `threshold` and `sample_rate` have none, and a default here would
be exactly the magic number this plan removes.

That makes it a required argument at all 13 construction sites — 2 production,
11 test:

- `neos/workflow/deep_analysis/service.py:73` → `max_output_tokens=config.judge_max_output_tokens`
- `scripts/deep_analysis_discard_recall.py:134` → same, from `settings.config.deep_analysis`
- 11 sites in `tests/workflow/deep_analysis/test_agentic_grader.py` and one in
  `test_discard_recall_scoring.py:245` → pass an explicit literal; tests may use
  literals, and an explicit value there documents what each test assumes.

Update every site. If you find a construction site not in this list, report it.

- [ ] **Step 6: Run the test to verify it passes**

Same command as Step 4. Expected: PASS.

- [ ] **Step 7: Prove the test bites**

Revert the line to `max_tokens=300`, confirm the test FAILS, restore, and verify with `git diff` that the restore is exact. Record it in your report — five tests on this project have shipped green while proving nothing, and a break-check caught every one.

- [ ] **Step 8: Record it in the fingerprint**

In `scripts/deep_analysis_funnel_sample.py`'s `_fingerprint()`, beside `decompose_max_tokens` and `fetch_user_agent`:

```python
        "judge_max_output_tokens": config.judge_max_output_tokens,
```

It changes grading outcomes, so an artifact should record which value produced it.

- [ ] **Step 9: Full suite and lint**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/ -q -o log_cli=false --disable-warnings

/Users/ywsung/Desktop/neos/.venv/bin/ruff check \
  neos/workflow/deep_analysis/ neos/config/schema.py \
  scripts/deep_analysis_funnel_sample.py tests/workflow/deep_analysis/
```

Baseline is **423 passed, 0 failed**. Expect 423 plus your new test.

**If a pre-existing test asserts `max_tokens == 300` for the judge, report it rather than updating it** — it would be pinning the truncating behaviour, and I want to know.

- [ ] **Step 10: Commit**

```bash
git add neos/config/schema.py neos/workflow/deep_analysis/graders/agentic.py \
        scripts/deep_analysis_funnel_sample.py tests/workflow/deep_analysis/test_agentic_grader.py
git commit -m "fix(deep-analysis): stop truncation flipping judge rejections to passes"
```

---

## Done When

- The judge's `max_tokens` comes from `judge_max_output_tokens`, not a literal.
- The new test fails at the old 300.
- The fingerprint records the value.
- `_judge_failed`'s fail-open behaviour is unchanged.
- Full suite green, Ruff clean, no other limit touched.

## Verifying The Effect

Needs a separate authorised run. From the event log: `llm_truncated` events with `stage="claim_grading"` (was 4) should reach zero. Anything remaining at an *odd* ceiling value is budget-clamped, not ceiling-limited, and is a different problem.


## Plan Correction (2026-08-02, before execution)

An earlier draft told the implementer to read settings inside `agentic.py`.
Validating against the code showed that module imports no settings and takes
every limit by constructor injection with no defaults. The plan now follows that
convention, which widens the change to 13 construction sites but keeps the
module's design intact.

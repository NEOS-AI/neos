# Funnel Clamp Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve safe confidence-clamp telemetry in the aggregate `dev_funnel`, then run and document the bounded `mixed-v1` 5+1 comparison.

**Architecture:** Extend the existing explicit funnel-field aggregation with the same four source-count buckets used by Ledger, analytics, and artifact sanitization. Derive the aggregate total from sanitized bucket sums, integrate the fix into local `dev`, and only then execute the existing bounded production-like runner.

**Tech Stack:** Python 3.12, pytest, Ruff, PostgreSQL, existing Anthropic/Tavily funnel runner.

## Global Constraints

- Accepted buckets are exactly `0`, `1`, `2`, and `3_plus`.
- Accepted bucket values are non-negative integers; booleans are invalid.
- Missing, malformed, negative, boolean, and unknown values contribute zero.
- `confidence_clamped_count` is derived from aggregate buckets; per-run declared totals are ignored.
- Do not change prompts, graders, thresholds, sampling, discovery, models, token caps, or wall-clock caps.
- Never print or persist API keys, provider responses, claim text, URLs, excerpts, or requested confidence in evaluation telemetry.

---

### Task 1: Aggregate Clamp Buckets Safely

**Files:**
- Modify: `neos/workflow/deep_analysis/funnel_sample.py`
- Test: `tests/workflow/deep_analysis/test_funnel_sample.py`

**Interfaces:**
- Consumes: `aggregate_funnels(funnels: list[dict]) -> dict` input `claim_funnel` objects.
- Produces: aggregate fields `confidence_clamped_by_source_count: dict[str, int]` and `confidence_clamped_count: int`.

- [ ] **Step 1: Write the failing aggregation regression**

Add a test with two funnels. Include valid counts, a missing bucket, a boolean,
a negative integer, an unknown key, and inconsistent declared totals:

```python
def test_aggregate_funnels_derives_safe_confidence_clamp_total():
    first = {
        **FUNNEL_A,
        "confidence_clamped_count": 999,
        "confidence_clamped_by_source_count": {
            "0": 1, "1": 2, "2": True, "3_plus": 3, "unknown": 50,
        },
    }
    second = {
        **FUNNEL_B,
        "confidence_clamped_count": 999,
        "confidence_clamped_by_source_count": {"0": -1, "2": 4},
    }

    combined = aggregate_funnels([first, second])

    assert combined["confidence_clamped_by_source_count"] == {
        "0": 1, "1": 2, "2": 4, "3_plus": 3,
    }
    assert combined["confidence_clamped_count"] == 10
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample.py::test_aggregate_funnels_derives_safe_confidence_clamp_total -q`

Expected: FAIL because `aggregate_funnels()` does not produce the clamp fields.

- [ ] **Step 3: Implement exact-bucket aggregation**

Add `_CONFIDENCE_CLAMP_BUCKETS = ("0", "1", "2", "3_plus")` and a private
validation helper:

```python
def _safe_count(value: object) -> int:
    return (
        value
        if isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
        else 0
    )
```

In `aggregate_funnels()`, sum each exact bucket from dictionary-valued input
and derive `confidence_clamped_count` with `sum()` over the aggregate buckets.
Do not read any input `confidence_clamped_count`.

- [ ] **Step 4: Verify GREEN and adjacent artifact behavior**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample_runner.py -q -o log_cli=false --disable-warnings`

Run: `.venv/bin/ruff check neos/workflow/deep_analysis/funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample_runner.py`

Expected: 28 tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit**

```bash
git add neos/workflow/deep_analysis/funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample.py
git commit -m "fix(deep-analysis): aggregate confidence clamp buckets"
```

---

### Task 2: Integrate, Execute the 5+1 Sample, and Document Results

**Files:**
- Modify after measured results: `docs/TODO_260729.md`
- Generate: `artifacts/deep-analysis-funnel/<timestamp>/manifest.json`
- Generate: `artifacts/deep-analysis-funnel/<timestamp>/funnel.json`
- Generate: `artifacts/deep-analysis-funnel/<timestamp>/report.md`

**Interfaces:**
- Consumes: `scripts/deep_analysis_funnel_sample.py` and configured local PostgreSQL, Anthropic, and Tavily credentials.
- Produces: one bounded `mixed-v1` result with five `dev` observations and one selected `default` observation.

- [ ] **Step 1: Verify the feature branch before integration**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample_runner.py tests/workflow/deep_analysis/test_deep_analysis_analytics.py -q -o log_cli=false --disable-warnings`

Run: `.venv/bin/ruff check neos/workflow/deep_analysis/funnel_sample.py neos/workflow/deep_analysis/funnel_sample_runner.py tests/workflow/deep_analysis/test_funnel_sample.py tests/workflow/deep_analysis/test_funnel_sample_runner.py`

Expected: all tests and Ruff pass.

- [ ] **Step 2: Merge locally into the latest `dev` and re-verify**

Merge `codex/funnel-clamp-aggregation` into local `dev` without modifying or
staging unrelated user changes. Re-run the Task 2 Step 1 commands from the
main checkout and confirm zero failures.

- [ ] **Step 3: Run the bounded production-like sample**

Run from local `dev`:

```bash
.venv/bin/python scripts/deep_analysis_funnel_sample.py \
  --output-root artifacts/deep-analysis-funnel
```

Expected: the script prints one new artifact directory followed by six run
IDs. If preflight fails, stop without changing policy or fabricating results.

- [ ] **Step 4: Validate the generated artifact**

Read the new `manifest.json`, `funnel.json`, and `report.md`. Confirm:

```python
assert manifest["question_set_version"] == "mixed-v1"
assert len(funnel["dev_runs"]) == 5
assert funnel["default_run"] is not None
assert funnel["dev_funnel"]["confidence_clamped_count"] == sum(
    funnel["dev_funnel"]["confidence_clamped_by_source_count"].values()
)
```

Also confirm no API key or disallowed content field appears in the artifacts.

- [ ] **Step 5: Document the measured comparison**

Update `docs/TODO_260729.md` with the artifact timestamp, six run IDs,
completed/failed status, dev and default funnel totals, clamp bucket totals,
reject-code and verified-rate deltas against `20260720T142912Z`, and explicit
limitations. Do not claim causal improvement from one 5+1 sample.

- [ ] **Step 6: Commit documentation only**

```bash
git add docs/TODO_260729.md
git commit -m "docs: record post-calibration funnel sample"
```

Do not commit generated evaluation artifacts unless the repository's existing
tracking policy already tracks that artifact directory.

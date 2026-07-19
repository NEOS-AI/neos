# Verified Claim Funnel Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add run-scoped diagnostics that identify whether low verified-claim yield comes from evidence scarcity, deterministic validation, or agentic judgment without changing any grading decision.

**Architecture:** Graders attach safe aggregate diagnostics to the existing `Verdict`; the orchestrator merges deterministic and optional agentic tier metadata; the ledger writes one `claim_graded` event before each existing outcome event. Analytics defensively aggregates those events with existing `pass_completed` records into a backward-compatible `claim_funnel` signal.

**Tech Stack:** Python 3.12, dataclasses, SQLAlchemy async, PostgreSQL, pytest, Ruff

## Global Constraints

- Do not change thresholds, confidence caps, sampling, prompts, discovery breadth, or existing outcome-event meanings.
- Do not add a table, migration, URL, excerpt, claim text, or raw blob content to diagnostics.
- `excerpt_matches()` acceptance behavior must remain identical.
- Malformed diagnostic payloads count in raw totals but never crash or contaminate numeric aggregates.
- Preserve existing `Verdict(...)` callers through a default-empty diagnostics mapping.

---

### Task 1: Observable Quote Matching and Deterministic Diagnostics

**Files:**
- Modify: `neos/workflow/deep_analysis/text_norm.py`
- Modify: `neos/workflow/deep_analysis/models.py`
- Modify: `neos/workflow/deep_analysis/graders/deterministic.py`
- Modify: `tests/workflow/deep_analysis/test_text_norm.py`
- Modify: `tests/workflow/deep_analysis/test_deterministic_grader.py`

**Interfaces:**
- Produces: `excerpt_match_score(excerpt: str, raw: str, threshold: float) -> float`
- Preserves: `excerpt_matches(excerpt: str, raw: str, threshold: float) -> bool`
- Extends: `Verdict.diagnostics: dict[str, Any]`

- [ ] **Step 1: Write failing quote-score tests**

Import `excerpt_match_score` and assert exact containment is `1.0`, empty/unrelated input is `0.0`, and for every existing match fixture:

```python
score = excerpt_match_score(excerpt, raw, threshold)
assert excerpt_matches(excerpt, raw, threshold) == (score >= threshold)
```

- [ ] **Step 2: Run the score tests and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_text_norm.py -q`

Expected: collection fails because `excerpt_match_score` is missing.

- [ ] **Step 3: Extract score calculation without changing the algorithm**

Move the exact-first and anchor-window maximum into `excerpt_match_score`; retain the existing threshold-dependent tolerance and make `excerpt_matches` return `excerpt_match_score(excerpt, raw, threshold) >= threshold`. Add parity tests across thresholds `0.80`, `0.92`, and `0.99` so no acceptance decision changes.

- [ ] **Step 4: Write failing deterministic diagnostic tests**

For no evidence, dead source, quote mismatch, confidence inflation, and pass, assert:

```python
assert verdict.diagnostics == {
    "deterministic": "rejected",
    "deterministic_code": "E_NO_EVIDENCE",
    "evidence_count": 0,
    "source_count": 0,
    "fetched_source_count": 0,
    "dead_source_count": 0,
    "excerpt_chars": 0,
    "best_quote_score": None,
    "quote_threshold": 0.92,
}
```

Use the corresponding values for the other four outcomes.

- [ ] **Step 5: Add the compatible verdict field and grader metrics**

Add:

```python
@dataclass
class Verdict:
    ...
    diagnostics: dict[str, Any] = field(default_factory=dict)
```

Compute only aggregate counts and scores. Return diagnostics on every deterministic exit without storing content.

- [ ] **Step 6: Run focused tests and commit**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_text_norm.py tests/workflow/deep_analysis/test_deterministic_grader.py tests/workflow/deep_analysis/test_core_models.py -q`

Expected: all pass.

Commit:

```bash
git add neos/workflow/deep_analysis/text_norm.py neos/workflow/deep_analysis/models.py neos/workflow/deep_analysis/graders/deterministic.py tests/workflow/deep_analysis/test_text_norm.py tests/workflow/deep_analysis/test_deterministic_grader.py
git commit -m "feat(deep-analysis): expose deterministic grading diagnostics"
```

### Task 2: Preserve Diagnostics Across the Agentic Tier

**Files:**
- Modify: `neos/workflow/deep_analysis/graders/agentic.py`
- Modify: `neos/workflow/deep_analysis/orchestrator.py`
- Modify: `tests/workflow/deep_analysis/test_agentic_grader.py`
- Modify: `tests/workflow/deep_analysis/test_orchestrator_m3.py`
- Modify: `tests/workflow/deep_analysis/test_orchestrator_token_budget.py`

**Interfaces:**
- Produces agentic states: `skipped`, `attempted_passed`, `attempted_rejected`
- Merges states: `not_configured`, produced states, and `exhausted`

- [ ] **Step 1: Write failing agentic-state tests**

Assert unsampled claims return `diagnostics={"agentic": "skipped"}`; parsed SUPPORTS returns `attempted_passed`; PARTIAL/UNRELATED/CONTRADICTS and judge parse failures return `attempted_rejected` when the verdict rejects.

- [ ] **Step 2: Write failing orchestrator merge tests**

Use a deterministic verdict containing evidence metrics, then assert `_grade()` preserves those keys while adding:

```python
assert verdict.diagnostics["agentic"] == "not_configured"
assert verdict.diagnostics["best_quote_score"] == 0.93
```

Cover agentic pass, reject, skip, and `TokenBudgetExhausted -> exhausted`.

- [ ] **Step 3: Run tests and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_agentic_grader.py tests/workflow/deep_analysis/test_orchestrator_m3.py tests/workflow/deep_analysis/test_orchestrator_token_budget.py -q`

Expected: diagnostics assertions fail.

- [ ] **Step 4: Implement non-mutating diagnostic merges**

Use `dataclasses.replace` so frozen assumptions are unnecessary and shared verdict objects in tests are not mutated:

```python
def _with_diagnostics(verdict: Verdict, **extra: Any) -> Verdict:
    return replace(verdict, diagnostics={**verdict.diagnostics, **extra})
```

The deterministic rejection still short-circuits agentic grading and records `agentic="skipped"`; absent agentic configuration records `not_configured`.

- [ ] **Step 5: Run tests and commit**

Run the Step 3 command. Expected: all pass.

Commit:

```bash
git add neos/workflow/deep_analysis/graders/agentic.py neos/workflow/deep_analysis/orchestrator.py tests/workflow/deep_analysis/test_agentic_grader.py tests/workflow/deep_analysis/test_orchestrator_m3.py tests/workflow/deep_analysis/test_orchestrator_token_budget.py
git commit -m "feat(deep-analysis): trace deterministic and agentic grading tiers"
```

### Task 3: Persist One Diagnostic Event per Applied Verdict

**Files:**
- Modify: `neos/workflow/deep_analysis/ledger.py`
- Modify: `tests/workflow/deep_analysis/test_ledger_m3.py`

**Interfaces:**
- Produces event: `claim_graded`
- Payload allowlist: identifiers, outcome/code, tier states, labels, aggregate numeric metrics only

- [ ] **Step 1: Write failing ledger event tests**

For verified, rejected, retry-capped unverified, and repair-regrade paths, query events by sequence and assert `claim_graded` immediately precedes the corresponding outcome event. Assert unknown diagnostic keys such as `raw_text`, `url`, and `excerpt` are absent.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_ledger_m3.py -q`

Expected: no `claim_graded` events exist.

- [ ] **Step 3: Add bounded payload construction**

Add a module-level allowlist and helper:

```python
_CLAIM_DIAGNOSTIC_FIELDS = frozenset({...})

def _claim_diagnostic_payload(claim_id, outcome, verdict):
    payload = {key: verdict.diagnostics[key] for key in _CLAIM_DIAGNOSTIC_FIELDS if key in verdict.diagnostics}
    payload.update(claim_id=claim_id, outcome=outcome, code=verdict.code, agentic_label=verdict.label)
    return payload
```

In `_apply_verdict`, determine the existing final outcome first, log `claim_graded`, then log the existing outcome event and perform the unchanged state transition.

- [ ] **Step 4: Run ledger tests and commit**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_ledger.py tests/workflow/deep_analysis/test_ledger_m2.py tests/workflow/deep_analysis/test_ledger_m3.py -q`

Expected: all pass.

Commit:

```bash
git add neos/workflow/deep_analysis/ledger.py tests/workflow/deep_analysis/test_ledger_m3.py
git commit -m "feat(deep-analysis): persist claim grading diagnostics"
```

### Task 4: Aggregate the Run-Scoped Claim Funnel

**Files:**
- Modify: `neos/workflow/deep_analysis/analytics.py`
- Modify: `tests/workflow/deep_analysis/test_deep_analysis_analytics.py`

**Interfaces:**
- Extends: `DeepAnalysisAnalyticsService.signals()["claim_funnel"]`
- Consumes: `pass_completed` and `claim_graded` payloads

- [ ] **Step 1: Write failing funnel aggregation tests**

Insert two runs containing valid and malformed diagnostic events. For the selected run assert the exact funnel object, including proposed/graded/tier/outcome counts, missing/dead rates, averages, and all five quote buckets. Assert the unrelated run does not contribute.

- [ ] **Step 2: Run test and verify RED**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_deep_analysis_analytics.py -q`

Expected: `claim_funnel` is missing.

- [ ] **Step 3: Extend the payload query and aggregate defensively**

Add `claim_graded` to `_PAYLOAD_KINDS`. Use helpers that reject booleans as numeric values, require non-negative counts, clamp valid scores to `[0, 1]`, and classify:

```python
if score is None:
    bucket = "unavailable"
elif score == 1.0:
    bucket = "exact"
elif score >= threshold:
    bucket = "above_threshold"
elif score >= threshold - 0.05:
    bucket = "near_miss"
else:
    bucket = "low"
```

Use valid graded events as rate and average denominators. Sum `pass_completed.new_claims` for `proposed`.

- [ ] **Step 4: Run analytics and report-task regressions**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_deep_analysis_analytics.py tests/workflow/deep_analysis/test_deep_analysis_report_task.py -q`

Expected: all pass and existing top-level keys remain unchanged.

- [ ] **Step 5: Commit**

```bash
git add neos/workflow/deep_analysis/analytics.py tests/workflow/deep_analysis/test_deep_analysis_analytics.py
git commit -m "feat(deep-analysis): aggregate verified claim funnel"
```

### Task 5: Reconcile Documentation and Verify CI Boundaries

**Files:**
- Modify: `docs/TODO_260729.md`
- Verify: all changed deep-analysis files

**Interfaces:**
- Records §7 diagnosis capability without claiming the bottleneck is fixed
- Promotes §5 to the next implementation priority

- [ ] **Step 1: Update §7 and the priority table**

Document the event contract and funnel metrics. State explicitly that threshold/discovery behavior remains unchanged until production-like runs identify the dominant loss stage. Move §5 to priority 1 while preserving §15, §6, and §8 order.

- [ ] **Step 2: Run focused diagnostics verification**

Run:

```bash
.venv/bin/pytest tests/workflow/deep_analysis/test_text_norm.py tests/workflow/deep_analysis/test_deterministic_grader.py tests/workflow/deep_analysis/test_agentic_grader.py tests/workflow/deep_analysis/test_ledger_m3.py tests/workflow/deep_analysis/test_deep_analysis_analytics.py -q
```

Expected: all pass.

- [ ] **Step 3: Run complete test boundaries sequentially**

Run:

```bash
.venv/bin/pytest tests/workflow/deep_analysis -q
.venv/bin/pytest tests/workflow -q
.venv/bin/pytest tests/api -q
```

Expected: all pass; record allowed environment warnings separately.

- [ ] **Step 4: Run static and diff validation**

Run Ruff over every changed Python file, then:

```bash
git diff --check
rg -n "§7|claim_funnel|다음 권고 순서" docs/TODO_260729.md
git status --short
```

Expected: no lint or whitespace failures and no unrelated files staged.

- [ ] **Step 5: Commit documentation**

```bash
git add docs/TODO_260729.md
git commit -m "docs(deep-analysis): record verified claim diagnostics"
```

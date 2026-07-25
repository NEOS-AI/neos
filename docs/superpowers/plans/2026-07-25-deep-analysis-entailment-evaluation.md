# Deep Analysis Entailment Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run one unchanged, bounded `mixed-v1` five-`dev` plus one-`default` production-like sample after claim-evidence entailment, validate its artifacts, compare it with the prompt-v3 baseline, and document the observed result without causal overclaiming.

**Architecture:** Reuse the existing `scripts/deep_analysis_funnel_sample.py` runner without changing runtime policy. Keep the generated artifact under the existing gitignored output root, record exact validation evidence in the SDD report, then update only `docs/TODO_260729.md` with the measured comparison and limitations.

**Tech Stack:** Python 3.12, pytest, Ruff, PostgreSQL, Anthropic, Tavily, JSON/Markdown funnel artifacts.

## Global Constraints

- Use `QUESTION_SET_VERSION == "mixed-v1"` with exactly the five existing `dev` cases and the runner-selected single `default` case.
- Do not change grader thresholds, sampling, discovery width, prompts, models, token limits, worker limits, depth limits, wall-clock limits, repair behavior, or entailment behavior before or during this sample.
- Run the live sample exactly once. Do not automatically retry failed cases or the full sample.
- Preserve the hard caps already encoded by the selected profiles and runner: `dev` global token budget `20_000`, `default` global token budget `300_000`, and per-run external timeout `3_900` seconds.
- Never print, persist, commit, or include credential values in reports. Artifact validation may check secret absence only as a boolean.
- Generated artifacts remain under ignored `artifacts/deep-analysis-funnel/<UTC timestamp>/` and must not be committed.
- Compare against the complete prompt-v3 artifact `artifacts/deep-analysis-funnel/20260723T124006Z` when locally available and the durable baseline recorded in `docs/TODO_260729.md`: dev verified `19/38`, rejected `19/38`, overclaim `16`, quote mismatch `1`.
- A single 5+1 observation is non-causal. Report provider, search-result, time, and query-selection variability explicitly.

---

### Task 1: Execute and Validate One Bounded `mixed-v1` 5+1 Sample

**Files:**
- Read: `scripts/deep_analysis_funnel_sample.py`
- Read: `neos/workflow/deep_analysis/funnel_sample.py`
- Read: `neos/workflow/deep_analysis/funnel_sample_runner.py`
- Generate ignored: `artifacts/deep-analysis-funnel/<UTC timestamp>/manifest.json`
- Generate ignored: `artifacts/deep-analysis-funnel/<UTC timestamp>/funnel.json`
- Generate ignored: `artifacts/deep-analysis-funnel/<UTC timestamp>/report.md`
- Report only: `.superpowers/sdd/2026-07-25-deep-analysis-entailment-evaluation/task-1-report.md`

**Interfaces:**
- Consumes: existing `mixed-v1` runner, configured local PostgreSQL, `ANTHROPIC_API_KEY`, and `TAVILY_API_KEY`.
- Produces: one immutable artifact path and its six run records, or one truthful failed/incomplete artifact with no retry.

- [ ] **Step 1: Verify the deterministic runner baseline**

Run from the isolated worktree:

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_funnel_sample.py \
  tests/workflow/deep_analysis/test_funnel_sample_runner.py \
  tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py \
  -q -o log_cli=false --disable-warnings

/Users/ywsung/Desktop/neos/.venv/bin/ruff check \
  scripts/deep_analysis_funnel_sample.py \
  neos/workflow/deep_analysis/funnel_sample.py \
  neos/workflow/deep_analysis/funnel_sample_runner.py \
  tests/workflow/deep_analysis/test_funnel_sample.py \
  tests/workflow/deep_analysis/test_funnel_sample_runner.py \
  tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py
```

Expected: all selected tests pass and Ruff reports no errors.

- [ ] **Step 2: Perform a secret-safe live preflight**

If the worktree has no `.env` and `/Users/ywsung/Desktop/neos/.env` exists, create an ignored symlink named `.env` pointing to it. Do not read or print the file. Run:

```bash
/Users/ywsung/Desktop/neos/.venv/bin/python -c \
  'import asyncio; from neos.config.settings import settings; from neos.database.connection import get_session_ctx; from neos.workflow.deep_analysis.funnel_sample_runner import preflight; asyncio.run(preflight(settings, get_session_ctx)); print("preflight passed")'
```

Confirm only boolean availability of the two required API keys plus PostgreSQL connectivity. Never echo credential values.

Expected: preflight succeeds before any provider call. If it fails, report `BLOCKED` without starting the live sample.

- [ ] **Step 3: Run exactly one live sample**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/python \
  scripts/deep_analysis_funnel_sample.py \
  --output-root artifacts/deep-analysis-funnel
```

Expected: the command runs five sequential `dev` cases, selects one representative completed case, then runs one `default` case. Record start/end times, exit status, artifact path, and printed run IDs. Do not retry any failure.

- [ ] **Step 4: Validate the generated artifact structurally**

Export the exact path printed by Step 3 as `ARTIFACT`, then run this read-only validation:

```python
import json
import os
from pathlib import Path

artifact = Path(os.environ["ARTIFACT"])
manifest = json.loads((artifact / "manifest.json").read_text())
funnel = json.loads((artifact / "funnel.json").read_text())

assert manifest["question_set_version"] == "mixed-v1"
assert len(manifest["dev_runs"]) == 5
assert [run["profile"] for run in manifest["dev_runs"]] == ["dev"] * 5
assert manifest["default_run"] is not None
assert manifest["default_run"]["profile"] == "default"
all_runs = [*manifest["dev_runs"], manifest["default_run"]]
assert [run["status"] for run in all_runs] == ["completed"] * 6
run_ids = [run["run_id"] for run in all_runs]
assert all(run_ids)
assert len(run_ids) == len(set(run_ids))
assert len(funnel["dev_runs"]) == 5
assert funnel["default_run"] is not None
assert sum(funnel["dev_funnel"]["safe_confidence_clamp"]["buckets"].values()) == funnel["dev_funnel"]["safe_confidence_clamp"]["total"]
assert funnel["dev_funnel"]["tokens_spent"] == sum(run["tokens_spent"] for run in funnel["dev_runs"])
print("artifact validation passed")
```

Also scan serialized artifact key names and values without printing secrets; record only whether any configured credential value was present. Expected: false for all credentials and no raw content/provider-response fields outside the existing allowlist.

- [ ] **Step 5: Record the execution report**

Write the exact artifact path, run IDs, statuses, elapsed time, token totals, validation results, warnings, and any failure to the ignored Task 1 report. Do not modify tracked files and do not commit the artifact.

---

### Task 2: Compare the Funnel and Document the Evaluation Boundary

**Files:**
- Read: `artifacts/deep-analysis-funnel/20260723T124006Z/funnel.json`
- Read: the exact Task 1 artifact `funnel.json`
- Modify: `docs/TODO_260729.md`
- Report only: `.superpowers/sdd/2026-07-25-deep-analysis-entailment-evaluation/task-2-report.md`

**Interfaces:**
- Consumes: the validated Task 1 artifact path and the prompt-v3 baseline.
- Produces: a durable, non-causal evaluation record with exact counts and the next evidence-based priority.

- [ ] **Step 1: Compute exact comparable metrics**

Read both JSON artifacts when the historical artifact exists. Otherwise use the durable baseline values in `docs/TODO_260729.md` and explicitly mark that source. For the aggregate five-`dev` funnel compute:

```text
proposed
graded
deterministic_rejected
agentic_attempted
agentic_passed
agentic_rejected
agentic_skipped
agentic_exhausted
verified
rejected
unverified
tokens_spent
safe_confidence_clamp total and buckets
rejection_reasons.overclaim
rejection_reasons.quote_mismatch
rejection_reasons.confidence_inflated
rejection_reasons.evidence_missing
rejection_reasons.source_dead
quote_match buckets
```

Calculate `verified / graded` and `rejected / graded` with exact numerators and denominators. Extract the same per-run values for `fact-aspartame` and `policy-london-ulez`.

- [ ] **Step 2: Verify accounting invariants**

For the new aggregate and every run, confirm the documented funnel identities used by existing tests, clamp bucket sum equals clamp total, aggregate token sum equals per-run token sum, and all six statuses are completed. Treat any invariant failure as `BLOCKED`; do not repair the artifact manually.

- [ ] **Step 3: Interpret without changing policy**

State whether the single sample shows an increase, decrease, or no change for:

```text
aggregate verified ratio
aggregate rejected ratio
overclaim count and share of rejections
quote mismatch count and share of rejections
fact-aspartame verified/rejected outcome
policy-london-ulez verified/rejected outcome
token usage
```

Do not attribute changes causally to entailment. Do not recommend threshold, sampling, discovery, model, prompt, or cap changes unless the measured dominant loss stage supports that specific next investigation.

- [ ] **Step 4: Update the TODO document**

Append a dated subsection immediately after the 2026-07-25 entailment implementation paragraph in `docs/TODO_260729.md`. Include:

- artifact timestamp and all six run IDs;
- 5+1 completion and artifact-integrity statement;
- exact aggregate funnel counts and ratios;
- exact `fact-aspartame` and `policy-london-ulez` comparison;
- comparison with `20260723T124006Z`;
- provider/time/query-selection limitations;
- the next recommended investigation based only on the observed dominant loss stage.

- [ ] **Step 5: Verify and commit**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_funnel_sample.py \
  tests/workflow/deep_analysis/test_funnel_sample_runner.py \
  tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py \
  -q -o log_cli=false --disable-warnings

/Users/ywsung/Desktop/neos/.venv/bin/ruff check \
  scripts/deep_analysis_funnel_sample.py \
  neos/workflow/deep_analysis/funnel_sample.py \
  neos/workflow/deep_analysis/funnel_sample_runner.py \
  tests/workflow/deep_analysis/test_funnel_sample.py \
  tests/workflow/deep_analysis/test_funnel_sample_runner.py \
  tests/workflow/deep_analysis/test_funnel_sample_runner_integration.py

git add docs/TODO_260729.md
git commit -m "docs: record claim entailment funnel evaluation"
```

Expected: tests and Ruff pass; only the TODO document is committed.

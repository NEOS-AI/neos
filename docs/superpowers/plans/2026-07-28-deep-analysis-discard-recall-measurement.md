# Deep Analysis Discard Recall Measurement Run Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run one bounded `mixed-v1` 5+1 sample with discard instrumentation active, score the discarded claims offline, and record the false-discard rate against the pre-registered stopping rule — without overclaiming.

**Architecture:** Two live phases separated in time. Phase A runs `scripts/deep_analysis_funnel_sample.py` exactly once to produce a funnel artifact, a recorded cassette, and `claim_discarded` events. Phase B runs `scripts/deep_analysis_discard_recall.py` over that run's IDs to grade every distinct discarded claim and emit a recall artifact. Phase C interprets the result against the rule that was fixed before any data existed, and updates the durable backlog.

**Tech Stack:** Python 3.12, PostgreSQL, Anthropic, Tavily, pytest, Ruff, JSON/Markdown artifacts.

**Design spec:** `docs/superpowers/specs/2026-07-27-deep-analysis-discard-recall-design.md` (Korean). **Implementation:** commits `4e81d92f..901cf913` on `dev`.

## Global Constraints

- **Run the live sample exactly once.** No automatic retry of a failed case or of the whole sample. A failed run is a result, not a reason to re-roll.
- **Change nothing before or during the run:** grader thresholds, sampling, discovery width, prompts, models, token limits, worker/depth/wall-clock limits, repair behaviour, entailment behaviour, or the stopping-rule thresholds.
- **The stopping rule is pre-registered and frozen.** `safe_upper_bound = 0.10`, `over_discard_lower_bound = 0.40`, `wilson_z = 1.96` in `neos/config/schema.py`. Do not tune them after seeing data. Adjusting a threshold to reach a conclusion is the exact failure this rule exists to prevent.
- **`safe` is unreachable at this sample size and that is expected.** It requires ≥35 distinct discards with zero verified; this run is expected to yield roughly 16. An `inconclusive` result is a successful run, not a failed one. See spec §2.3.1.
- Preserve the hard caps already encoded by the profiles and runner: `dev` global token budget `20_000`, `default` global token budget `300_000`, per-run external timeout `3_900` seconds.
- **Never print, persist, or commit credential values.** Boolean presence only.
- Artifacts stay under the gitignored `artifacts/deep-analysis-funnel/` and `artifacts/deep-analysis-discard-recall/` roots and are **never committed**.
- **A single 5+1 observation is not causal.** Provider responses, search results, execution time, and default-query selection all vary between samples. Report that explicitly.
- Test command: `HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest ... -q -o log_cli=false --disable-warnings`. Bare `pytest` fails asyncio marker collection.

## Known Limitations To Carry Into The Write-Up

These are already established; restate them rather than rediscovering them.

- **The grader is not ground truth.** A claim the grader would also have rejected only tells you entailment and the grader agree. The measured rate is a **lower bound** on recall loss (spec §2.2).
- **Scout-effort claims are judged by their own author.** The judge and the SCOUT worker both resolve to `claude-sonnet-5`; DIG resolves to `claude-opus-5` and is unaffected. This skews scout claims toward `verified`, which **overstates** the false-discard rate — conservative with respect to concluding entailment is safe.
- **Phase 2 grades exhaustively**, bypassing the agentic sampling gate that a normal run applies. Claims that would normally pass unjudged are judged here.
- `judge_failed` and `grade_errors` in the recall artifact are live signals: a materially non-zero value means the reported rate is weaker than even the stated lower bound.

## Preconditions

Confirm before Task 1, and stop if any fails:

- `dev` is at or after commit `901cf913` and the working tree is clean.
- `tests/workflow/deep_analysis/` is green (**410 passed** as of `901cf913`).
- `ANTHROPIC_API_KEY` and `TAVILY_API_KEY` are present (boolean check only) and PostgreSQL is reachable.
- `deep_analysis` is enabled for the run profile being used.

---

### Task 1: Execute one bounded `mixed-v1` 5+1 sample

**Files:**
- Read: `scripts/deep_analysis_funnel_sample.py`
- Generate ignored: `artifacts/deep-analysis-funnel/<UTC timestamp>/{manifest.json,funnel.json,report.md,cassette.json}`
- Report only: `.superpowers/sdd/2026-07-28-deep-analysis-discard-recall-measurement/task-1-report.md`

**Interfaces:**
- Consumes: the `mixed-v1` runner, PostgreSQL, `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`.
- Produces: one artifact directory, six run IDs, and `claim_discarded` events in `deep_analysis_events` for those runs. Task 2 consumes the run IDs.

- [ ] **Step 1: Verify the deterministic baseline**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/ -q -o log_cli=false --disable-warnings

/Users/ywsung/Desktop/neos/.venv/bin/ruff check \
  neos/workflow/deep_analysis/ scripts/deep_analysis_funnel_sample.py \
  scripts/deep_analysis_discard_recall.py
```

Expected: 410 passed, 0 failed. Ruff reports no errors in these paths (12 pre-existing `F541` errors in `scripts/test_document_upload.py` are unrelated — do not fix them).

If the suite is not green, report `BLOCKED` and do not start the live run.

- [ ] **Step 2: Secret-safe preflight**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/python -c \
  'import asyncio; from neos.config.settings import settings; from neos.database.connection import get_session_ctx; from neos.workflow.deep_analysis.funnel_sample_runner import preflight; asyncio.run(preflight(settings, get_session_ctx)); print("preflight passed")'
```

Expected: `preflight passed`. This confirms boolean credential presence and database connectivity. Never echo a credential value. If it fails, report `BLOCKED` without starting the run.

- [ ] **Step 3: Run the sample exactly once**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/python \
  scripts/deep_analysis_funnel_sample.py \
  --output-root artifacts/deep-analysis-funnel
```

This runs five sequential `dev` cases, selects one representative completed case, then runs one `default` case. It takes roughly 30 minutes; do not mistake a quiet period for completion, and do not start a second process.

Record: the artifact path printed, all six run IDs, start and end wall-clock times, and the exit status.

**Do not retry any failure.** If a case fails, that is the result — carry it forward and say so.

- [ ] **Step 4: Confirm the artifact is internally consistent**

Export the printed path as `ARTIFACT`, then:

```python
import json, os
from pathlib import Path

artifact = Path(os.environ["ARTIFACT"])
manifest = json.loads((artifact / "manifest.json").read_text())
funnel = json.loads((artifact / "funnel.json").read_text())

assert manifest["question_set_version"] == "mixed-v1"
assert len(manifest["dev_runs"]) == 5
assert [r["profile"] for r in manifest["dev_runs"]] == ["dev"] * 5
assert manifest["default_run"]["profile"] == "default"
all_runs = [*manifest["dev_runs"], manifest["default_run"]]
run_ids = [r["run_id"] for r in all_runs]
assert all(run_ids) and len(run_ids) == len(set(run_ids))

dev_funnel = funnel["dev_funnel"]
assert sum(dev_funnel["confidence_clamped_by_source_count"].values()) == dev_funnel["confidence_clamped_count"]

# Provenance added by the instrumentation work — both must be present.
assert manifest["execution_receipt"] is not None
assert manifest["config_fingerprint"] is not None
print("statuses:", [r["status"] for r in all_runs])
print("run ids:", run_ids)
print("receipt:", manifest["execution_receipt"])
print("validation passed")
```

Note the statuses rather than asserting all six are `completed` — a partial or failed run is a legitimate outcome here and must be reported, not suppressed.

- [ ] **Step 5: Confirm the cassette recorded and discards were captured**

```bash
ls -la "$ARTIFACT"
```

Expected: `cassette.json` exists and is non-trivial in size. An empty or missing cassette means the recording did not flush — report it; do not re-run the sample to fix it.

Then confirm phase 1 actually captured discards, substituting the six run IDs:

```bash
/Users/ywsung/Desktop/neos/.venv/bin/python -c "
import asyncio, json
from sqlalchemy import select, func
from neos.database.connection import get_session_ctx
from neos.database.deep_analysis_models import DAEvent
RUN_IDS = ['<id1>','<id2>','<id3>','<id4>','<id5>','<id6>']
async def main():
    async with get_session_ctx() as s:
        rows = (await s.execute(
            select(DAEvent.run_id, func.count())
            .where(DAEvent.kind=='claim_discarded', DAEvent.run_id.in_(RUN_IDS))
            .group_by(DAEvent.run_id))).all()
        print('claim_discarded per run:', dict(rows))
        print('total events:', sum(c for _, c in rows))
asyncio.run(main())
" 2>/dev/null
```

Record the per-run counts. **A total of zero is a real finding, not a failure** — it would mean entailment discarded nothing in this sample, which is itself the answer. Report it and continue to Task 2, which will report `total_discarded == 0` and `inconclusive`.

- [ ] **Step 6: Write the Task 1 report**

Record the artifact path, all six run IDs and statuses, elapsed times, token totals, the execution receipt and config fingerprint, the cassette size, the per-run `claim_discarded` counts, and any failure. Do not commit the artifact.

---

### Task 2: Score the discarded claims offline

**Files:**
- Read: `scripts/deep_analysis_discard_recall.py`
- Generate ignored: `artifacts/deep-analysis-discard-recall/<UTC timestamp>/{manifest.json,recall.json,claims.json,report.md}`
- Report only: `.superpowers/sdd/2026-07-28-deep-analysis-discard-recall-measurement/task-2-report.md`

**Interfaces:**
- Consumes: the six run IDs from Task 1.
- Produces: `total_discarded`, `verified`, `false_discard_rate`, `wilson_low`, `wilson_high`, `verdict`, plus `raw_events`, `distinct_claims`, `kept_elsewhere`, `malformed`, `judge_failed`, `grade_errors`. Task 3 interprets these.

- [ ] **Step 1: Score all six runs in one invocation**

```bash
/Users/ywsung/Desktop/neos/.venv/bin/python \
  scripts/deep_analysis_discard_recall.py \
  --run-id <id1> --run-id <id2> --run-id <id3> \
  --run-id <id4> --run-id <id5> --run-id <id6> \
  --output-root artifacts/deep-analysis-discard-recall
```

This spends judge-model tokens, one call per distinct discarded claim that clears the deterministic grader. Run it **once**. Record the printed artifact path, start/end times, and exit status.

The script builds a fresh ledger and grader pair per run, so passing all six in one invocation is correct and pools the counts.

- [ ] **Step 2: Read the result and check the collapse is sane**

```python
import json, os
from pathlib import Path

artifact = Path(os.environ["RECALL_ARTIFACT"])
recall = json.loads((artifact / "recall.json").read_text())
manifest = json.loads((artifact / "manifest.json").read_text())

for key in ("raw_events", "distinct_claims", "kept_elsewhere", "malformed",
            "total_discarded", "verified", "false_discard_rate",
            "wilson_low", "wilson_high", "verdict",
            "judge_failed", "grade_errors"):
    print(f"{key}: {recall.get(key)}")

# The collapse must be arithmetically coherent.
assert recall["distinct_claims"] <= recall["raw_events"]
assert recall["total_discarded"] <= recall["distinct_claims"]
assert recall["verified"] <= recall["total_discarded"]
print("config fingerprint:", manifest["config_fingerprint"])
print("per-run breakdown:", manifest.get("per_run"))
```

`raw_events > distinct_claims` means re-investigation produced duplicate discard events, which the dedupe correctly collapsed. `kept_elsewhere > 0` means some discarded claims were kept on another pass and are rightly excluded.

- [ ] **Step 3: Verify no credential reached either artifact**

```python
import json, os
from pathlib import Path
from neos.config.settings import settings

artifact = Path(os.environ["RECALL_ARTIFACT"])
blob = "\n".join((artifact / name).read_text()
                 for name in ("manifest.json", "recall.json", "claims.json", "report.md"))

for name in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY"):
    value = getattr(settings, name, None)
    # Only scan non-empty values — an empty needle matches everything and
    # produces a false positive, which has happened before on this project.
    if value and len(value) >= 32:
        assert value not in blob, f"{name} present in artifact"
        print(f"{name}: absent")
    else:
        print(f"{name}: not set or too short to scan meaningfully")
```

Report only the boolean outcome. Never print a credential value or a fragment of one.

- [ ] **Step 4: Write the Task 2 report**

Record the artifact path, every metric above, the config fingerprint (confirming the recorded judge model and `agentic_sample_rate_override: 1.0`), the per-run breakdown, the credential check result, and the exit status.

---

### Task 3: Interpret against the pre-registered rule and update the backlog

**Files:**
- Read: both artifacts from Tasks 1 and 2
- Modify: `docs/TODO_260729.md`
- Modify: `docs/archive/deep_analysis_task_task_resume.md`
- Report only: `.superpowers/sdd/2026-07-28-deep-analysis-discard-recall-measurement/task-3-report.md`

**Interfaces:**
- Consumes: the metrics from Task 2.
- Produces: a durable, non-causal record and the next recommended step.

- [ ] **Step 1: Apply the stopping rule as written**

Take `verdict` from `recall.json` — do not recompute it by hand, and do not second-guess it:

- `safe` → entailment is not destroying acceptable output. Stop.
- `over_discarding` → entailment is removing claims the pipeline would accept. Next step is loosening toward `narrow`, not threshold tuning.
- `inconclusive` → **do not conclude.** State what sample size would be needed and stop.

Recall that `safe` is unreachable below 35 distinct discards with zero verified, so `inconclusive` is the expected outcome of a single run. That is not a failure and must not be written up as one.

- [ ] **Step 2: Sanity-check the result against its own weaknesses**

Before writing anything, check whether the number deserves the weight the verdict gives it:

- Is `judge_failed` or `grade_errors` a material share of `total_discarded`? If so, the rate is weaker than the stated lower bound and the write-up must say so.
- Is `total_discarded` small enough that the Wilson interval spans most of [0, 1]? Report the interval, not just the point estimate.
- Did `kept_elsewhere` remove a large share? That means re-investigation rescued many claims, which is itself worth reporting.
- Read a sample of `claims.json` by hand. Spec §2.2 requires human adjudication; the point estimate alone does not discharge it. Note whether the "verified" discards look genuinely well-evidenced or look like the scout-self-judging bias.

- [ ] **Step 3: Append a dated subsection to `docs/TODO_260729.md`**

Place it immediately after the 2026-07-26 entailment-evaluation subsection, in Korean to match the surrounding document. Include:

- both artifact timestamps and all six run IDs;
- `raw_events` / `distinct_claims` / `kept_elsewhere` / `total_discarded`, and why they differ;
- `verified`, `false_discard_rate`, the Wilson interval, and the verdict;
- `malformed`, `judge_failed`, `grade_errors`;
- the four limitations from this plan's "Known Limitations" section, stated plainly;
- **no causal claim** — provider, search results, timing, and query selection all varied;
- the next recommended step, driven only by the verdict.

- [ ] **Step 4: Update the resume document**

In `docs/archive/deep_analysis_task_task_resume.md`: mark §5 (claim recall 손실 측정) as complete, add the result to the §1 status table, and write the next frontier based on the verdict. Keep the §6 worktree-hazard section as is.

- [ ] **Step 5: Verify and commit documentation only**

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/ -q -o log_cli=false --disable-warnings

/Users/ywsung/Desktop/neos/.venv/bin/ruff check \
  neos/workflow/deep_analysis/ scripts/deep_analysis_discard_recall.py

git status --short
git add docs/TODO_260729.md docs/archive/deep_analysis_task_task_resume.md
git commit -m "docs: record entailment discard recall measurement"
```

Expected: 410 passed, Ruff clean, and **only the two documentation files staged**. If `git status` shows an artifact directory as untracked-but-not-ignored, stop — the ignore rules are wrong and an artifact is one command away from being committed.

Do not add a `Co-Authored-By` trailer.

---

## Done When

- One `mixed-v1` 5+1 sample has run exactly once, with its artifact, cassette, receipt, and config fingerprint intact.
- Every distinct discarded claim from that sample has been graded exhaustively, with the collapse from raw events to distinct claims recorded.
- `docs/TODO_260729.md` carries the verdict, the interval, the counts, and the limitations, with no causal claim.
- The resume document points at the next frontier.
- No artifact and no credential is committed; no threshold was changed at any point.

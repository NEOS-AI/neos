# Production-like Claim Funnel Sample Design

**Date:** 2026-07-19
**Status:** Approved

## Goal

Collect a reproducible production-like baseline for the deep-analysis verified
claim funnel. Run five mixed questions with the real configured model and
discovery providers under the bounded `dev` profile, select one representative
run by a deterministic rule, rerun that question under `default`, and report
where claims are lost. This work measures the existing policy; it does not
change thresholds, sampling, prompts, discovery breadth, or model selection.

## Why a Reusable Runner

An authenticated API and Celery execution would include more deployment
components but would also mix queue, authentication, and service-availability
failures into a grading-policy experiment. An inline one-off command would be
faster but would not preserve the question set, selection rule, or output
schema. A repository runner that calls the same `create_run` and `execute_run`
application functions keeps the real orchestrator, database ledger, models,
search, fetch, graders, and hard caps while remaining repeatable.

## Fixed Question Set

The runner owns a versioned five-question mixed sample:

1. Two time-sensitive factual verification questions.
2. Two technical comparison questions that require primary evidence.
3. One causal or policy-impact question that should expose evidence-quality
   and overclaim behavior.

Questions must be answerable from public sources, avoid personal data, and be
specific enough to produce verifiable claims. The exact text is stored beside
the runner and included in the output manifest so later baselines can reuse it.

## Execution Flow

1. Perform a preflight without printing secret values: database connectivity,
   configured model-provider credentials, and at least one usable discovery
   provider.
2. Execute the five questions sequentially with profile `dev`. Sequential
   execution makes provider rate-limit and local resource effects easier to
   interpret.
3. Create each run through `create_run`, commit it, and execute it through
   `execute_run`. The existing job-level and effort-level hard bounds remain
   authoritative.
4. A failed run is recorded and does not prevent later samples from running.
   Runs are never silently retried by the sample runner.
5. Read `DeepAnalysisAnalyticsService.signals(run_id=...)` after each run and
   store only aggregate diagnostics plus bounded execution metadata.
6. Select one representative completed dev run and execute its question once
   with profile `default`.
7. Aggregate dev results, compare the representative dev/default pair, and
   produce machine-readable JSON plus a concise Markdown interpretation.

The runner does not submit through Celery because the experiment targets claim
generation and grading rather than dispatch infrastructure. Production API and
worker conformance remain covered by their existing tests.

## Representative Selection

Selection is deterministic and computed only from completed dev runs:

1. Determine the dominant loss stage across the five runs by absolute loss
   count; use loss rate as the tie-breaker.
2. Keep runs that contain at least one loss at that stage.
3. From those candidates, choose the run whose `graded` count is closest to the
   median `graded` count of all completed dev runs.
4. Break remaining ties by the fixed question order.

This avoids choosing only an extreme failure while ensuring the default rerun
actually exercises the observed bottleneck. If no completed run has a graded
claim, select the first completed run. If no dev run completes, skip the
default run and report the preflight or execution failures.

## Loss-stage Interpretation

The report derives stage counts without modifying the analytics service:

- proposal-to-grade loss: `max(proposed - graded, 0)`;
- deterministic rejection: `deterministic_rejected`;
- agentic rejection or exhaustion: `agentic_rejected + agentic_exhausted`;
- final unresolved loss: `rejected + unverified`.

The stages overlap semantically, so the report labels them as diagnostic views,
not an additive Sankey total. It reports both counts and denominators. Quote
score buckets, evidence-missing rate, source-dead rate, average evidence/source
counts, and average excerpt size provide supporting evidence for the dominant
stage.

## Output Contract

Outputs are written below a gitignored local artifact directory and are not
committed automatically. Each execution receives a timestamped directory with:

- `manifest.json`: schema version, question-set version, a `questions` object
  with its own schema version and the exact declared case ID, category, and
  question text for all five inputs, configuration names, run IDs, statuses,
  elapsed seconds, and error type plus a fixed stage code;
- `funnel.json`: per-run signals, aggregate dev signals, representative
  selection details, and the dev/default comparison;
- `report.md`: concise tables, dominant-stage interpretation, caveats, and
  evidence-backed policy recommendations.

No API key, complete model response, fetched document body, excerpt, URL, or
claim text is copied into diagnostics. Questions are retained because they are
the declared evaluation inputs. Artifact-bound failures contain only the
exception type and an allowlisted `execution` or `collection` stage code; they
never contain exception messages. Preflight may name missing configuration
variables but never their values.

## Failure and Cost Boundaries

- Missing credentials or discovery capability fails preflight before paid
  model calls.
- One run failure is isolated; the runner exits non-zero only for failed
  preflight, zero completed dev runs, invalid output, or interrupted execution.
- `KeyboardInterrupt`, cancellation, and process termination propagate.
- The first phase is limited to five `dev` runs. The second phase is limited to
  one `default` run selected by the stated rule.
- Existing `global_token_cap`, effort token caps, wall-clock caps, and job hard
  limits are not raised or bypassed.

## Verification

Unit tests cover question-set stability, loss derivation, aggregation,
representative selection and tie-breaking, failure isolation, redaction, and
output serialization. An integration test uses real PostgreSQL with stubbed
orchestrator execution to prove run creation, scoped analytics collection, and
artifact generation without paid API calls. The real five-plus-one execution
is a manual evaluation command and its artifact path and run IDs are recorded
in the final handoff.

## Decision Boundary After Sampling

The final report may recommend changing one of quote threshold, agentic sample
rate, prompts, discovery breadth, or source handling, but it does not implement
that change. A later change requires its own design and a comparison against
this baseline.

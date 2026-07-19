# Verified Claim Funnel Diagnostics Design

**Date:** 2026-07-19  
**Status:** Approved for planning  
**Scope:** `docs/TODO_260729.md` §7 diagnosis only; no grading-policy changes

## Goal

Explain why deep-analysis runs produce few verified claims without weakening
truthfulness gates. For a run or time window, operators must be able to separate
source/evidence scarcity, deterministic quote validation failures, and agentic
semantic rejection.

## Non-goals

- Do not change `quote_match_threshold`, confidence caps, sampling, prompts, or
  discovery breadth.
- Do not add a database table or migration.
- Do not expose raw fetched source text in events or analytics.
- Do not change the meaning of existing claim outcome events.

## Architecture

Use the append-only `deep_analysis_events` ledger as the diagnostic source.
`pass_completed.new_claims` remains the proposed-claim count. Each applied
verdict additionally emits one `claim_graded` event immediately before the
existing `claim_verified`, `claim_rejected`, or `claim_unverified` event.

`Verdict` gains a default-empty `diagnostics` mapping. This remains an internal
transport field: graders produce diagnostics, the orchestrator merges tier
results, and the ledger serializes a bounded allowlist into `claim_graded`.
Existing callers constructing `Verdict(...)` remain compatible.

## Diagnostic Contract

Each `claim_graded` payload contains:

- `claim_id`: stored claim identifier;
- `outcome`: `verified`, `rejected`, or `unverified`;
- `code`: final rejection code or an empty string;
- `deterministic`: `passed` or `rejected`;
- `deterministic_code`: deterministic rejection code or an empty string;
- `agentic`: `not_configured`, `skipped`, `attempted_passed`,
  `attempted_rejected`, or `exhausted`;
- `agentic_label`: semantic judge label when present;
- `evidence_count` and `source_count`;
- `fetched_source_count` and `dead_source_count`;
- `excerpt_chars`: total attached excerpt characters;
- `best_quote_score`: highest normalized excerpt/source similarity in `[0, 1]`,
  or `null` when no fetched evidence can be compared;
- `quote_threshold`: threshold used by the deterministic grader.

No URLs, excerpts, claim text, or blob contents are written to this diagnostic
event. Numeric fields are non-negative and analytics validates all payloads
defensively.

## Quote Scoring

Refactor evidence matching so
`excerpt_match_score(excerpt, raw, threshold)` returns the best score using the
existing threshold-dependent, exact-first, anchor-adjacent bounded-window
algorithm. Exact containment returns `1.0`; an empty or anchorless excerpt
returns `0.0`. `excerpt_matches(...)` becomes a compatibility wrapper comparing
the score to the same configured threshold.

The algorithm and acceptance decision therefore remain unchanged. The new
score exists only to show whether failures cluster just below the threshold or
represent unrelated text.

## Grading Data Flow

1. `DeterministicGrader` computes all safe metrics while performing its current
   checks and attaches them to its verdict.
2. `Orchestrator._grade` preserves deterministic diagnostics. When no agentic
   grader is configured it records `not_configured`. An agentic grader reports
   whether it skipped sampling or attempted a judgment; the orchestrator merges
   that state with the deterministic metrics.
3. If the optional agentic tier exhausts the run token budget, the deterministic
   pass is retained and the event records `agentic="exhausted"`.
4. `Ledger._apply_verdict` derives the durable outcome using the same retry-cap
   logic it already applies, logs `claim_graded`, then emits the unchanged
   outcome event.
5. Repair regrades use the same path and produce another diagnostic event,
   allowing attempt-based funnel analysis.

## Analytics Output

`DeepAnalysisAnalyticsService.signals()` adds a `claim_funnel` object:

- `proposed`: sum of valid `pass_completed.new_claims` values;
- `graded`: valid `claim_graded` events;
- `deterministic_passed` and `deterministic_rejected`;
- `agentic_attempted`, `agentic_passed`, `agentic_rejected`,
  `agentic_skipped`, and `agentic_exhausted`;
- `verified`, `rejected`, and `unverified` outcomes;
- `evidence_missing_rate` and `source_dead_rate` over graded events;
- `quote_score_buckets`: counts for `exact`, `above_threshold`,
  `near_miss` (within 0.05 below threshold), `low`, and `unavailable`;
- `avg_evidence_count`, `avg_source_count`, and `avg_excerpt_chars`.

Existing top-level analytics keys remain unchanged. Global, `since`, and
`run_id` scoping reuse the current query boundary. Malformed events count in
the raw `totals` map but are excluded from funnel numeric aggregates.

## Error Handling and Privacy

Diagnostic generation must never turn a valid grade into a grading failure.
Missing blobs and malformed numeric data produce conservative counts or
`best_quote_score=null`. Analytics ignores malformed payload fields rather than
raising. Event payloads contain only aggregate metadata and machine-readable
codes, preventing source or user claim content from leaking into observability.

## Testing

- Unit-test score parity: every prior `excerpt_matches` case keeps its result,
  with exact, near-threshold, unrelated, and empty scores covered.
- Unit-test deterministic diagnostics for no evidence, dead source, mismatch,
  confidence inflation, and pass.
- Unit-test orchestrator merging for no agentic grader, sampled skip,
  attempted pass/reject, and token-budget exhaustion.
- PostgreSQL integration-test `claim_graded` ordering and retry-cap outcomes.
- PostgreSQL analytics-test run scoping, funnel counts, quote buckets, averages,
  and malformed payload tolerance.
- Run the complete deep-analysis, workflow, and API suites before merging.

## Success Criteria

A run summary can identify whether its verification bottleneck is upstream
evidence scarcity, deterministic source/quote validation, or agentic semantic
judgment. All existing grading decisions and public analytics keys remain
backward compatible, and no raw research content is added to events.

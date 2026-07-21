# Funnel Clamp Aggregation Design

## Goal

Preserve confidence-clamp telemetry when the production-like funnel runner
combines five `dev` observations, so the post-change `mixed-v1` sample can be
compared with the 2026-07-20 baseline.

## Root Cause

Each run's `claim_funnel` now contains `confidence_clamped_count` and
`confidence_clamped_by_source_count`, and the artifact sanitizer allowlists
them. However, `aggregate_funnels()` only combines the older counter, rate,
average, and quote-bucket fields. The aggregate `dev_funnel` therefore drops
the new telemetry before artifact generation.

## Design

`aggregate_funnels()` will sum only the exact source-count buckets `0`, `1`,
`2`, and `3_plus` across input funnels. A missing or malformed bucket value
contributes zero. Valid values are non-negative integers; booleans are invalid.
Unknown keys are ignored.

The aggregate `confidence_clamped_count` will be derived from the four summed
buckets. It will never trust or sum a per-run declared total. This matches the
Ledger, analytics, and artifact-boundary contracts and prevents inconsistent
totals from propagating into the evaluation report.

## Scope

- Modify `neos/workflow/deep_analysis/funnel_sample.py` only for aggregation.
- Add focused regression coverage in
  `tests/workflow/deep_analysis/test_funnel_sample.py`.
- Re-run funnel runner tests to verify artifact compatibility.
- Do not change prompts, graders, thresholds, sampling, discovery, models, or
  execution budgets.
- Do not start the live 5+1 provider run until the deterministic aggregation
  tests and Ruff pass.

## Verification and Handoff

The regression test will include valid buckets, missing fields, malformed
known values, an unknown key, and deliberately inconsistent declared totals.
After implementation and local `dev` integration, the existing bounded script
will run the `mixed-v1` five `dev` cases and one selected `default` case. Its
artifact must retain the aggregate clamp buckets and derived total before the
results are compared with the prior baseline.

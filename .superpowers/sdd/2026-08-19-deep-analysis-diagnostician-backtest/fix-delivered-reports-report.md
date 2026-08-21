# Fix: `deep_analysis_diagnostician.load_sample` was reading the funnel summary table, not the delivered report

## The bug

`load_sample()` read `artifacts/deep-analysis-funnel/<ts>/report.md` and passed
that single blob into `build_summary(..., report_markdown=...)`. That file is
the funnel runner's own per-case summary table (~1.1KB, identical shape across
every sample) — not a delivered deep-analysis report. Every sample's
`delivered` block therefore reported `footnotes: 0`, `raw_markers: 0`,
`sources_section: false` for all samples, including #11–#16, which are exactly
the arc where the harness's citation behaviour was diagnosed and fixed
(delivered footnote median 2 → 8 at #16, per the roadmap).

## Read path used, and why

Used `DeepAnalysisAnalyticsService.report_bodies(run_ids)`
(`neos/workflow/deep_analysis/analytics.py`), not `Ledger.report_markdown()`.
Rationale: `load_sample` needs the body for *every run in a sample* (a sample
has multiple `dev_runs` + one `default_run`), and `report_bodies()` is the
batch form built for exactly this — one round trip for many runs, returning a
`{run_id: body}` dict that simply omits runs with no completed job or no body
in the payload (rather than mapping them to `None`/`""`). `Ledger.
report_markdown()` is scoped to a single run and would cost one round trip per
run per sample; it also isn't the batch form the roadmap's G4 note points a
grader at.

Both read from the `job_completed` event payload's `report_markdown` key
(never the NULL `report_path` column) — see `Ledger.report_markdown()`'s
docstring for why the column is a dead end.

## New `delivered` shape

`build_summary()` signature changed:

```
def build_summary(
    rows: Sequence[EventRow],
    *,
    run_ids: Sequence[str],
    report_bodies: dict[str, str],
    config_fingerprint: dict,
) -> dict:
```

`load_sample()` now returns `(rows, run_ids, report_bodies, config_fingerprint)`
instead of `(rows, report_markdown, config_fingerprint)`.

New `delivered` block (all scalar, so `summary_field_paths`'s existing
dict-only recursion still needs no changes):

```json
{
  "runs_total": 6,
  "runs_with_body": 6,
  "runs_missing_body": 0,
  "chars_median": 4154,
  "footnotes_median": 9,
  "raw_markers_median": 0,
  "sources_section_count": 6
}
```

- `runs_total` / `runs_with_body` / `runs_missing_body` — a run with no
  delivered body (failed/unfinished job, or a `job_completed` payload without
  `report_markdown`) is counted separately, never folded into the medians as
  an empty-string zero (requirement 3).
- `chars_median`, `footnotes_median`, `raw_markers_median` — computed only
  over runs that *have* a body, using the same median convention already used
  by `gate.uncited_ratio` in this file (`sorted(values)[len(values)//2]`,
  `None` when the list is empty). This is the project's own "배달 각주
  중앙값" vocabulary (roadmap, samples #16 entry).
- `sources_section_count` — count of runs whose body contains `## 출처`
  (was a single bool before; now a count across runs).

`_count_footnotes()` and `_median()` were factored out as module-level
helpers used by the new `_delivered_summary()`.

## Real sample #16 data (verified against the live DB, no LLM call)

Ran a throwaway script (not committed) calling `load_sample("16", entry,
session=session)` against sample #16's artifact (`20260811T152942Z`, 6 runs)
using `DATABASE_URL` from `.env`. All 6 runs had a delivered body:

```
run_ids: ['50fd36f1', '4af2ffd4', 'ca8fd65c', 'ea3357e8', '73c172a0', 'd7d602ca']
body lengths: 2295, 4040, 2530, 4154, 4315, 7500

delivered:
{
  "runs_total": 6,
  "runs_with_body": 6,
  "runs_missing_body": 0,
  "chars_median": 4154,
  "footnotes_median": 9,
  "raw_markers_median": 0,
  "sources_section_count": 6
}
```

`footnotes_median: 9` (all 6 runs non-zero) is in line with the roadmap's
"배달 각주 중앙값 2 → 8" finding for #16 — before the fix this field always
read `0`. The fix reaches real data.

## Signal map

`scripts/diagnostician_backtest/signal_map.yaml` referenced three now-renamed
paths and was updated:

- `delivered.footnotes` → `delivered.footnotes_median` (label `writer_prompt`)
- `delivered.raw_markers` → `delivered.raw_markers_median` (label
  `citation_render`)
- `delivered.sources_section` → `delivered.sources_section_count` (label
  `citation_render`)

No other path in the signal map or elsewhere in the repo referenced the old
`delivered.*` names.

`answer_key.yaml` was not touched (pre-registration, requirement 5).

## Prompt version

`neos/workflow/deep_analysis/prompts/diagnose_bottleneck.md` was not edited —
it only shows example evidence paths like `clamp.exhausted` /
`budget.by_stage`, never hardcodes `delivered.footnotes` etc., so its guidance
about citing paths ("경로 찾아 인용") stays accurate against the new schema
with no content change. No version bump needed; `EXPECTED_PROMPT_VERSIONS` in
`tests/workflow/deep_analysis/test_golden_gate.py` is unchanged
(`diagnose_bottleneck: 2`).

## Tests changed

`tests/workflow/deep_analysis/test_diagnostician_input.py` — rewrote to call
`build_summary` with the new `run_ids=`/`report_bodies=` kwargs, and replaced
the single "reads the delivered report" test with:

- `test_summary_reports_delivered_body_median_across_runs` — 3 runs, all with
  bodies, odd-length lists so the median is unambiguous.
- `test_summary_counts_runs_with_no_delivered_body_as_a_signal` — one run
  missing a body; asserts it's counted in `runs_missing_body`, not folded
  into the median as zero.
- `test_summary_delivered_is_all_none_and_zero_when_no_body_ever_arrives` —
  no bodies at all: medians are `None`, `sources_section_count` is `0`.

All other existing tests (`test_summary_counts_events_by_kind`, budget/stage,
zero-token-pass, schema-identity, no-sample-id-in-source) updated only to
pass the new kwargs; their assertions are unchanged.

No test hits the database or makes an LLM call — all use fixture
`report_bodies` dicts and in-memory `rows`.

## Full test output

```
HOME=/tmp/neos-test-home .venv/bin/pytest tests/workflow/deep_analysis -q
...
====================== 655 passed, 25 warnings in 12.02s =======================
```

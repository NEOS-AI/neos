# Claim Scope and Confidence Calibration Design

**Date:** 2026-07-21
**Status:** Approved

## Goal

Reduce the dominant `E_CONFIDENCE_INFLATED` and `E_OVERCLAIM` losses observed
in production-like deep-analysis sampling. Strengthen claim-generation and
repair prompts, enforce confidence caps at the worker parsing boundary, and
record only aggregate clamp telemetry. Do not change graders, thresholds,
agentic sampling, discovery, models, or token/time caps.

## Baseline

The `mixed-v1` baseline completed five `dev` runs and one representative
`default` run. The dev runs produced 49 graded events: 12 verified and 37
rejected. Of the 37 rejected events, 23 were `E_CONFIDENCE_INFLATED` and nine
were `E_OVERCLAIM`; together they represented 86.5% of rejection events.
Evidence-missing and source-dead rates were zero, and 43 of 49 quote scores
were exact. This supports claim scope and confidence calibration as the next
single policy-design priority.

## Architecture

The change uses two complementary controls:

1. The versioned worker prompt teaches the model to emit atomic, evidence-
   bounded claims and calculate confidence from evidence it actually attaches.
2. The worker parser independently clamps confidence after discarding evidence
   whose URL was not fetched. Only the clamped value enters `ProposedClaim`.

The deterministic grader remains a fail-closed backstop. It does not mutate
claims and retains its existing confidence rejection behavior for claims from
other producers or legacy data.

## Prompt Contract v2

`worker_brief.md` advances from version 1 to version 2. It retains the existing
JSON shape and adds these binding instructions:

- Each claim contains one independently verifiable proposition.
- A claim must preserve the evidence's subject, time range, population,
  conditions, quantitative qualifiers, and comparison scope.
- Separate claims are required when evidence supports only some parts of a
  compound statement.
- Association or observational evidence must not be promoted to a causal
  conclusion.
- Confidence is calculated after selecting the final evidence list, using the
  number of unique attached `source_url` values.
- The caps are zero sources `0.0`, one source `0.6`, two sources `0.8`, and
  three or more sources `0.95`. The three non-zero values are rendered from
  the configured `deep_analysis.confidence_cap`, which is also used by the
  parser and deterministic grader.
- When uncertain, narrow the claim or lower confidence rather than broadening
  the evidence interpretation.

The `E_OVERCLAIM` weaken-only prompt keeps the no-search behavior. It adds an
explicit weakening checklist: preserve supported dates, populations,
conditions, quantities, and association-versus-causation language; remove
unsupported comparisons or causal force; abandon a repair rather than invent
support. Its output remains content-compatible with the existing repair
parser.

## Parser Enforcement

The worker first resolves each proposed evidence item against
`fetched_by_url`, exactly as today. It then computes the distinct source count
from the retained `ProposedEvidence` list and applies:

```text
0 sources -> confidence <= 0.0
1 source  -> confidence <= 0.6
2 sources -> confidence <= 0.8
3+ sources -> confidence <= 0.95
```

The model-provided confidence is still bounded to `[0, 1]` before applying the
source cap. A clamp is recorded only when the bounded requested value exceeds
the source cap. The requested value is never stored in a model, event, log, or
artifact. Claims without retained evidence remain subject to the existing
`E_NO_EVIDENCE` rejection even though their normalized confidence becomes
zero.

One helper owns cap lookup and normalization so prompt parsing and tests do not
duplicate the table. The worker reads the same configured cap mapping used to
construct the deterministic grader; it does not import or depend on the grader.
The orchestrator renders those configured values into the prompt placeholders,
so environment-specific caps cannot diverge between model instructions and
parser enforcement.

## Aggregate Telemetry

`WorkerResult` adds two backward-compatible defaulted fields:

- `confidence_clamped_count: int = 0`
- `confidence_clamped_by_source_count: dict[str, int]`, with allowed keys
  `0`, `1`, `2`, and `3_plus`.

The worker increments these fields while parsing claims. `flush_partial()`
preserves the accumulated counters.

`Ledger.commit_pass()` adds the following safe aggregate fields to the existing
`pass_completed` payload:

```json
{
  "confidence_clamped_count": 2,
  "confidence_clamped_by_source_count": {
    "0": 1,
    "1": 1,
    "2": 0,
    "3_plus": 0
  }
}
```

No claim text, requested confidence, source URL, excerpt, blob, or repair text
is included. Invalid or unknown bucket keys from custom `WorkerResult`
producers are excluded at the ledger boundary, and counts must be non-negative
integers that are not booleans. The persisted total is derived from the four
sanitized buckets rather than trusting a possibly inconsistent custom total.

`DeepAnalysisAnalyticsService.claim_funnel` sums the total and four buckets
from valid `pass_completed` payloads. Malformed clamp telemetry is ignored
without invalidating existing pass metrics. Existing events without the new
fields contribute zero, preserving backward compatibility.

## Data Flow

```text
worker prompt v2
  -> model JSON
  -> retain only fetched evidence
  -> clamp confidence by distinct retained sources
  -> ProposedClaim(clamped confidence)
  -> deterministic and agentic graders
  -> Ledger.commit_pass aggregate clamp telemetry
  -> claim_funnel aggregate
```

## Error and Security Boundaries

- Non-numeric confidence continues to use the worker's existing parse failure
  behavior; this design does not silently invent a numeric value.
- Clamp telemetry cannot fail a research pass. Invalid custom telemetry is
  sanitized to safe zero/default aggregates at the ledger boundary.
- Cancellation and token-budget behavior are unchanged.
- Logs and events never contain requested confidence, claim text, source URLs,
  excerpts, fetched content, or provider responses because of this feature.
- Prompt version changes update the golden prompt-version gate, but golden
  provider cassettes and runtime response schemas remain unchanged.

## Verification

Tests cover:

- prompt version 2 and atomic/scope/causality/confidence instructions;
- confidence normalization for zero, one, two, and three-plus retained sources;
- clamp after unfetched evidence is removed and unique-source deduplication;
- no clamp when requested confidence is at or below the cap;
- accumulated and partial-result telemetry;
- weaken-only prompt scope and causality constraints with no search/fetch;
- ledger payload allowlisting and malformed custom telemetry;
- analytics aggregation, malformed payload tolerance, and legacy events;
- golden prompt-version gate and focused workflow regressions.

After implementation, the same `mixed-v1` five-`dev` plus one-`default`
evaluation can be run manually. The comparison must report clamp counts,
rejection-code distribution, and verified/rejected rates. A single rerun is
directional evidence only; it does not by itself establish causal improvement.

## Non-goals

- Changing confidence caps or quote thresholds.
- Changing agentic sampling or mandatory-grading rules.
- Changing discovery sources, fetch behavior, or model selection.
- Storing raw requested confidence for later analysis.
- Automatically splitting compound claims in application code.
- Automatically rerunning the live provider evaluation.

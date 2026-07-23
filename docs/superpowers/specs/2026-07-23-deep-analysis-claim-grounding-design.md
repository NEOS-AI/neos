# Deep Analysis Claim Scope and Quote Grounding Design

## Context

The repeated `mixed-v1` funnel samples show that confidence calibration is
working, while overclaim and quote mismatch remain the dominant avoidable
losses. The second complete post-calibration sample recorded 12 overclaim and
8 quote-mismatch rejections. Five quote mismatches and four overclaims came
from `fact-aspartame`, where answers commonly compare conclusions from several
institutions.

This change targets claim generation only. It keeps the grader, thresholds,
sampling, discovery, models, token caps, wall-clock caps, and repair execution
unchanged so a later sample can be compared with the existing baseline.

## Goal

Strengthen the worker output contract so each proposed claim has one
independently verifiable scope and each evidence excerpt is a contiguous,
verbatim quotation that directly supports that scope.

## Design

Update `neos/workflow/deep_analysis/prompts/worker_brief.md` from prompt version
2 to version 3. Add explicit rules requiring the worker to:

1. Express one institution, one conclusion, and one comparison axis per claim.
2. Split conclusions from different institutions into separate claims, even
   when the institutions address the same subject.
3. Use comparative language only when the same excerpt directly states both
   compared subjects and the comparison direction.
4. Copy each excerpt as one contiguous substring from the fetched text without
   joining distant fragments, adding ellipses, translating, or paraphrasing.
5. Before returning JSON, verify that every excerpt can be found verbatim in
   the fetched text associated with its `source_url`.
6. Split or narrow a partially supported compound claim and discard any
   unsupported remainder.

These rules extend the existing atomic-claim and confidence-cap contract.
They do not introduce new JSON fields or change worker parsing.

## Data Flow

The orchestrator renders the version 3 worker brief with the same values it
already supplies. The worker receives the same fetched evidence context and
returns the same JSON schema. Existing parsing constructs `ProposedClaim` and
`ProposedEvidence` unchanged, and the deterministic and agentic graders apply
their existing policies unchanged.

The only intended behavior change is the distribution of LLM-produced claim
text and excerpts before grading.

## Error Handling

No post-generation rewriting or silent evidence removal is added. If the model
still returns a non-verbatim excerpt or an over-broad claim, the existing
graders reject it with the existing reason codes. This preserves observable
failures and avoids converting quote mismatch into no-evidence failures.

Malformed JSON and unknown evidence URLs continue through the current worker
handling. The version 3 prompt does not relax any existing output constraint.

## Testing

Extend `tests/workflow/deep_analysis/test_prompt_loader.py` to verify that the
rendered worker brief includes:

- the one-institution, one-conclusion, one-comparison-axis rule;
- mandatory separation of conclusions from different institutions;
- the direct-support requirement for comparisons;
- the contiguous, verbatim excerpt restriction;
- the pre-submission lookup check against the matching `source_url`;
- split, narrow, or discard behavior for partially supported compound claims.

Use test-driven development: first update the prompt-contract test and confirm
that it fails against version 2, then update the prompt and confirm it passes.
Run the prompt and worker focused tests, followed by the full deep-analysis
test suite and Ruff.

## Acceptance Criteria

- `worker_brief.md` declares prompt version 3.
- All six grounding rules are visible in a rendered worker brief.
- The worker JSON schema and Python parsing interfaces are unchanged.
- No grader, threshold, sampling, discovery, model, token, wall-clock, or
  repair-path behavior changes.
- Focused and full deep-analysis regression tests pass.

## Non-Goals

- Deterministic splitting or rewriting of generated claims.
- Exact-quote filtering in Python.
- A new repair path for `E_QUOTE_MISMATCH`.
- Changes to `_weaken_only()`.
- A claim-funnel sample run as part of implementation; sampling is the
  follow-up evaluation after the code change is merged.

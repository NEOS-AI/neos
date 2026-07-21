# Deep-analysis NUL Normalization Design

## Goal

Prevent fetched HTML or PDF evidence containing a NUL character (`U+0000`)
from failing PostgreSQL blob persistence with
`CharacterNotInRepertoireError`.

## Observed Failure

The second post-calibration `mixed-v1` run produced artifact
`20260721T043212Z`. Four `dev` cases and the selected `default` case completed,
but `fact-aspartame` run `100e784a` failed during execution. Durable event
inspection identified the database exception class as
`asyncpg.exceptions.CharacterNotInRepertoireError`. The fetch path collapses
whitespace and applies NFC but does not remove NUL, while PostgreSQL `text`
cannot store NUL.

The incomplete artifact is diagnostic evidence only. Its aggregate funnel must
not be compared as a complete five-case sample.

## Design

Add one shared `normalize_evidence_text(value: str) -> str` helper in
`neos/workflow/deep_analysis/text_norm.py`. It will remove every NUL character,
collapse whitespace, trim the result, and normalize it to NFC.

Both HTML extraction and PDF extraction will call this helper before returning
text to `fetch_url()`. The sanitized canonical text will therefore be used for
all three downstream purposes:

1. content hashing and deduplication;
2. the worker evidence context sent to the model;
3. PostgreSQL blob persistence and quote matching.

This preserves the content-address contract: a source containing `A\x00B` and
one containing `AB` produce the same canonical body and hash. NUL removal does
not discard the rest of a source and does not introduce a Ledger-only mutation.

## Boundaries

- Remove only `U+0000`; do not broadly delete other Unicode control characters.
- Preserve existing whitespace collapse, NFC normalization, HTML script/style
  exclusion, PDF error wrapping, and empty-body hash behavior.
- Do not change prompts, graders, thresholds, sampling, discovery, models,
  token caps, or wall-clock caps.
- Do not log the offending fetched body or database error payload.

## Tests

- HTML extraction removes NUL while preserving adjacent text and NFC.
- PDF extraction removes NUL across page text and still closes the document.
- `fetch_url()` produces identical canonical text and content hashes for NUL
  and already-sanitized equivalent HTML.
- Existing fetch and PDF suites remain green; focused Ruff passes.

## Evaluation Handoff

After local `dev` integration, discard `20260721T043212Z` as an incomplete
comparison sample and run a fresh bounded `mixed-v1` 5+1 evaluation. Only an
artifact with all five `dev` runs and the selected `default` run completed may
be used for the second post-calibration comparison.

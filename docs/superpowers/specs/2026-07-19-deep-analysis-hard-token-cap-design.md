# Deep Analysis hard token cap design

## Context

The current `deep_analysis.global_token_cap` is checked against
`DAQuestion.spent_tokens` only at orchestration round boundaries. A parallel
round can therefore start several workers while under budget and commit all of
their usage after the cap has already been crossed. Measured development runs
with a 20,000-token cap consumed between 20,866 and 27,362 tokens.

The existing accounting also excludes decomposition, agentic claim grading,
conflict processing, hierarchical reduction, report assembly, and agentic
report grading. Treating the existing number as a cost ceiling is therefore
misleading even if worker scheduling is tightened.

## Decision

`global_token_cap` becomes a hard upper bound for all provider LLM tokens used
by one deep-analysis run. Every call made through
`neos.workflow.deep_analysis.llm` while an orchestration budget scope is active
must reserve its worst-case token cost before contacting a provider or replaying
a cassette response.

The bound covers:

- root and split decomposition;
- discovery tool-calling turns;
- worker analysis and repair calls;
- deterministic-pass agentic claim grading;
- conflict-resolution LLM calls;
- hierarchical node reduction;
- final report assembly and retries; and
- agentic report grading.

Network search, source fetching, deterministic grading, and non-LLM Python
processing do not consume this token budget.

## Run-scoped budget

A new `TokenBudget` owns the following run-scoped state:

- immutable `cap_tokens`;
- durable settled usage;
- durable outstanding reservations;
- an `asyncio.Lock` protecting reserve and settle transitions; and
- an optional async persistence callback supplied by the orchestrator.

The budget is installed with a `contextvars.ContextVar` for the duration of
`Orchestrator.run()`. Child tasks created by `asyncio.gather()` inherit that
context, while concurrently executing runs retain independent budget objects.
Calls made outside an active deep-analysis run remain unchanged.

## Conservative reservation

Before a provider call, the LLM adapter computes:

```text
reservation = conservative_input_bound(request) + effective_max_output
```

The input bound is the UTF-8 byte length of the canonical JSON request body plus
a fixed structural allowance per message and tool definition. This deliberately
overestimates common provider tokenizers: a serialized token cannot represent
less than one input byte, while the allowance covers provider-added message and
tool framing.

The adapter first reserves the input bound. If that cannot fit, it raises
`TokenBudgetExhausted` without invoking the provider. Otherwise it reduces
`max_tokens` to the smaller of the caller request and the remaining reservable
amount. A positive minimum output allocation is required; a call with no output
room is rejected before dispatch.

Reservations are atomic. Concurrent calls cannot collectively reserve more than
the remaining cap. Near exhaustion this naturally lowers effective parallelism:
calls that win reservations proceed and the others degrade without dispatch.

On success, the adapter settles the reservation using
`response.input_tokens + response.output_tokens` and releases the unused
portion. The actual value must not exceed the reservation. Such a result would
invalidate the conservative-bound contract and raises
`TokenBudgetContractError`; it is never silently clamped.

An error before dispatch releases the reservation only after a durable release
record is written. Once provider dispatch begins, an exception or task
cancellation leaves the reservation outstanding because external usage is
unknown. Recovery and the live budget both treat that amount as fully consumed.
Cassette replay follows the same reservation and settlement path using the
recorded response usage, without changing the cassette key or payload format.

## Durable reserve and settle protocol

The orchestrator provides a persistence callback that writes budget events to
the deep-analysis event ledger and checkpoints them.

Each provider attempt has a unique `reservation_id` and records:

1. `token_budget_reserved` before dispatch, containing the reservation amount,
   stage/model metadata, and reservation ID;
2. exactly one terminal event:
   - `token_budget_settled` with actual usage, or
   - `token_budget_released` only when dispatch did not begin.

A dispatched call that ends without usage data intentionally has no terminal
event and remains fully charged.

The reserve event is checkpointed before the provider request begins. The
terminal event is checkpointed before the released capacity becomes available
to another call. This ordering prevents a crash from exposing budget that may
already have been spent externally.

`Ledger` gains a run-budget recovery query. On resume it reconstructs:

- settled reservations from their actual usage;
- released reservations as zero usage; and
- reservations without a terminal event as fully consumed.

Failing closed for an interrupted reservation can reduce useful remaining
budget, but it prevents the resumed run from exceeding the configured cap.

The existing per-question `spent_tokens` values remain as worker analytics.
They are no longer authoritative for global stop decisions.

## Orchestrator integration

`Orchestrator.run()` recovers durable budget state before performing any new LLM
work and enters the run's budget scope. The loop stops when the budget cannot
fund another call, rather than waiting for `Ledger.total_spent()` to reach the
cap.

`Budgeter` continues to rank questions and enforce score/depth policy. Its
global stop contract consumes the shared budget state instead of the worker-only
ledger total. Breadth selection remains value-driven; actual concurrency is
bounded by successful reservations in the LLM adapter.

Budget events include a stage label set by the calling component so operators
can distinguish decomposition, discovery, worker analysis, grading, reduction,
assembly, and report grading usage.

## Exhaustion behavior

Budget exhaustion is a normal terminal condition, not a failed run.

- A worker that exhausts its budget flushes accumulated blobs and claims as a
  `partial` result.
- An agentic claim grader falls back to its deterministic verdict.
- Conflict reinvestigation stops scheduling additional investigation.
- An agentic report grader retains the deterministic report verdict.
- If an LLM reduction or assembly call cannot run, the synthesizer produces a
  deterministic minimal report from verified claims, question text, existing
  node summaries, and caveats.
- The orchestrator records and emits one `token_budget_exhausted` event with the
  cap, consumed/reserved totals, and the stage that first failed to reserve.
- The run completes with the strongest result available at exhaustion.

The deterministic fallback must retain the normal report headings, verified
claim citations where available, and an explicit limitation explaining that the
LLM token cap was exhausted.

## Retry semantics

JSON parse retries are separate provider calls and therefore require separate
reservations. A retry that cannot reserve budget is skipped and surfaces budget
exhaustion rather than a JSON parse error. Report assembly retries, agentic
two-judgment checks, and discovery turns follow the same rule.

## Tests

### Budget unit tests

- concurrent reservations never exceed the cap;
- settlement releases unused reservation capacity;
- insufficient input or output room rejects before dispatch;
- pre-dispatch failure persists a release before capacity returns;
- provider error and cancellation after dispatch leave a fully consumed
  outstanding reservation;
- actual usage greater than reservation raises a contract error;
- recovery counts settled actual usage, released usage as zero, and orphaned
  reservations at their full reserved amount.

### LLM adapter tests

- prompt and tool-calling requests both reserve conservative input plus output;
- provider `max_tokens` is reduced to available output capacity;
- exhausted calls never invoke the provider;
- successful calls settle recorded usage;
- cassette replay consumes the recorded usage without changing cassette keys;
- calls outside a budget scope preserve current behavior.

### Component and orchestration tests

- parallel worker calls remain at or below the global cap;
- decomposition, grading, reduction, assembly, and report grading all share the
  same cap;
- worker exhaustion becomes `partial`, not systemic failure;
- grader exhaustion uses deterministic results;
- synthesis exhaustion returns the deterministic minimal report;
- only one exhaustion event is emitted per run;
- resume treats an orphaned reservation as fully spent and does not re-spend it;
- existing golden cassette tests retain their payload compatibility.

## Observability

Completion and failure logs expose:

- `token_budget_cap`;
- `token_budget_consumed`;
- `token_budget_reserved` still outstanding; and
- whether graceful exhaustion occurred.

This accounting is run-scoped and distinct from the existing per-question
worker token totals.

## Non-goals

- Limiting non-LLM search or HTTP traffic by token budget.
- Converting the token ceiling into a currency ceiling.
- Sharing one cap across multiple independent deep-analysis runs.
- Silently truncating provider-reported usage to make metrics fit the cap.
- Changing model selection, quality thresholds, or question ranking policy.

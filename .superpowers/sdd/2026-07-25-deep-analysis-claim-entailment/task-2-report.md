# Task 2 Report — Versioned Prompt and Worker Integration

## Implementation

- Added `neos/workflow/deep_analysis/prompts/claim_entailment.md` with a
  version-1 Korean claim/evidence entailment contract.
- Added `Worker._refine_claims` in
  `neos/workflow/deep_analysis/worker.py`. It performs one compact batched
  `call_llm` request after generated claims are resolved and before the worker
  result is assembled, with `stage="claim_entailment"` and `max_tokens=1200`.
- The worker counts successful entailment usage before JSON parsing, keeps the
  batch unchanged for provider, JSON, and structural-validation failures, and
  lets `TokenBudgetExhausted` reach the existing partial-result boundary.
- Added the versioned-prompt contract and focused integration coverage in
  `tests/workflow/deep_analysis/test_prompt_loader.py` and
  `tests/workflow/deep_analysis/test_worker_entailment.py`; updated the
  pre-existing worker usage/call-count expectation in
  `tests/workflow/deep_analysis/test_worker.py`.

## Decisions

Task 1's committed public response schema is authoritative:
`verdict` plus `narrowed_claim`, rather than the stale `action` plus
`new_text` wording in the Task 2 brief/design. The Task 1 module was not
modified. The prompt and tests therefore use its strict, atomic contract.

The hard-cap test delegates the generation-stage call to the real `call_llm`
and raises only for `claim_entailment`; this tests the intended second-call
boundary while preserving the buffered generated claims that the partial path
must return.

## TDD Evidence

RED command (the requested relative `.venv` path is absent in this linked
worktree, so the same repository environment was used by absolute path):

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_prompt_loader.py::test_claim_entailment_prompt_contract \
  tests/workflow/deep_analysis/test_worker_entailment.py \
  -q -o log_cli=false --disable-warnings
```

Result before implementation: 6 failed, 2 passed. Failures were the absent
prompt, missing worker refinement/usage accounting, and absent `call_llm`
integration seam.

GREEN verification:

```bash
HOME=/tmp/neos-test-home /Users/ywsung/Desktop/neos/.venv/bin/pytest \
  tests/workflow/deep_analysis/test_claim_entailment.py \
  tests/workflow/deep_analysis/test_prompt_loader.py \
  tests/workflow/deep_analysis/test_worker.py \
  tests/workflow/deep_analysis/test_worker_entailment.py \
  tests/workflow/deep_analysis/test_worker_repair.py \
  tests/workflow/deep_analysis/test_worker_discovery.py \
  -q -o log_cli=false --disable-warnings
```

Result: 51 passed, 1 warning in 0.24s.

```bash
/Users/ywsung/Desktop/neos/.venv/bin/ruff check \
  neos/workflow/deep_analysis/claim_entailment.py \
  neos/workflow/deep_analysis/worker.py \
  tests/workflow/deep_analysis/test_claim_entailment.py \
  tests/workflow/deep_analysis/test_worker.py \
  tests/workflow/deep_analysis/test_worker_entailment.py \
  tests/workflow/deep_analysis/test_prompt_loader.py
```

Result: `All checks passed!` (`git diff --check` also passed).

## Commit

Implementation commit: `829360b97ce7463222dc91c918a612888321a7fb`
(`feat(deep-analysis): refine claims against evidence`).

## Concerns

No functional blocker found. The worktree lacks its own `.venv`; test commands
used the repository-root virtual environment. Golden manifest/cassette data
were intentionally untouched, as required for this task boundary.

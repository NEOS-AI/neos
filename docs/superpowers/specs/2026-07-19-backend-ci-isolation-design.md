# Backend CI and Test Isolation Design

**Date:** 2026-07-19

**Status:** Approved

## Purpose

Close the remaining test-isolation issues in `docs/TODO_260729.md` sections 9, 10, and 11, and turn their regression checks into a GitHub Actions backend CI workflow. The workflow must make collection, workflow, and API failures distinguishable while using the same commands developers can run locally.

This work follows the previously implemented deep-analysis systemic-failure and inline-timeout bounds on `fix/deep-analysis-failure-bounds`.

## Scope

The change includes:

- pytest collection isolation for same-basename workflow test modules;
- deterministic test configuration for clean environments;
- run-scoped deep-analysis analytics queries for isolated tests;
- full workflow and API suite regression checks;
- a GitHub Actions workflow for pull requests and pushes to `dev`.

The change excludes frontend tests, end-to-end browser tests, deployment, and speculative production changes for failures that cannot be reproduced.

## Architecture

Create `.github/workflows/backend-ci.yml` with three independent jobs.

### `quality`

This job installs the locked Python environment, runs Ruff, and collects all workflow and API tests. Its purpose is to report static-analysis and collection failures separately from runtime failures.

### `workflow-tests`

This job starts PostgreSQL and runs `tests/workflow/`. It covers NEOS loop behavior, deep-analysis analytics, and workflow-level regressions.

### `api-tests`

This job starts PostgreSQL and runs all of `tests/api/` in one pytest process. Running the suite together is the regression contract for shared application state, import order, database integration, and environment completeness.

All jobs use read-only repository permissions. Workflow runs for the same branch use concurrency cancellation so that stale commits do not consume CI capacity.

## Section 9: Pytest Module Collection Isolation

Configure pytest with `--import-mode=importlib`. The repository contains same-basename modules such as:

- `tests/workflow/harness/test_policy.py` and `tests/workflow/autonomy/test_policy.py`;
- `tests/workflow/mission/test_executor.py` and `tests/workflow/hyper_deep/test_executor.py`.

Importlib mode lets pytest load these files with independent module identities without requiring every test directory to become a Python package. This also protects future same-basename tests. The `quality` job enforces the contract by collecting `tests/workflow` and `tests/api` together.

## Section 10: API Order and Environment Isolation

The query-authorization order failure described in the TODO did not reproduce in the current full API suite. Production application construction or singleton behavior will therefore not be changed without a failing regression case.

The API isolation contract is instead:

- run the complete API suite in one pytest process;
- provide deterministic test defaults before application imports;
- set the same required values explicitly in GitHub Actions;
- add a minimal order-specific regression only if the problem becomes reproducible.

A clean checkout currently exposes a concrete missing configuration: coding WebSocket authentication tests need a non-null JWT secret. Test setup will provide a fixed, non-secret `JWT_SECRET_KEY` default. CI will also set `DATABASE_URL`, `JWT_SECRET_KEY`, a placeholder `GOOGLE_API_KEY`, and `DEBUG=false`. These values are test fixtures, not production credentials.

## Section 11: Analytics Isolation

Add an optional `run_id` filter to the deep-analysis analytics service.

- With no `run_id`, the service retains its existing production behavior and aggregates all qualifying runs.
- With `run_id`, every analytics aggregate is restricted to events belonging to that run.
- Analytics tests pass the unique run they create and assert only that run's signals.

The design does not delete the append-only deep-analysis event table between tests. Global deletion would weaken audit semantics and become unsafe under parallel test execution. Query scoping gives each test an explicit ownership boundary while preserving production-wide aggregation.

## Data Flow

For analytics, the caller supplies an optional run identifier to the service. The service builds its event query using the existing time boundary and, when present, the run boundary. All derived counters and rates consume the same filtered event set, preventing partial scoping where one metric could still see unrelated data.

For CI, each job independently checks out the repository, installs dependencies from `uv.lock`, applies deterministic environment values, and runs its assigned command. Runtime jobs wait for a healthy PostgreSQL service before pytest starts.

## Failure Handling and Diagnostics

The workflow does not use `continue-on-error` or automatic test retries.

- `quality` failure means lint or test collection failed.
- `workflow-tests` failure means workflow or deep-analysis behavior regressed.
- `api-tests` failure means API state, configuration, or database integration regressed.

If test collection or initialization attempts an external HTTP request, the test boundary must block or mock it rather than making CI dependent on public network availability.

## GitHub Actions Policy

The workflow runs on:

- pull requests;
- pushes to `dev`.

It uses Python 3.12, installs dependencies with `uv sync --frozen`, and pins official actions to supported major versions verified at implementation time. PostgreSQL uses a health check. Permissions are limited to `contents: read`, and concurrency cancels older runs for the same workflow and ref.

## Verification

The implementation is complete when all of the following hold:

1. `pytest --collect-only tests/workflow tests/api` succeeds and includes every known same-basename test module.
2. `tests/workflow/` passes as a complete suite.
3. `tests/api/` passes as a complete suite in one process.
4. Analytics tests pass alone, repeatedly, and within the full workflow suite when unrelated committed events already exist.
5. Ruff passes on the configured backend scope.
6. The GitHub Actions YAML has valid structure and its commands match the locally verified commands.
7. Previously implemented systemic-worker-failure and inline-timeout regressions remain green.

## Non-goals and Follow-up Boundary

This design does not claim that the historical query-authorization failure was fixed; it establishes a suite-level contract capable of detecting its return. If CI reveals a reproducible import-order failure, that failure must first be reduced to a deterministic regression test and then handled as a separate targeted production fix.

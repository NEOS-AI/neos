# Backend CI and Test Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make backend workflow and API tests deterministic in clean environments and enforce those contracts in a three-job GitHub Actions workflow.

**Architecture:** Pytest uses importlib module loading to avoid same-basename collisions, test bootstrap supplies deterministic non-secret defaults, and analytics accepts an optional `run_id` that scopes every aggregate without changing global production behavior. GitHub Actions separates lint/collection, workflow tests, and API tests so failures remain attributable.

**Tech Stack:** Python 3.12, pytest 9, pytest-asyncio, SQLAlchemy 2, PostgreSQL 16 with pgvector, Ruff 0.14.13, uv, GitHub Actions

## Global Constraints

- Execute tasks strictly in the order written.
- Use test-driven development for every behavioral change.
- Preserve global analytics aggregation when `run_id` is omitted.
- Do not delete the append-only `deep_analysis_events` table for test isolation.
- Do not change production application construction for the unreproduced query-authorization order failure.
- CI runs on pull requests and pushes to `dev` only.
- CI permissions are `contents: read`; stale runs for the same ref are cancelled.
- Frontend, browser E2E, deployment, and unrelated repository-wide lint cleanup are out of scope.

---

## File Map

- `pytest.ini`: owns pytest's repository-wide import strategy.
- `tests/conftest.py`: owns deterministic test-process environment defaults before application modules import settings.
- `neos/workflow/deep_analysis/analytics.py`: owns global and optional run-scoped analytics queries.
- `tests/workflow/deep_analysis/test_deep_analysis_analytics.py`: proves run isolation, time filtering, malformed payload handling, and global-default compatibility.
- `pyproject.toml` and `uv.lock`: make the root CI lint tool reproducible.
- `.github/workflows/backend-ci.yml`: owns backend CI triggers, permissions, services, environment, and job boundaries.

### Task 1: Isolate Same-Basename Pytest Modules

**Files:**
- Modify: `pytest.ini`
- Test: `tests/workflow/autonomy/test_policy.py`
- Test: `tests/workflow/harness/test_policy.py`
- Test: `tests/workflow/mission/test_executor.py`
- Test: `tests/workflow/hyper_deep/test_executor.py`

**Interfaces:**
- Consumes: pytest's `--import-mode=importlib` command-line option.
- Produces: repository-wide collection in which test file basenames do not define a shared top-level module identity.

- [ ] **Step 1: Reproduce the collection collision**

Run:

```bash
.venv/bin/pytest --collect-only \
  tests/workflow/autonomy/test_policy.py \
  tests/workflow/harness/test_policy.py \
  tests/workflow/mission/test_executor.py \
  tests/workflow/hyper_deep/test_executor.py -q
```

Expected: FAIL during collection with an import-file-mismatch error for `test_policy.py` or `test_executor.py`.

- [ ] **Step 2: Configure importlib collection**

Add this line beneath `--disable-warnings` in `pytest.ini`:

```ini
    --import-mode=importlib
```

- [ ] **Step 3: Verify all colliding modules collect**

Run the Step 1 command again.

Expected: PASS; pytest reports tests collected from all four paths and no import-file-mismatch error.

- [ ] **Step 4: Verify combined backend collection**

Run:

```bash
.venv/bin/pytest --collect-only tests/workflow tests/api -q
```

Expected: PASS with zero collection errors.

- [ ] **Step 5: Commit the collection boundary**

```bash
git add pytest.ini
git commit -m "test: isolate pytest module collection"
```

### Task 2: Make Test Authentication Configuration Self-Contained

**Files:**
- Modify: `tests/conftest.py:1-8`
- Test: `tests/api/handlers/test_coding_ws_handlers.py`

**Interfaces:**
- Consumes: process environment before `neos.config.settings` is imported.
- Produces: `JWT_SECRET_KEY=neos-test-only-secret-key-2026-07-19` only when the caller has not supplied a value.

- [ ] **Step 1: Reproduce the clean-environment JWT failure**

Run:

```bash
env -u JWT_SECRET_KEY .venv/bin/pytest \
  tests/api/handlers/test_coding_ws_handlers.py -q
```

Expected: FAIL in `create_access_token` because the signing key is `None`.

- [ ] **Step 2: Add the deterministic test default before third-party imports**

Change the top of `tests/conftest.py` to:

```python
"""Pytest configuration and fixtures."""

import os

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "neos-test-only-secret-key-2026-07-19",
)

import asyncio
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
```

Keep the rest of the file unchanged. `setdefault` is required so explicit developer or CI configuration remains authoritative.

- [ ] **Step 3: Verify clean-environment authentication tests**

Run the Step 1 command again.

Expected: PASS for all coding WebSocket handler tests.

- [ ] **Step 4: Verify the API suite as one process**

Run:

```bash
env -u JWT_SECRET_KEY .venv/bin/pytest tests/api -q
```

Expected: PASS, including query-authorization and coding WebSocket tests in the same process.

- [ ] **Step 5: Commit deterministic test setup**

```bash
git add tests/conftest.py
git commit -m "test: provide deterministic JWT configuration"
```

### Task 3: Scope Deep-Analysis Analytics by Run

**Files:**
- Modify: `neos/workflow/deep_analysis/analytics.py`
- Modify: `tests/workflow/deep_analysis/test_deep_analysis_analytics.py`

**Interfaces:**
- Consumes: `signals(*, since: datetime | None = None, run_id: str | None = None)` and `summary(*, since: datetime | None = None, run_id: str | None = None)`.
- Produces: every total and payload-derived metric scoped by both optional filters; omitting `run_id` retains global aggregation.

- [ ] **Step 1: Write the failing cross-run isolation regression**

Add this test after `_ev_at`:

```python
@pytest.mark.asyncio
async def test_signals_run_id_excludes_other_runs():
    async with await db_manager.get_session() as s:
        selected_run = await create_run(s, "selected", "dev")
        other_run = await create_run(s, "other", "dev")
        await _ev(s, selected_run, "claim_verified")
        await _ev(s, other_run, "claim_rejected", '{"code":"E_OVERCLAIM"}')

        sig = await DeepAnalysisAnalyticsService(s).signals(run_id=selected_run)

        assert sig["totals"] == {"claim_verified": 1}
        assert sig["reject_rate_by_code"] == {}
        await s.rollback()
```

- [ ] **Step 2: Run the regression to verify the interface is absent**

Run:

```bash
.venv/bin/pytest \
  tests/workflow/deep_analysis/test_deep_analysis_analytics.py::test_signals_run_id_excludes_other_runs -q
```

Expected: FAIL with `TypeError: signals() got an unexpected keyword argument 'run_id'`.

- [ ] **Step 3: Apply both optional filters to totals and payload rows**

In `analytics.py`, replace the global-only module description with wording that says aggregation is global by default and optionally run-scoped. Import `Select`:

```python
from sqlalchemy import Select, func, select
```

Add a shared query helper and update the private query signatures:

```python
    @staticmethod
    def _scope(
        stmt: Select,
        *,
        since: datetime | None,
        run_id: str | None,
    ) -> Select:
        if since is not None:
            stmt = stmt.where(DAEvent.ts >= to_naive_utc(since))
        if run_id is not None:
            stmt = stmt.where(DAEvent.run_id == run_id)
        return stmt

    async def _totals(
        self,
        since: datetime | None,
        run_id: str | None,
    ) -> dict[str, int]:
        stmt = select(DAEvent.kind, func.count()).group_by(DAEvent.kind)
        result = await self.db.execute(
            self._scope(stmt, since=since, run_id=run_id)
        )
        return {kind: int(count) for kind, count in result.all()}

    async def _payload_rows(
        self,
        since: datetime | None,
        run_id: str | None,
    ) -> list[tuple[str, str]]:
        stmt = select(DAEvent.kind, DAEvent.payload).where(
            DAEvent.kind.in_(_PAYLOAD_KINDS)
        )
        result = await self.db.execute(
            self._scope(stmt, since=since, run_id=run_id)
        )
        return [(kind, payload) for kind, payload in result.all()]
```

Update the public methods and their calls:

```python
    async def signals(
        self,
        *,
        since: datetime | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        totals = await self._totals(since, run_id)
```

Within the existing payload loop, replace only the iterator expression:

```python
        for kind, payload in await self._payload_rows(since, run_id):
```

Replace `summary` completely with:

```python

    async def summary(
        self,
        *,
        since: datetime | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "signals": await self.signals(since=since, run_id=run_id),
            "since": since,
            "generated_at": datetime.now(timezone.utc),
        }
```

- [ ] **Step 4: Verify the cross-run regression passes**

Run the Step 2 command again.

Expected: PASS with exactly one `claim_verified` event in totals.

- [ ] **Step 5: Make every analytics fixture own its query boundary**

In each existing test that calls `signals()`, pass the run created by that test:

```python
sig = await svc.signals(run_id=run_id)
```

For the empty-log test, create a run without events and query it:

```python
run_id = await create_run(s, "empty", "dev")
sig = await svc.signals(run_id=run_id)
```

For the summary test, use:

```python
result = await svc.summary(since=since, run_id=run_id)
assert result["signals"]["totals"] == {"claim_verified": 1}
```

Remove the far-future workaround and the comment claiming the tests aggregate globally. Keep the `since` regression and pass both `since=cutoff` and `run_id=run_id` so the two filters are proven to compose.

- [ ] **Step 6: Prove the production default remains global**

Add this test after the run-isolation regression:

```python
@pytest.mark.asyncio
async def test_signals_without_run_id_remains_global():
    async with await db_manager.get_session() as s:
        first_run = await create_run(s, "first-global", "dev")
        second_run = await create_run(s, "second-global", "dev")
        future = datetime.now(timezone.utc) + timedelta(days=3650)
        await _ev_at(s, first_run, "claim_verified", future)
        await _ev_at(s, second_run, "claim_verified", future)

        sig = await DeepAnalysisAnalyticsService(s).signals(
            since=future - timedelta(seconds=1)
        )

        assert sig["totals"]["claim_verified"] == 2
        await s.rollback()
```

The future timestamp prevents older committed events from affecting this global-default assertion.

- [ ] **Step 7: Run analytics isolation in three contexts**

Run:

```bash
.venv/bin/pytest tests/workflow/deep_analysis/test_deep_analysis_analytics.py -q
.venv/bin/pytest tests/workflow/deep_analysis/test_deep_analysis_analytics.py -q
.venv/bin/pytest tests/workflow/deep_analysis -q
```

Expected: all three commands PASS with identical analytics results; the repeated module run is not affected by events committed by earlier processes.

- [ ] **Step 8: Commit run-scoped analytics**

```bash
git add neos/workflow/deep_analysis/analytics.py \
  tests/workflow/deep_analysis/test_deep_analysis_analytics.py
git commit -m "fix: isolate deep analysis analytics by run"
```

### Task 4: Add Reproducible Backend GitHub Actions CI

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `.github/workflows/backend-ci.yml`

**Interfaces:**
- Consumes: Python 3.12, `uv.lock`, PostgreSQL at `localhost:5432`, and the pytest contracts from Tasks 1-3.
- Produces: `quality`, `workflow-tests`, and `api-tests` required-check candidates on pull requests and `dev` pushes.

- [ ] **Step 1: Demonstrate that the root environment does not install Ruff**

Run:

```bash
.venv/bin/python -m ruff --version
```

Expected: FAIL with `No module named ruff`.

- [ ] **Step 2: Declare the locked root development tool**

Add to `pyproject.toml` after `[project.optional-dependencies]` entries and before `[tool.setuptools.packages.find]`:

```toml
[dependency-groups]
dev = [
    "ruff==0.14.13",
]
```

Run:

```bash
uv lock
uv sync --frozen --group dev
```

Expected: both commands exit 0 and `.venv/bin/ruff --version` reports `ruff 0.14.13`.

- [ ] **Step 3: Verify the exact quality commands before encoding them**

Run:

```bash
uv run --frozen ruff check \
  neos/workflow/deep_analysis/analytics.py \
  tests/workflow/deep_analysis/test_deep_analysis_analytics.py \
  tests/conftest.py
uv run --frozen pytest --collect-only tests/workflow tests/api -q
```

Expected: both commands PASS. Fix only lint findings in the three named files; do not expand into repository-wide lint cleanup.

- [ ] **Step 4: Create the GitHub Actions workflow**

Create `.github/workflows/backend-ci.yml` with:

```yaml
name: Backend CI

on:
  pull_request:
  push:
    branches:
      - dev

permissions:
  contents: read

concurrency:
  group: backend-ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

env:
  DATABASE_URL: postgresql+asyncpg://neos:neos_password@localhost:5432/neos_db
  JWT_SECRET_KEY: neos-ci-only-secret-key-2026-07-19
  GOOGLE_API_KEY: neos-ci-placeholder
  DEBUG: "false"

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
        with:
          enable-cache: true
      - run: uv sync --frozen --group dev
      - name: Ruff
        run: >-
          uv run --frozen ruff check
          neos/workflow/deep_analysis/analytics.py
          tests/workflow/deep_analysis/test_deep_analysis_analytics.py
          tests/conftest.py
      - name: Collect backend tests
        run: uv run --frozen pytest --collect-only tests/workflow tests/api -q

  workflow-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: neos
          POSTGRES_PASSWORD: neos_password
          POSTGRES_DB: neos_db
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U neos -d neos_db"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
        with:
          enable-cache: true
      - run: uv sync --frozen --group dev
      - run: uv run --frozen pytest tests/workflow -q

  api-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: neos
          POSTGRES_PASSWORD: neos_password
          POSTGRES_DB: neos_db
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U neos -d neos_db"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b # v8.1.0
        with:
          enable-cache: true
      - run: uv sync --frozen --group dev
      - run: uv run --frozen pytest tests/api -q
```

The action versions are based on the official documentation checked on 2026-07-19: `actions/checkout@v6`, `actions/setup-python@v6`, and the immutable `setup-uv` v8.1.0 commit.

- [ ] **Step 5: Validate workflow structure locally**

Run:

```bash
uv run --frozen python -c \
  'import pathlib, yaml; data=yaml.safe_load(pathlib.Path(".github/workflows/backend-ci.yml").read_text()); assert data["permissions"] == {"contents": "read"}; assert set(data["jobs"]) == {"quality", "workflow-tests", "api-tests"}'
git diff --check
```

Expected: both commands exit 0. The parser assertion proves the three job IDs and least-privilege permission are present.

- [ ] **Step 6: Run the complete local CI contract**

Run sequentially:

```bash
uv run --frozen ruff check \
  neos/workflow/deep_analysis/analytics.py \
  tests/workflow/deep_analysis/test_deep_analysis_analytics.py \
  tests/conftest.py
uv run --frozen pytest --collect-only tests/workflow tests/api -q
uv run --frozen pytest tests/workflow -q
uv run --frozen pytest tests/api -q
```

Expected: every command exits 0. If collection performs an external HTTP request, identify the importer and replace that boundary with a deterministic test mock before continuing; do not add retry or `continue-on-error`.

- [ ] **Step 7: Commit CI**

```bash
git add pyproject.toml uv.lock .github/workflows/backend-ci.yml
git commit -m "ci: add isolated backend test workflow"
```

### Task 5: Final Regression and TODO Reconciliation

**Files:**
- Modify: `docs/TODO_260729.md`

**Interfaces:**
- Consumes: all commits from Tasks 1-4.
- Produces: evidence that §§9-11 and the earlier deep-analysis failure-bound work pass together.

- [ ] **Step 1: Run focused deep-analysis failure-bound regressions**

Run:

```bash
uv run --frozen pytest \
  tests/workflow/deep_analysis/test_deep_analysis_service_m2.py \
  tests/workflow/deep_analysis/test_deep_analysis_jobs.py \
  tests/api/handlers/test_deep_analysis_handlers.py -q
```

Expected: PASS, including systemic termination, inline timeout, resume, and API persistence boundaries.

- [ ] **Step 2: Re-run backend suites from a clean process boundary**

Run:

```bash
uv run --frozen pytest tests/workflow -q
uv run --frozen pytest tests/api -q
```

Expected: both suites PASS with no collection errors and no analytics total contamination.

- [ ] **Step 3: Reconcile the TODO statuses with verified evidence**

Append the following resolution paragraph to §9:

```markdown
**해결 (2026-07-19):** pytest에 `--import-mode=importlib`을 적용했다. 이제
`pytest --collect-only tests/workflow tests/api -q`와 `pytest tests/workflow -q`가
basename 충돌 없이 한 번에 통과하며, GitHub Actions `quality` job이 수집 회귀를 감지한다.
```

Append the following status paragraph to §10:

```markdown
**현재 상태 (2026-07-19):** 기존 query authorization 순서 실패는 전체 API suite에서
재현되지 않았다. 추측성 production 변경은 하지 않았다. 대신 테스트 bootstrap에 결정론적
JWT 설정을 추가하고 GitHub Actions가 `pytest tests/api -q`를 단일 프로세스로 실행한다.
따라서 이 항목은 **재발 감지 계약 구축 완료**이며, production singleton 수정 완료를 뜻하지 않는다.
```

Append the following resolution paragraph to §11:

```markdown
**해결 (2026-07-19):** analytics 조회에 선택적 `run_id` 경계를 추가했다. 운영 호출은
기존 전역 집계를 유지하고, 테스트는 자신이 만든 run만 조회한다. 단독·반복·전체 workflow
suite 실행에서 동일한 결과를 검증한다.
```

- [ ] **Step 4: Check the final diff and commit documentation**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors and only `docs/TODO_260729.md` is uncommitted. Commit it:

```bash
git add docs/TODO_260729.md
git commit -m "docs: reconcile backend isolation TODOs"
```

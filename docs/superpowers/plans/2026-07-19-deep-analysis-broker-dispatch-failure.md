# Deep Analysis Broker Dispatch Failure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Celery broker dispatch failures explicit, durable, and recoverable without silently falling back to inline execution.

**Architecture:** Add a focused durable dispatch-failure recorder beside the existing job lifecycle functions, then make the integration-layer dispatcher async so it can commit compensation before raising a bounded custom exception. FastAPI maps that exception to 503, while the graph node keeps its existing user-facing failure response and skips its started event.

**Tech Stack:** Python 3.12, asyncio, Celery, FastAPI, SQLAlchemy async, PostgreSQL, pytest, Ruff

## Global Constraints

- Celery-enabled broker failure must never fall back to inline execution.
- A failed dispatch must set `DARun.status="failed"` and commit `job_failed` before the caller observes failure.
- The durable payload code is exactly `E_BROKER_DISPATCH`.
- Do not persist the question, broker URL, credentials, Celery kwargs, or raw broker exception.
- Keep the current inline path unchanged when Celery is disabled.
- Do not add a migration, new run status, retry loop, outbox, reconciliation task, or health probe.
- A persistence failure must not replace the original dispatch failure.

---

### Task 1: Durable Dispatch-Failure Lifecycle Primitive

**Files:**
- Modify: `neos/workflow/deep_analysis/jobs.py`
- Modify: `tests/workflow/deep_analysis/test_jobs.py`

**Interfaces:**
- Consumes: existing `_record_failure(session_factory, run_id, error)` behavior
- Produces: `record_dispatch_failure(session_factory, run_id) -> None`
- Produces event: `job_failed` with `{"code": "E_BROKER_DISPATCH", "error": "Celery broker dispatch failed"}`

- [ ] **Step 1: Write a failing durable compensation test**

Add a DB-backed test using the existing session fakes/helpers in `test_jobs.py`:

```python
@pytest.mark.asyncio
async def test_record_dispatch_failure_marks_run_failed_with_bounded_event():
    run = SimpleNamespace(status="running", report_path=None)
    fail_session = FakeSession(run=run)
    session_factory = make_factory([fail_session])

    await jobs.record_dispatch_failure(session_factory, "run00001")

    assert run.status == "failed"
    assert kinds(fail_session) == [jobs.JOB_FAILED]
    assert json.loads(fail_session.added[-1].payload) == {
        "code": "E_BROKER_DISPATCH",
        "error": "Celery broker dispatch failed",
    }
    assert fail_session.commits == 1
```

Also assert the serialized payload contains neither a question nor a URL-like secret.

- [ ] **Step 2: Run the new test and verify RED**

Run:

```bash
.venv/bin/pytest tests/workflow/deep_analysis/test_jobs.py::test_record_dispatch_failure_marks_run_failed_with_bounded_event -q
```

Expected: collection or assertion failure because `record_dispatch_failure` does not exist.

- [ ] **Step 3: Generalize failure persistence without changing execution failures**

Change the private helper to accept an optional code and construct only bounded fields:

```python
async def _record_failure(
    session_factory,
    run_id: str,
    error: str,
    *,
    code: str | None = None,
) -> None:
    payload = {"error": error[:500]}
    if code is not None:
        payload["code"] = code
    try:
        async with session_factory() as session:
            run = await session.get(DARun, run_id)
            if run is not None:
                run.status = "failed"
            await _log_lifecycle(session, run_id, JOB_FAILED, payload)
    except Exception:
        logger.error(
            "failed to persist job_failed for deep_analysis run %s",
            run_id,
            exc_info=True,
        )


async def record_dispatch_failure(session_factory, run_id: str) -> None:
    await _record_failure(
        session_factory,
        run_id,
        "Celery broker dispatch failed",
        code="E_BROKER_DISPATCH",
    )
```

Keep `execute_run` calling `_record_failure` without a code so all existing execution-failure payloads remain backward compatible.

- [ ] **Step 4: Run job lifecycle tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/workflow/deep_analysis/test_jobs.py -q
```

Expected: all tests pass, including existing timeout and orchestration failure cases.

- [ ] **Step 5: Commit the lifecycle primitive**

```bash
git add neos/workflow/deep_analysis/jobs.py tests/workflow/deep_analysis/test_jobs.py
git commit -m "feat(deep-analysis): record broker dispatch failures"
```

### Task 2: Async Dispatcher with Explicit Broker Failure

**Files:**
- Modify: `neos/tasks/deep_analysis_job_task.py`
- Modify: `tests/workflow/deep_analysis/test_deep_analysis_job_task.py`
- Modify: `tests/tasks/test_deep_analysis_report_persistence.py`

**Interfaces:**
- Consumes: `record_dispatch_failure(session_factory, run_id) -> None`
- Produces: `DeepAnalysisDispatchError(run_id: str)`
- Changes: `async submit_deep_analysis_job(run_id: str, question: str = "", profile: str = "dev", *, resume: bool = False) -> str`

- [ ] **Step 1: Convert success-path tests to the intended async interface**

Mark Celery submit, inline submit, strong-reference, and resume passthrough tests async where necessary and await the dispatcher:

```python
executor = await task_module.submit_deep_analysis_job(
    "run00001", "질문", "dev"
)
```

Update the source-inspection assertion in
`tests/tasks/test_deep_analysis_report_persistence.py` to accept the async
function while retaining its `_execute(` boundary assertion.

- [ ] **Step 2: Add failing broker-policy tests**

Add a test with `apply_async` raising a sentinel exception and patch the durable
recorder:

```python
@pytest.mark.asyncio
async def test_celery_broker_failure_is_recorded_and_never_runs_inline(monkeypatch):
    recorded = []
    executed = False

    def broker_down(**kwargs):
        raise ConnectionError("redis://user:secret@broker")

    async def record(session_factory, run_id):
        recorded.append(run_id)

    async def execute(*args, **kwargs):
        nonlocal executed
        executed = True

    monkeypatch.setattr(task_module, "_celery_enabled", lambda: True)
    monkeypatch.setattr(task_module.run_deep_analysis_job, "apply_async", broker_down)
    monkeypatch.setattr(task_module, "_record_dispatch_failure", record)
    monkeypatch.setattr(task_module, "_execute", execute)

    with pytest.raises(task_module.DeepAnalysisDispatchError) as captured:
        await task_module.submit_deep_analysis_job("run00001", "private question")

    assert str(captured.value) == "deep_analysis dispatch failed for run run00001"
    assert recorded == ["run00001"]
    assert executed is False
    assert isinstance(captured.value.__cause__, ConnectionError)
    assert "secret" not in str(captured.value)
```

Add a second test where `_record_dispatch_failure` raises. Assert the raised
exception is still `DeepAnalysisDispatchError` chained from the original
`ConnectionError`, not the persistence error.

- [ ] **Step 3: Run dispatcher tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/workflow/deep_analysis/test_deep_analysis_job_task.py tests/tasks/test_deep_analysis_report_persistence.py -q
```

Expected: failures because submission is synchronous and the custom exception
and durable recorder binding do not exist.

- [ ] **Step 4: Implement the async dispatch boundary**

Add the bounded exception and lazy failure imports without exposing broker
details:

```python
class DeepAnalysisDispatchError(RuntimeError):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"deep_analysis dispatch failed for run {run_id}")
        self.run_id = run_id


async def _record_dispatch_failure(run_id: str) -> None:
    from neos.database.connection import get_session_ctx
    from neos.workflow.deep_analysis.jobs import record_dispatch_failure

    await record_dispatch_failure(get_session_ctx, run_id)
```

Convert the dispatcher and wrap only the Celery enqueue operation:

```python
async def submit_deep_analysis_job(
    run_id: str,
    question: str = "",
    profile: str = "dev",
    *,
    resume: bool = False,
) -> str:
    kwargs = {
        "run_id": run_id,
        "question": question,
        "profile": profile,
        "resume": resume,
    }
    if _celery_enabled():
        try:
            run_deep_analysis_job.apply_async(
                kwargs=kwargs,
                queue=settings.config.deep_analysis.job_queue,
            )
        except Exception as exc:  # broker client exceptions vary by transport
            logger.error(
                "deep_analysis broker dispatch failed for run %s",
                run_id,
                exc_info=True,
            )
            try:
                await _record_dispatch_failure(run_id)
            except Exception:
                logger.error(
                    "deep_analysis dispatch failure persistence failed for run %s",
                    run_id,
                    exc_info=True,
                )
            raise DeepAnalysisDispatchError(run_id) from exc
        return "celery"

    task = asyncio.create_task(
        _execute(
            run_id,
            question,
            profile,
            resume,
            timeout_seconds=_config.job_soft_time_limit,
        )
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_discard_task)
    return "inline"
```

Do not catch failures from inline task construction; the policy applies only
to broker dispatch while Celery is enabled.

- [ ] **Step 5: Run dispatcher tests and verify GREEN**

Run the Step 3 command. Expected: all tests pass and no un-awaited coroutine
warnings occur.

- [ ] **Step 6: Commit the dispatcher policy**

```bash
git add neos/tasks/deep_analysis_job_task.py tests/workflow/deep_analysis/test_deep_analysis_job_task.py tests/tasks/test_deep_analysis_report_persistence.py
git commit -m "feat(deep-analysis): fail explicit broker dispatch"
```

### Task 3: API, Graph, Documentation, and Full Verification

**Files:**
- Modify: `neos/api/handlers/deep_analysis_handlers.py`
- Modify: `neos/workflow/graph.py`
- Modify: `tests/api/test_deep_analysis_api.py`
- Modify: `tests/workflow/test_deep_analysis_node.py`
- Modify: `docs/TODO_260729.md`

**Interfaces:**
- Consumes: `async submit_deep_analysis_job(run_id: str, question: str = "", profile: str = "dev", *, resume: bool = False) -> str`
- Consumes: `DeepAnalysisDispatchError`
- Produces: HTTP 503 for dedicated API dispatch failures

- [ ] **Step 1: Write failing API failure tests and convert success fakes**

Make every `fake_submit` in `test_deep_analysis_api.py` async and add initial
and resume failure cases:

```python
async def fail_submit(*args, **kwargs):
    raise DeepAnalysisDispatchError("run00001")

monkeypatch.setattr(handlers, "submit_deep_analysis_job", fail_submit)

with pytest.raises(HTTPException) as captured:
    await handlers.start_deep_analysis(request, user)

assert captured.value.status_code == 503
assert captured.value.detail == "Deep analysis dispatch unavailable"
```

Repeat for `resume_deep_analysis` and assert no accepted response is produced.

- [ ] **Step 2: Write the graph non-regression test**

In the existing graph submission-failure test, make the failing submit fake
async, raise `DeepAnalysisDispatchError`, and pass a recording event handler:

```python
assert out["final_response"] == "심층 분석을 시작하지 못했습니다."
assert out["deep_analysis_run_id"] is None
assert event_handler.deep_analysis_started == []
```

- [ ] **Step 3: Run integration-boundary tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/api/test_deep_analysis_api.py tests/workflow/test_deep_analysis_node.py -q
```

Expected: await/type failures and missing 503 mapping.

- [ ] **Step 4: Await dispatch and map the bounded exception**

In `deep_analysis_handlers.py`, import `DeepAnalysisDispatchError`, await both
submission calls, and use a focused helper:

```python
async def _submit_or_503(*args, **kwargs) -> str:
    try:
        return await submit_deep_analysis_job(*args, **kwargs)
    except DeepAnalysisDispatchError as exc:
        raise HTTPException(
            status_code=503,
            detail="Deep analysis dispatch unavailable",
        ) from exc
```

Use `_submit_or_503` from initial and resume handlers. In `graph.py`, change the
existing call to:

```python
executor = await submit_deep_analysis_job(run_id, query, profile)
```

Keep the graph's existing broad failure response boundary unchanged.

- [ ] **Step 5: Run boundary tests and verify GREEN**

Run the Step 3 command. Expected: all tests pass.

- [ ] **Step 6: Update the unresolved-work document**

In `docs/TODO_260729.md` §5, replace the undecided policy text with the completed
behavior: Celery-enabled dispatch is fail-loud, records `failed` plus
`job_failed/E_BROKER_DISPATCH`, returns API 503, and never silently falls back.
Move §15 to the first row of the recommendation table and add §5 to the
completed list.

- [ ] **Step 7: Run complete verification boundaries sequentially**

Run:

```bash
.venv/bin/pytest tests/workflow/deep_analysis -q -o log_cli=false
.venv/bin/pytest tests/workflow -q -o log_cli=false
.venv/bin/pytest tests/api -q -o log_cli=false
```

Expected: all pass. If the API suite exceeds the execution-cell limit, split it
without omitting files and report the summed count. Record approved asyncpg
event-loop-close warnings separately from failures.

- [ ] **Step 8: Run static and diff validation**

Run Ruff on every changed Python file, then:

```bash
git diff --check
rg -n "E_BROKER_DISPATCH|dispatch|다음 권고 순서" docs/TODO_260729.md
git status --short
```

Expected: Ruff and diff checks pass; only scoped files are staged or modified.

- [ ] **Step 9: Commit documentation and integration**

```bash
git add neos/api/handlers/deep_analysis_handlers.py neos/workflow/graph.py tests/api/test_deep_analysis_api.py tests/workflow/test_deep_analysis_node.py docs/TODO_260729.md
git commit -m "feat(deep-analysis): surface broker dispatch failures"
```

- [ ] **Step 10: Merge the verified feature branch locally**

Use the repository's feature-worktree workflow, merge into local `dev`, rerun
the complete deep-analysis suite on the merged result, then remove only the
worktree and feature branch created for this plan. Preserve all unrelated user
changes in the main worktree.

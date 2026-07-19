# Deep Analysis Failure Bounds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure zero-token worker failures converge and inline deep-analysis jobs time out into a durable, resumable failed state.

**Architecture:** Keep worker-failure convergence inside `Orchestrator` as a question-scoped in-memory safety signal, separate from ledger `fail_streak` and D15's general progress signal. Put the optional wall-clock timeout inside `jobs.execute_run()`'s existing durable failure boundary, and let only the inline dispatcher supply `job_soft_time_limit`; Celery retains its native soft/hard limits.

**Tech Stack:** Python 3.11 asyncio, pytest/pytest-asyncio, SQLAlchemy async session test doubles, Celery task dispatcher.

## Global Constraints

- Reuse `max_stall_rounds` for the consecutive worker-failure cap; add no new configuration field.
- Reuse `deep_analysis.job_soft_time_limit` for inline execution.
- Do not change Celery retry, soft-limit, or hard-limit semantics.
- Do not publish or persist a partial report after a job timeout.
- Preserve existing user changes outside the files listed below.

---

## File Map

- `neos/workflow/deep_analysis/orchestrator.py`: classify failed worker passes before generic progress accounting and terminate repeatedly failing questions.
- `tests/workflow/deep_analysis/test_orchestrator_m3_integration.py`: exercise repeated failure through the real round/ledger contract.
- `neos/workflow/deep_analysis/jobs.py`: apply an optional timeout inside the existing run failure boundary and forward it through resume.
- `tests/workflow/deep_analysis/test_jobs.py`: verify timeout, durable failure event, and timeout propagation on resume.
- `neos/tasks/deep_analysis_job_task.py`: pass the configured timeout only for inline execution.
- `tests/workflow/deep_analysis/test_deep_analysis_job_task.py`: verify executor-specific timeout wiring and no assistant-message persistence after failure.

### Task 1: Bound consecutive failed worker passes

**Files:**
- Modify: `neos/workflow/deep_analysis/orchestrator.py:96-105, 413-441, 518-531`
- Test: `tests/workflow/deep_analysis/test_orchestrator_m3_integration.py`

**Interfaces:**
- Consumes: `WorkerResult.status: str`, `WorkerResult.fail_reason: str | None`, `Orchestrator.max_stall_rounds: int`.
- Produces: `Orchestrator._register_worker_outcome(question_id: str, result: WorkerResult, made_progress: bool) -> None`; question-scoped failure counts and `worker_failed`/`stall_terminated` event payloads.

- [ ] **Step 1: Add a failing repeated-zero-token-worker regression test**

Add a worker that always returns `WorkerResult(question_id=qid, status="failed", tokens_spent=0, fail_reason="systemic")`, configure `max_depth=1` and `max_stall_rounds=2`, and run the orchestrator under `asyncio.wait_for(..., timeout=1)`. Assert it returns a report, the failing leaf is no longer open, and exactly two `worker_failed` events were logged for that question.

```python
class AlwaysFailingWorker:
    async def investigate(self, brief, effort, qid, **kwargs):
        return WorkerResult(
            question_id=qid,
            status="failed",
            tokens_spent=0,
            fail_reason="systemic",
        )

    def flush_partial(self, qid):
        return WorkerResult(question_id=qid, status="partial")


result = await asyncio.wait_for(orch.run("root"), timeout=1)
assert result["report_markdown"]
assert question.status in {"split", "abandoned"}
assert [e.kind for e in events].count("worker_failed") == 2
```

- [ ] **Step 2: Run the regression test and verify it fails**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_orchestrator_m3_integration.py -k zero_token_worker_failure -q`

Expected: FAIL by the 1-second outer timeout because repeated failed passes do not trip D15.

- [ ] **Step 3: Add question-scoped failure outcome accounting**

Initialize `self._failure_counts: dict[str, int] = {}`. Add `_register_worker_outcome()` so failed results increment and log before reaching the cap, while a non-failed pass with real progress resets the counter.

```python
async def _register_worker_outcome(
    self,
    question_id: str,
    result: WorkerResult,
    made_progress: bool,
) -> None:
    if result.status != "failed":
        if made_progress:
            self._failure_counts[question_id] = 0
        await self._register_progress(question_id, made_progress)
        return

    count = self._failure_counts.get(question_id, 0) + 1
    self._failure_counts[question_id] = count
    payload = {
        "count": count,
        "reason": (result.fail_reason or "")[:500],
    }
    await self.ledger.log("worker_failed", question_id, payload)
    await self._emit("worker_failed", {"qid": question_id, **payload})
    if count >= self.max_stall_rounds:
        await self._force_terminate_stalled(
            question_id,
            reason="worker_failure",
        )
```

Extend `_force_terminate_stalled(question_id, *, reason="no_progress")` and include `reason` in both logged and emitted payloads. Replace the successful commit path's `_register_progress(...)` call with `_register_worker_outcome(...)`.

- [ ] **Step 4: Run focused orchestrator tests**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_orchestrator_m3_integration.py tests/workflow/deep_analysis/test_orchestrator_run_worker.py -q`

Expected: all tests PASS, including the new bounded-failure regression.

- [ ] **Step 5: Commit the bounded worker-failure behavior**

```bash
git add neos/workflow/deep_analysis/orchestrator.py tests/workflow/deep_analysis/test_orchestrator_m3_integration.py
git commit -m "fix: bound repeated deep analysis worker failures"
```

### Task 2: Make job timeout durable and resumable

**Files:**
- Modify: `neos/workflow/deep_analysis/jobs.py:103-176`
- Test: `tests/workflow/deep_analysis/test_jobs.py`

**Interfaces:**
- Consumes: optional `timeout_seconds: float | None` supplied by an executor.
- Produces: `execute_run(..., timeout_seconds: float | None = None) -> dict[str, str]` and `resume_run(..., timeout_seconds: float | None = None) -> dict[str, str]`.

- [ ] **Step 1: Add failing timeout contract tests**

Add a blocking fake orchestrator and call `execute_run(..., timeout_seconds=0.01)`. Assert `TimeoutError`, `JOB_STARTED` in the run session, `JOB_FAILED` in the fresh failure session, and `run.status == "failed"`. Add a resume test with three ordered fake sessions: lookup session, execution session, and failure session. Pass `timeout_seconds=0.01` to `resume_run()` and assert the blocking resumed orchestrator times out, the execution session contains `JOB_RESUMED`, and the failure session contains `JOB_FAILED` with `run.status == "failed"`.

```python
with pytest.raises(asyncio.TimeoutError):
    await jobs.execute_run(
        factory,
        "run00001",
        "질문",
        "dev",
        timeout_seconds=0.01,
        build_orchestrator_fn=build_blocking,
    )

assert kinds(run_session) == [jobs.JOB_STARTED]
assert kinds(fail_session) == [jobs.JOB_FAILED]
assert fail_session.run.status == "failed"
```

The resume test uses the same blocking builder and makes the forwarding assertion behaviorally:

```python
with pytest.raises(asyncio.TimeoutError):
    await jobs.resume_run(
        make_factory([lookup_session, run_session, fail_session]),
        "run00001",
        timeout_seconds=0.01,
        build_orchestrator_fn=build_blocking,
    )

assert kinds(run_session) == [jobs.JOB_RESUMED]
assert kinds(fail_session) == [jobs.JOB_FAILED]
assert fail_session.run.status == "failed"
```

- [ ] **Step 2: Run timeout tests and verify they fail**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_jobs.py -k timeout -q`

Expected: FAIL because `execute_run()` and `resume_run()` do not accept `timeout_seconds`.

- [ ] **Step 3: Add the timeout inside the durable failure boundary**

Add `import asyncio`, accept the optional parameter, and place `wait_for` inside the existing `try`.

```python
try:
    run_coro = orchestrator.run(question)
    result = (
        await asyncio.wait_for(run_coro, timeout=timeout_seconds)
        if timeout_seconds is not None
        else await run_coro
    )
except Exception as exc:
    await _record_failure(session_factory, run_id, str(exc)[:500])
    raise
```

Forward `timeout_seconds` unchanged from `resume_run()` into its `execute_run()` call. Preserve the default `None` so existing callers and Celery behavior do not change.

- [ ] **Step 4: Run job-core tests**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_jobs.py -q`

Expected: all tests PASS; timeout creates `JOB_FAILED` and completed runs still create only `JOB_COMPLETED`.

- [ ] **Step 5: Commit the durable timeout contract**

```bash
git add neos/workflow/deep_analysis/jobs.py tests/workflow/deep_analysis/test_jobs.py
git commit -m "fix: record inline deep analysis timeouts"
```

### Task 3: Wire the timeout only into the inline executor

**Files:**
- Modify: `neos/tasks/deep_analysis_job_task.py:49-62, 123-162`
- Test: `tests/workflow/deep_analysis/test_deep_analysis_job_task.py`

**Interfaces:**
- Consumes: `settings.config.deep_analysis.job_soft_time_limit`.
- Produces: `_execute(..., timeout_seconds: float | None = None)`; Celery calls with `None`, inline dispatch calls with the configured integer.

- [ ] **Step 1: Add failing executor-wiring tests**

Update inline fake `_execute` functions to accept `timeout_seconds=None`, capture it, and assert it equals `settings.config.deep_analysis.job_soft_time_limit`. Assert Celery kwargs remain exactly the current run/question/profile/resume mapping with no timeout key.

```python
async def fake_execute(
    run_id, question, profile, resume, *, timeout_seconds=None
):
    seen["timeout_seconds"] = timeout_seconds
    ran.set()

assert seen["timeout_seconds"] == settings.config.deep_analysis.job_soft_time_limit
assert "timeout_seconds" not in captured["kwargs"]
```

- [ ] **Step 2: Run dispatcher tests and verify the new assertion fails**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_deep_analysis_job_task.py -q`

Expected: FAIL because inline dispatch does not supply the configured timeout.

- [ ] **Step 3: Forward the timeout without changing Celery semantics**

Extend `_execute` and forward `timeout_seconds` to `execute_run`/`resume_run`. In `submit_deep_analysis_job`, keep Celery kwargs unchanged and create the inline task with:

```python
task = asyncio.create_task(
    _execute(
        run_id,
        question,
        profile,
        resume,
        timeout_seconds=settings.config.deep_analysis.job_soft_time_limit,
    )
)
```

Because `_persist_assistant_message()` remains after the awaited job-core call, any timeout skips assistant-message persistence automatically.

- [ ] **Step 4: Run executor and job tests together**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/test_deep_analysis_job_task.py tests/workflow/deep_analysis/test_jobs.py -q`

Expected: all tests PASS; inline has a timeout and Celery task kwargs/time limits are unchanged.

- [ ] **Step 5: Commit executor wiring**

```bash
git add neos/tasks/deep_analysis_job_task.py tests/workflow/deep_analysis/test_deep_analysis_job_task.py
git commit -m "fix: bound inline deep analysis jobs"
```

### Task 4: Verify the complete §1 change

**Files:**
- Verify only: all files changed in Tasks 1-3.

**Interfaces:**
- Consumes: the bounded worker failure behavior and executor timeout contract.
- Produces: evidence that §1 acceptance criteria pass without regressions.

- [ ] **Step 1: Run the focused deep-analysis suite**

Run: `.venv/bin/pytest tests/workflow/deep_analysis/ -q`

Expected: all tests PASS.

- [ ] **Step 2: Run API regression tests for deep-analysis job lifecycle**

Run: `.venv/bin/pytest tests/api/test_deep_analysis_api.py tests/api/adapters/test_deep_analysis_stream_adapter.py -q`

Expected: all tests PASS.

- [ ] **Step 3: Run static formatting checks on changed Python files**

Run: `.venv/bin/ruff check neos/workflow/deep_analysis/orchestrator.py neos/workflow/deep_analysis/jobs.py neos/tasks/deep_analysis_job_task.py tests/workflow/deep_analysis/test_orchestrator_m3_integration.py tests/workflow/deep_analysis/test_jobs.py tests/workflow/deep_analysis/test_deep_analysis_job_task.py`

Expected: no lint errors.

- [ ] **Step 4: Review the final diff and status**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intentional §1 files plus pre-existing user changes are present.

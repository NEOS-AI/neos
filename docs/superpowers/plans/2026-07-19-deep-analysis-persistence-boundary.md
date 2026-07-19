# Deep Analysis Persistence Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대화 메시지 부가 영속화의 DB 조회·저장 실패가 완료된 deep-analysis run 결과를 바꾸지 않게 하면서 작업 취소와 제한된 로그 계약을 보존한다.

**Architecture:** `_persist_assistant_message()`의 DB lookup과 `ChatService.add_message()`를 하나의 fail-soft 경계로 묶는다. 일반 예외는 `run_id`와 예외 타입만 기록하고 반환하며, `CancelledError`는 `BaseException` 경계를 통해 전파한다.

**Tech Stack:** Python 3.12, asyncio, SQLAlchemy async session, ChatService, pytest/pytest-asyncio, PostgreSQL, Ruff

## Global Constraints

- 함수 반환형은 `None`을 유지한다.
- 대화가 없는 run은 정상 no-op이다.
- `Exception`만 삼키며 `CancelledError`, `KeyboardInterrupt`, `SystemExit`은 전파한다.
- 로그에는 `run_id`와 `error_type`만 남기고 예외 원문·보고서·대화 식별자·DB 정보를 남기지 않는다.
- outbox, 별도 retry worker, schema/event 계약은 추가하지 않는다.
- 사용자 소유 dirty/untracked 파일은 수정하거나 staging하지 않는다.

---

### Task 1: Fail-Soft Persistence Boundary

**Files:**
- Modify: `neos/tasks/deep_analysis_job_task.py:49-85`
- Modify: `tests/tasks/test_deep_analysis_report_persistence.py`

**Interfaces:**
- Consumes: `get_session_ctx()`, `session.get(DARun, run_id)`, `ChatService.add_message(conversation_id, role, content, message_id, model_name, metadata)`
- Produces: `_persist_assistant_message(run_id: str, report_markdown: str) -> None` with bounded fail-soft semantics

- [ ] **Step 1: Write failing boundary tests**

Add helpers that install fake `neos.database.connection`, `neos.database.deep_analysis_models`, and `neos.api.services.chat_service` modules through `monkeypatch.setitem(sys.modules, module_name, fake_module)`. Add tests equivalent to:

```python
async def test_lookup_failure_is_swallowed_and_logged_without_payload(monkeypatch, caplog):
    session = SimpleNamespace(get=AsyncMock(side_effect=RuntimeError("secret db url")))
    install_dependencies(monkeypatch, session=session, add_message=AsyncMock())
    with caplog.at_level(logging.WARNING):
        await task_mod._persist_assistant_message("run1", "secret report")
    assert "run=run1" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "secret db url" not in caplog.text
    assert "secret report" not in caplog.text

async def test_message_failure_is_swallowed_with_bounded_log(monkeypatch, caplog):
    run = SimpleNamespace(conversation_id="c1", assistant_message_id="m1")
    add_message = AsyncMock(side_effect=ValueError("secret message"))
    install_dependencies(monkeypatch, session=FakeSession(run), add_message=add_message)
    await task_mod._persist_assistant_message("run1", "report")
    assert "error_type=ValueError" in caplog.text
    assert "secret message" not in caplog.text
```

Also add: context-manager entry failure is swallowed; `asyncio.CancelledError` from lookup and message save propagates; missing conversation/message IDs remain no-op.

- [ ] **Step 2: Run tests and confirm RED**

Run:

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest \
  tests/tasks/test_deep_analysis_report_persistence.py \
  -q -o log_cli=false
```

Expected: lookup/context failures escape and bounded-log assertions fail because the current `try` starts after DB lookup and logs `str(exc)`.

- [ ] **Step 3: Implement the minimal boundary change**

Restructure the function without changing arguments:

```python
try:
    async with get_session_ctx() as session:
        run = await session.get(DARun, run_id)
        conversation_id = getattr(run, "conversation_id", None)
        message_id = getattr(run, "assistant_message_id", None)

    if not conversation_id or not message_id:
        return

    await ChatService.add_message(
        conversation_id=conversation_id,
        role="assistant",
        content=report_markdown,
        message_id=message_id,
        model_name="deep-analysis-harness",
        metadata={
            "deep_analysis_run_id": run_id,
            "research_status": "completed",
        },
    )
except Exception as exc:
    logger.warning(
        "failed to persist deep_analysis report message: run=%s error_type=%s",
        run_id,
        type(exc).__name__,
    )
```

Do not add a broad `BaseException` catch or explicit `CancelledError` catch.

- [ ] **Step 4: Run unit tests and Ruff**

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest \
  tests/tasks/test_deep_analysis_report_persistence.py \
  tests/workflow/deep_analysis/test_deep_analysis_job_task.py \
  -q -o log_cli=false
uv run --frozen ruff check \
  neos/tasks/deep_analysis_job_task.py \
  tests/tasks/test_deep_analysis_report_persistence.py
```

Expected: all selected tests PASS; Ruff says `All checks passed!`.

- [ ] **Step 5: Run real PostgreSQL integration tests**

With configured local `DATABASE_URL` and sandbox-external DB access, run:

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest \
  tests/tasks/test_deep_analysis_persistence_integration.py \
  -q -o log_cli=false
```

Expected: all three integration tests PASS.

- [ ] **Step 6: Commit the boundary fix**

```bash
git add \
  neos/tasks/deep_analysis_job_task.py \
  tests/tasks/test_deep_analysis_report_persistence.py
git commit -m "fix: bound deep analysis report persistence failures"
```

---

### Task 2: Regression and TODO Completion

**Files:**
- Modify: `docs/TODO_260729.md:206-217, summary table`

**Interfaces:**
- Consumes: Task 1 fail-soft behavior and verification evidence
- Produces: completed §8 record

- [ ] **Step 1: Run deep-analysis task regression**

```bash
HOME=/tmp/neos-test-home .venv/bin/pytest \
  tests/tasks/test_deep_analysis_report_persistence.py \
  tests/tasks/test_deep_analysis_persistence_integration.py \
  tests/workflow/deep_analysis/test_deep_analysis_job_task.py \
  tests/tasks/test_deep_analysis_job_security.py \
  -q -o log_cli=false
```

Expected: all selected tests PASS with PostgreSQL access enabled.

- [ ] **Step 2: Run final static checks**

Run Ruff on the changed Python files and `git diff --check`.

Expected: no lint or whitespace errors.

- [ ] **Step 3: Update §8**

Record the widened DB lookup/save boundary, cancellation propagation, bounded logging, focused and PostgreSQL test results, and implementation commit hash. Remove §8 from the recommendation table and add it to the completed list. If no actionable rows remain, state that the TODO has no remaining implementation-priority item and retain §7 production funnel observation as a data-collection decision.

- [ ] **Step 4: Commit documentation**

```bash
git add docs/TODO_260729.md
git commit -m "docs: mark persistence boundary complete"
```

- [ ] **Step 5: Verify feature branch state**

Run `git status --short` and `git log --oneline -5`.

Expected: feature work is committed and only pre-existing user-owned files remain.

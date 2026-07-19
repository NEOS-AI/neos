# Async Research Redis Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Celery 워커와 API 프로세스가 Redis Streams를 통해 async research SSE 이벤트를 누락·중복 없이 교환하게 한다.

**Architecture:** 새 `AsyncResearchEventStream`이 Redis `XADD`/`XREAD`와 JSON 직렬화를 캡슐화한다. Celery는 이 저장소에 이벤트를 append하고, API SSE는 Redis entry ID를 커서로 blocking read하며 기존 소유권 캐시 검증을 유지한다.

**Tech Stack:** Python 3.12, FastAPI StreamingResponse, Celery, `redis.asyncio`, pytest, pytest-asyncio

## Global Constraints

- Redis stream key는 `neos:async-research:events:{session_id}` 형식이다.
- TTL은 86,400초, 최대 길이는 `MAXLEN ~ 1000`, read batch는 100개, block timeout은 15,000ms다.
- Redis entry ID를 SSE `id`와 `Last-Event-ID` 커서로 그대로 사용한다.
- 소유권은 기존 `async_research_session_owner:{session_id}` 캐시 키로 검증한다.
- `deep_analysis`와 기존 `StreamManager`의 다른 호출자는 변경하지 않는다.
- Redis 장애를 무한 heartbeat로 숨기지 않는다.
- 작업 중 사용자 소유 dirty/untracked 파일을 staging하거나 수정하지 않는다.

---

### Task 1: Redis Stream Event Store

**Files:**
- Create: `neos/workflow/async_research_event_stream.py`
- Create: `tests/workflow/test_async_research_event_stream.py`

**Interfaces:**
- Consumes: `cache_manager.initialize()`와 `cache_manager.redis_client`
- Produces: `AsyncResearchEventStream(redis_client=None, key_prefix="neos:async-research:events", ttl_seconds=86400, max_length=1000)`, `append(session_id: str, event: str, data: Any) -> str`, `read_after(session_id: str, last_event_id: str = "0-0", block_ms: int = 15000, count: int = 100) -> list[StreamEvent]`, 전역 `async_research_event_stream`

- [ ] **Step 1: Write the failing store tests**

Create an in-test `FakeRedisStreams` that records `xadd`, `expire`, and `xread` calls and shares records between two clients. Add tests equivalent to:

```python
async def test_append_sets_max_length_and_refreshes_ttl():
    redis = FakeRedisStreams()
    store = AsyncResearchEventStream(redis, ttl_seconds=86400, max_length=1000)
    event_id = await store.append("s1", "workflow_started", {"task_id": "j1"})
    assert event_id == "1-0"
    assert redis.xadd_calls == [
        ("neos:async-research:events:s1", {"event": "workflow_started", "data": '{"task_id": "j1"}'}, 1000, True)
    ]
    assert redis.expire_calls == [("neos:async-research:events:s1", 86400)]

async def test_separate_store_instances_replay_only_after_cursor():
    redis = FakeRedisStreams()
    producer = AsyncResearchEventStream(redis)
    consumer = AsyncResearchEventStream(redis)
    first = await producer.append("s1", "workflow_started", {"step": 1})
    await producer.append("s1", "workflow_completed", {"step": 2})
    events = await consumer.read_after("s1", first, block_ms=0)
    assert [(event.id, event.event) for event in events] == [("2-0", "workflow_completed")]
```

Also cover bytes responses, empty reads, malformed records being skipped with a warning, and an invalid local cursor rejected by `validate_event_id()`.

- [ ] **Step 2: Run the store tests and confirm RED**

Run: `.venv/bin/pytest tests/workflow/test_async_research_event_stream.py -q`

Expected: collection fails with `ModuleNotFoundError: neos.workflow.async_research_event_stream`.

- [ ] **Step 3: Implement the minimal Redis store**

Implement a focused module with this shape:

```python
EVENT_ID_PATTERN = re.compile(r"^(?:0|[1-9]\d*)-(?:0|[1-9]\d*)$")

def validate_event_id(value: str) -> str:
    if not EVENT_ID_PATTERN.fullmatch(value):
        raise ValueError("Invalid Redis stream event ID")
    return value

class AsyncResearchEventStream:
    async def _client(self):
        if self._redis is not None:
            return self._redis
        if cache_manager.redis_client is None:
            await cache_manager.initialize()
        return cache_manager.redis_client

    async def append(self, session_id, event, data):
        client = await self._client()
        key = self._key(session_id)
        event_id = await client.xadd(
            key,
            {"event": event, "data": json.dumps(data, ensure_ascii=False)},
            maxlen=self.max_length,
            approximate=True,
        )
        await client.expire(key, self.ttl_seconds)
        return _decode(event_id)

    async def read_after(self, session_id, last_event_id="0-0", block_ms=15000, count=100):
        cursor = validate_event_id(last_event_id)
        records = await (await self._client()).xread(
            {self._key(session_id): cursor}, count=count, block=block_ms
        )
        return self._decode_records(records)
```

Decode both `str` and `bytes`. Construct existing `StreamEvent` values with Redis IDs. Catch only per-record decode/JSON errors, log session ID and event ID without payload, and continue.

- [ ] **Step 4: Run store tests and workflow lint**

Run: `.venv/bin/pytest tests/workflow/test_async_research_event_stream.py -q`

Expected: all tests PASS.

Run: `.venv/bin/ruff check neos/workflow/async_research_event_stream.py tests/workflow/test_async_research_event_stream.py`

Expected: `All checks passed!`

- [ ] **Step 5: Commit the store**

```bash
git add neos/workflow/async_research_event_stream.py tests/workflow/test_async_research_event_stream.py
git commit -m "feat: add async research Redis event stream"
```

---

### Task 2: Celery Producer Migration

**Files:**
- Modify: `neos/workflow/celery_tasks.py:270-375`
- Create: `tests/workflow/test_async_research_celery_events.py`

**Interfaces:**
- Consumes: Task 1 전역 `async_research_event_stream.append(session_id, event, data) -> str`
- Produces: `_publish_workflow_event(session_id: str, event: str, data: dict[str, Any]) -> str`; `_execute_workflow_full_async()` publishes start and terminal completion through Redis

- [ ] **Step 1: Write failing Celery producer tests**

Stub `neos.workflow.graph.multi_agent_workflow.execute_workflow` and monkeypatch the event store. Add:

```python
async def test_workflow_publishes_started_then_completed(monkeypatch):
    append = AsyncMock(side_effect=["1-0", "2-0"])
    monkeypatch.setattr(celery_tasks.async_research_event_stream, "append", append)
    result = await celery_tasks._execute_workflow_full_async(
        query="q", user_id="u1", conversation_id="c1",
        session_id="s1", language="ko", celery_task_id="j1",
    )
    assert [call.args[1] for call in append.await_args_list] == [
        "workflow_started", "workflow_completed"
    ]
    assert result["status"] == "completed"

async def test_start_publish_failure_prevents_workflow_execution(monkeypatch):
    append = AsyncMock(side_effect=ConnectionError("redis unavailable"))
    execute = AsyncMock()
    fake_graph = SimpleNamespace(
        multi_agent_workflow=SimpleNamespace(execute_workflow=execute)
    )
    monkeypatch.setitem(sys.modules, "neos.workflow.graph", fake_graph)
    monkeypatch.setattr(celery_tasks.async_research_event_stream, "append", append)
    with pytest.raises(ConnectionError, match="redis unavailable"):
        await celery_tasks._execute_workflow_full_async(
            query="q",
            user_id="u1",
            conversation_id="c1",
            session_id="s1",
            language="ko",
            celery_task_id="j1",
        )
    execute.assert_not_awaited()
```

Add a task-wrapper test proving the original workflow exception is retained when publishing `workflow_failed` also raises. Add a completion publish failure test proving the async helper does not return success.

- [ ] **Step 2: Run producer tests and confirm RED**

Run: `.venv/bin/pytest tests/workflow/test_async_research_celery_events.py -q`

Expected: tests fail because calls still target `stream_manager` or the event store attribute is absent.

- [ ] **Step 3: Replace in-memory publishing with Redis append**

At module scope import `async_research_event_stream`. Change both helper paths:

```python
async def _publish_workflow_event(session_id, event, data) -> str:
    return await async_research_event_stream.append(session_id, event, data)
```

Use `_publish_workflow_event()` for `workflow_started` and `workflow_completed`. In the task exception handler, catch failure-event publication separately and call `logger.exception("[Celery] Failed to publish workflow failure event: task=%s", task_id)`, but keep `e` as the retry/result cause. Do not restore the silent `except Exception: pass` behavior.

- [ ] **Step 4: Run producer and existing workflow tests**

Run: `.venv/bin/pytest tests/workflow/test_async_research_celery_events.py tests/workflow/test_deep_analysis_job_no_regression.py -q`

Expected: all tests PASS.

Run: `.venv/bin/ruff check neos/workflow/celery_tasks.py tests/workflow/test_async_research_celery_events.py`

Expected: `All checks passed!`

- [ ] **Step 5: Commit the producer migration**

```bash
git add neos/workflow/celery_tasks.py tests/workflow/test_async_research_celery_events.py
git commit -m "fix: publish async research events through Redis"
```

---

### Task 3: SSE Consumer, Cursor, and Failure Semantics

**Files:**
- Modify: `neos/api/handlers/async_research_handlers.py:1-215`
- Modify: `tests/api/handlers/test_research_authorization.py`
- Create: `tests/api/handlers/test_async_research_streaming.py`

**Interfaces:**
- Consumes: Task 1 `validate_event_id(value: str) -> str`, `async_research_event_stream.read_after(session_id, last_event_id, block_ms, count) -> list[StreamEvent]`
- Produces: authenticated SSE endpoint supporting `Last-Event-ID`, replay, heartbeat, terminal completion/failure, and terminal `stream_error`

- [ ] **Step 1: Write failing SSE behavior tests**

Call `stream_research_progress()` directly, consume `response.body_iterator`, and use an injected `AsyncMock` store. Add tests equivalent to:

```python
async def test_stream_replays_after_last_event_id_without_duplicates(monkeypatch):
    store = SimpleNamespace(read_after=AsyncMock(side_effect=[
        [StreamEvent("2-0", "workflow_started", '{"step":1}')],
        [StreamEvent("3-0", "workflow_completed", '{"ok":true}')],
    ]))
    request = SimpleNamespace(
        headers={"last-event-id": "1-0"},
        is_disconnected=AsyncMock(return_value=False),
    )
    response = await stream_research_progress("s1", request, current_user=_user())
    chunks = [chunk async for chunk in response.body_iterator]
    assert store.read_after.await_args_list[0].args[:2] == ("s1", "1-0")
    assert store.read_after.await_args_list[1].args[:2] == ("s1", "2-0")
    assert sum("id: 2-0" in chunk for chunk in chunks) == 1
    assert "event: workflow_completed" in chunks[-1]
```

Also cover: no header uses `0-0`; empty read yields one heartbeat; terminal failure closes; malformed header raises HTTP 400 before returning a response; Redis read exception yields a `stream_error` event and closes; missing/foreign owner never invokes the store.

- [ ] **Step 2: Run SSE tests and confirm RED**

Run: `.venv/bin/pytest tests/api/handlers/test_async_research_streaming.py tests/api/handlers/test_research_authorization.py -q`

Expected: new tests fail because the handler still claims an in-memory session and ignores `Last-Event-ID`.

- [ ] **Step 3: Migrate handler to Redis cursor reads**

Remove `stream_manager` usage from this handler and import the Task 1 store. Before creating `StreamingResponse`, parse:

```python
last_event_id = request.headers.get("last-event-id", "0-0")
try:
    validate_event_id(last_event_id)
except ValueError as exc:
    raise HTTPException(status_code=400, detail="Invalid Last-Event-ID") from exc
```

Inside the generator, hold a local `cursor`. Call `read_after(session_id, cursor, block_ms=15000, count=100)`. If empty, yield `: heartbeat\n\n`. For each event, yield `event.to_sse_format()`, update `cursor = event.id`, and return on `workflow_completed` or `workflow_failed`. On Redis exceptions, log only exception type/session ID, yield a terminal `StreamEvent(id=cursor, event="stream_error", data='{"error":"Event stream unavailable"}')`, then return. Remove `claim_session()` and `disconnect()` calls; owner-cache validation remains first.

- [ ] **Step 4: Run API tests and lint**

Run: `.venv/bin/pytest tests/api/handlers/test_async_research_streaming.py tests/api/handlers/test_research_authorization.py -q`

Expected: all tests PASS.

Run: `.venv/bin/ruff check neos/api/handlers/async_research_handlers.py tests/api/handlers/test_async_research_streaming.py tests/api/handlers/test_research_authorization.py`

Expected: `All checks passed!`

- [ ] **Step 5: Commit the SSE migration**

```bash
git add neos/api/handlers/async_research_handlers.py tests/api/handlers/test_async_research_streaming.py tests/api/handlers/test_research_authorization.py
git commit -m "fix: stream async research events across processes"
```

---

### Task 4: Integrated Regression and TODO Completion

**Files:**
- Modify: `docs/TODO_260729.md:290-325`

**Interfaces:**
- Consumes: Tasks 1-3 complete Redis producer/consumer path
- Produces: verified §15 completion record

- [ ] **Step 1: Run focused cross-process regression suite**

Run: `.venv/bin/pytest tests/workflow/test_async_research_event_stream.py tests/workflow/test_async_research_celery_events.py tests/api/handlers/test_async_research_streaming.py tests/api/handlers/test_research_authorization.py -q`

Expected: all tests PASS, including separate producer/consumer store instances sharing only fake Redis state.

- [ ] **Step 2: Run broader workflow and API suites**

Run: `.venv/bin/pytest tests/workflow tests/api/handlers -q`

Expected: all tests PASS. Environment-only warnings are acceptable; test failures are not.

- [ ] **Step 3: Run final static checks**

Run: `.venv/bin/ruff check neos/workflow/async_research_event_stream.py neos/workflow/celery_tasks.py neos/api/handlers/async_research_handlers.py tests/workflow/test_async_research_event_stream.py tests/workflow/test_async_research_celery_events.py tests/api/handlers/test_async_research_streaming.py tests/api/handlers/test_research_authorization.py`

Expected: `All checks passed!`

Run: `git diff --check`

Expected: no output and exit code 0.

- [ ] **Step 4: Mark §15 complete with evidence**

Move §15 from “확인 완료 — 수정 필요” to the completed section or label it completed in place. Record the Redis Stream key, cursor behavior, terminal semantics, focused test command/result, and implementation commit hashes. Change the recommendation table so §6 PDF support becomes priority 1.

- [ ] **Step 5: Commit documentation and verification record**

```bash
git add docs/TODO_260729.md
git commit -m "docs: mark cross-process research streaming complete"
```

- [ ] **Step 6: Verify final branch state without touching user files**

Run: `git status --short`

Expected: only pre-existing user-owned modified/untracked files remain; all feature files are committed.

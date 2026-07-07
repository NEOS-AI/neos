# Task 7 Review Fix Report

## Findings addressed

1. **Production query/workflow route audit gap**
   - Added a real `neos.main.app` route matrix in `tests/api/handlers/test_query_authorization.py`.
   - Matrix now covers primary query/history/cache/stats/hyper-research/SSE, multimodal, unified process/upload/stream, deep research, async research job/status/stream, and similarity chat mutation/stream/config/analytics routes.
   - Updated route introspection helper to include FastAPI `_EffectiveRouteContext` entries from production included-router wrappers.
   - Tightened similarity config/analytics from readable public/private conversations to owner-only `get_owned_conversation`.

2. **Workflow SSE claim race**
   - Verified existing fix adds `StreamManager.claim_session()` and uses it before `StreamingResponse` return in workflow and async research SSE handlers.
   - Added/kept regression coverage for losing a session creation race without mutating the foreign session and for handler denial before workflow execution or buffer reads.

3. **Production `neos.main` import/session context**
   - Replaced nonexistent `get_async_session` import in scheduled task handlers with production `get_session_ctx`.
   - Removed the test-local compatibility bridge and added clean subprocess `import neos.main` coverage.

4. **DEBUG operational endpoints**
   - DEBUG `/debug/test-workflow` and `/debug/cache-stats` now use `get_current_admin_user`.
   - Added tests for unauthenticated/non-admin denial before workflow/cache side effects and DEBUG=true production graph dependency registration.

## Files changed

- `neos/api/handlers/async_research_handlers.py`
- `neos/api/handlers/deep_research_handlers.py`
- `neos/api/handlers/multimodal_handlers.py`
- `neos/api/handlers/scheduled_tasks_handlers.py`
- `neos/api/handlers/similarity_chat_handlers.py`
- `neos/api/handlers/unified_handlers.py`
- `neos/api/handlers/workflow_stream_handlers.py`
- `neos/api/models/deep_research_models.py`
- `neos/api/models/unified_models.py`
- `neos/main.py`
- `neos/workflow/stream_manager.py`
- `tests/api/handlers/test_query_authorization.py`
- `tests/api/handlers/test_alternate_query_authorization.py`
- `tests/api/handlers/test_research_authorization.py`
- `tests/api/handlers/test_scheduled_tasks_session_context.py`
- `tests/api/handlers/test_similarity_chat_authorization.py`
- `tests/workflow/test_stream_manager_authorization.py`

## Verification

- RED:
  - `env GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-only-secret-key-for-tests DEBUG=false .venv/bin/pytest -q tests/api/handlers/test_query_authorization.py::test_production_query_workflow_routes_have_explicit_authorization_matrix tests/api/handlers/test_similarity_chat_authorization.py::test_similarity_routes_hide_missing_and_foreign_resources`
  - Result before final similarity fix: **3 failed, 16 passed**.
  - Expected failures confirmed similarity config/analytics used `get_readable_conversation` and allowed foreign public conversations before service reads.

- GREEN targeted RED tests:
  - `env GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-only-secret-key-for-tests DEBUG=false .venv/bin/pytest -q tests/api/handlers/test_query_authorization.py::test_production_query_workflow_routes_have_explicit_authorization_matrix tests/api/handlers/test_similarity_chat_authorization.py::test_similarity_routes_hide_missing_and_foreign_resources`
  - Result: **19 passed, 49 warnings**.

- Impacted Task 7 suites:
  - `env GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-only-secret-key-for-tests DEBUG=false .venv/bin/pytest -q tests/api/handlers/test_query_authorization.py tests/api/handlers/test_alternate_query_authorization.py tests/api/handlers/test_research_authorization.py tests/api/handlers/test_similarity_chat_authorization.py tests/api/handlers/test_scheduled_tasks_session_context.py tests/workflow/test_stream_manager_authorization.py tests/api/handlers/test_query_handlers_autonomy.py`
  - Result: **104 passed, 49 warnings**.

- Import regression with configured key:
  - `env GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-only-secret-key-for-tests DEBUG=false .venv/bin/python -c 'import neos.main'`
  - Result: exit **0**.

- Import regression with `GOOGLE_API_KEY` unset:
  - `env -u GOOGLE_API_KEY JWT_SECRET_KEY=test-only-secret-key-for-tests DEBUG=false .venv/bin/python -c 'import neos.main'`
  - Result: exit **1**.
  - Failure: `ValueError: GOOGLE_API_KEY is required for Gemini embeddings` from eager global `EmbeddingManager()` construction during `neos.main` import.

- Whitespace:
  - `git diff --check`
  - Result: exit **0**.

## Known concerns

- `neos.main` imports successfully once `GOOGLE_API_KEY` is set, which confirms the reviewed scheduled-task import failure is fixed.
- With `GOOGLE_API_KEY` unset, `neos.main` still fails before route registration because embeddings are eagerly initialized and the configured Gemini provider requires the key. I left this as a concern rather than changing embedding-provider semantics because it is outside the Task 7 review findings and would alter application startup behavior for misconfigured embedding providers.
- Test runs emit existing database initialization warnings/errors under the restricted local sandbox (`Operation not permitted`) during fixture setup/teardown, but the impacted authorization suites pass.

## Re-review critical fix

### Findings addressed

1. **Async research start conversation ownership**
   - `start_async_research` now validates a supplied `conversation_id` with `get_owned_conversation` before recording cache state or dispatching Celery work.
   - Missing or foreign conversations return 404, and the workflow uses only `current_user.user_id`.

2. **Async research SSE first-claim gap**
   - Async research start now records `async_research_session_owner:{session_id}` with the same TTL as the job owner record.
   - `stream_research_progress` checks that cached start-owner before `stream_manager.claim_session()` or buffer reads. Missing/foreign stream resources return 404.

3. **Production WebSocket exposure**
   - `neos.main` now includes router WebSocket routes only when `DEBUG=true`.
   - In production (`DEBUG=false`), routers are included through an HTTP-only filtered router so unauthenticated query/workflow/chat WebSocket routes are not in the production route graph.

### Files changed

- `neos/api/handlers/async_research_handlers.py`
- `neos/main.py`
- `tests/api/handlers/test_query_authorization.py`
- `tests/api/handlers/test_research_authorization.py`
- `.superpowers/sdd/task-7-fix-report.md`

### Verification

- RED async/session tests:
  - `env GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-only-secret-key-for-tests DEBUG=false .venv/bin/pytest -q tests/api/handlers/test_research_authorization.py::test_async_research_start_hides_missing_and_foreign_conversation_before_dispatch tests/api/handlers/test_research_authorization.py::test_async_stream_hides_missing_and_foreign_start_owner_before_claim tests/api/handlers/test_query_authorization.py::test_production_app_excludes_websocket_routes_when_debug_false`
  - Result before implementation and before correcting the wrapped-router WebSocket helper: **4 failed, 1 passed**. Async research tests failed for the expected missing authorization checks; the first WebSocket assertion missed `_IncludedRouter.original_router`.

- RED corrected production WebSocket test:
  - `env GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-only-secret-key-for-tests DEBUG=false .venv/bin/pytest -q tests/api/handlers/test_query_authorization.py::test_production_app_excludes_websocket_routes_when_debug_false`
  - Result before implementation after fixing the test helper: **1 failed**, showing `/api/v1/ws/{session_id}`, `/api/v1/ws/query/{session_id}`, `/api/v1/ws/query/detailed/{session_id}`, and `/api/v1/chat/ws/{conversation_id}` were still present.

- GREEN targeted re-review tests:
  - `env GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-only-secret-key-for-tests DEBUG=false .venv/bin/pytest -q tests/api/handlers/test_research_authorization.py::test_async_research_start_records_job_owner tests/api/handlers/test_research_authorization.py::test_async_research_start_hides_missing_and_foreign_conversation_before_dispatch tests/api/handlers/test_research_authorization.py::test_async_stream_hides_missing_and_foreign_start_owner_before_claim tests/api/handlers/test_research_authorization.py::test_async_stream_rejects_foreign_claim_before_response_or_buffer tests/api/handlers/test_query_authorization.py::test_production_app_excludes_websocket_routes_when_debug_false`
  - Result: **7 passed, 49 warnings**.

- Impacted Task 7 suites:
  - `env GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-only-secret-key-for-tests DEBUG=false .venv/bin/pytest -q tests/api/handlers/test_query_authorization.py tests/api/handlers/test_alternate_query_authorization.py tests/api/handlers/test_research_authorization.py tests/api/handlers/test_similarity_chat_authorization.py tests/api/handlers/test_scheduled_tasks_session_context.py tests/workflow/test_stream_manager_authorization.py tests/api/handlers/test_query_handlers_autonomy.py`
  - Result: **109 passed, 49 warnings**.

- Whitespace:
  - `git diff --check`
  - Result: exit **0**.

### Known concerns

- Test runs still emit existing database initialization warnings/errors under the restricted local sandbox (`Operation not permitted`) during fixture setup/teardown, but all impacted authorization suites pass.

## Second re-review critical fix

### Findings addressed

1. **Async research start `session_id` fallback**
   - `start_async_research` now always generates the async research stream/session ID server-side.
   - Caller-supplied `session_id` remains accepted by the request model for response-schema/path compatibility, but it is ignored for the workflow `conversation_id` fallback, stream owner cache key, returned `session_id`, and returned `stream_url`.

2. **Async research owner overwrite via duplicate supplied `session_id`**
   - Because start requests no longer use caller-supplied `session_id`, a second caller cannot overwrite `async_research_session_owner:{known_session}` through the start route.
   - Added regression coverage that a foreign caller starting with a known session ID receives a server-generated session, leaves the existing owner cache record unchanged, and still gets 404 before stream claim/buffer reads for the known session.

### Files changed

- `neos/api/handlers/async_research_handlers.py`
- `tests/api/handlers/test_research_authorization.py`
- `.superpowers/sdd/task-7-fix-report.md`

### Verification

- RED async supplied-session tests:
  - `env GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-only-secret-key-for-tests DEBUG=false .venv/bin/pytest -q tests/api/handlers/test_research_authorization.py::test_async_research_start_records_job_owner tests/api/handlers/test_research_authorization.py::test_async_research_start_ignores_supplied_session_id_for_workflow_conversation tests/api/handlers/test_research_authorization.py::test_async_research_start_does_not_overwrite_supplied_foreign_session_owner_or_enable_first_claim`
  - Result before implementation: **2 failed, 1 passed**. Failures confirmed supplied `session_id` was returned/used instead of a server-generated session.

- GREEN targeted supplied-session tests:
  - `env GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-only-secret-key-for-tests DEBUG=false .venv/bin/pytest -q tests/api/handlers/test_research_authorization.py::test_async_research_start_records_job_owner tests/api/handlers/test_research_authorization.py::test_async_research_start_ignores_supplied_session_id_for_workflow_conversation tests/api/handlers/test_research_authorization.py::test_async_research_start_does_not_overwrite_supplied_foreign_session_owner_or_enable_first_claim`
  - Result: **3 passed, 1 warning**.

- Research authorization suite:
  - `env GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-only-secret-key-for-tests DEBUG=false .venv/bin/pytest -q tests/api/handlers/test_research_authorization.py`
  - Result: **23 passed, 1 warning**.

- Impacted Task 7 suites:
  - `env GOOGLE_API_KEY=test-key JWT_SECRET_KEY=test-only-secret-key-for-tests DEBUG=false .venv/bin/pytest -q tests/api/handlers/test_query_authorization.py tests/api/handlers/test_alternate_query_authorization.py tests/api/handlers/test_research_authorization.py tests/api/handlers/test_similarity_chat_authorization.py tests/api/handlers/test_scheduled_tasks_session_context.py tests/workflow/test_stream_manager_authorization.py tests/api/handlers/test_query_handlers_autonomy.py`
  - Result: **111 passed, 49 warnings**.

- Whitespace:
  - `git diff --check`
  - Result before and after report update: exit **0**.

### Known concerns

- Test runs still emit existing database initialization warnings/errors under the restricted local sandbox (`Operation not permitted`) during fixture setup/teardown, but all impacted authorization suites pass.

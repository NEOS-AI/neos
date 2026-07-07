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

# NEOS HTTP Resource Authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce authenticated, owner-scoped access for NEOS HTTP chat, document, approval, UI-frame, query, and workflow-stream resources without trusting caller-supplied user IDs.

**Architecture:** Add reusable FastAPI resource-access dependencies that resolve the authenticated active user and return 404 for missing or unauthorized resources. Apply those dependencies at every HTTP handler boundary, derive all user IDs from the authenticated principal, and add a second ownership check at approval/UI-frame persistence boundaries. Preserve existing HTTP paths and public health/trending/related-query reads; route renaming, authenticated WebSockets, durable Research Runs, and share tokens remain separate sub-projects.

**Tech Stack:** Python 3.12, FastAPI 0.138+, Pydantic 2, SQLAlchemy 2, asyncpg, pytest 9, pytest-asyncio

## Global Constraints

- The authenticated identity is always `current_user.user_id`; request body, form, query, and path `user_id` values never grant authority.
- Missing and unauthorized private resources both return HTTP 404 to avoid resource enumeration.
- Conversation mutation requires ownership. Authenticated read access may continue for `visibility == "public"` until the share-token sub-project replaces ID-based public reads.
- Document, message, approval, UI-frame, query-history, and stream-session access is owner-only.
- Existing HTTP paths and response schemas remain compatible in this plan.
- Existing `user_id` request fields become deprecated optional compatibility fields and are ignored for authorization.
- No database migration is required: `documents.user_id`, `pending_approvals.user_id`, `ui_frame_sessions.user_id`, and conversation ownership already exist.
- Health, trending queries, and related-query reads remain public. Cache deletion, system stats, `/metrics`, and `/info` require an administrator.
- Unauthenticated WebSocket removal or replacement with short-lived authenticated tickets is a separate blocking security plan; do not enable the current WebSocket routes in production after this plan.
- Every behavior change is introduced test-first and committed independently.

---

## File Structure

### New files

- `neos/api/dependencies/resource_access.py` — reusable owner/read access dependencies and caller-user compatibility validation.
- `tests/api/dependencies/test_resource_access.py` — unit tests for conversation, message, document, and path-user authorization.
- `tests/api/handlers/test_chat_authorization.py` — handler identity and dependency audit tests for chat HTTP routes.
- `tests/api/handlers/test_document_authorization.py` — document handler identity and scope tests.
- `tests/api/handlers/test_approval_authorization.py` — pending approval and stream session ownership tests.
- `tests/api/handlers/test_ui_submit_authorization.py` — UI-frame owner filtering and atomic submit tests.
- `tests/api/handlers/test_query_authorization.py` — query, query-history, SSE session, and admin endpoint tests.

### Modified files

- `neos/api/dependencies/__init__.py` — export resource-access dependencies.
- `neos/api/models/chat_models.py` — deprecate caller-supplied identity fields.
- `neos/api/models/document_models.py` — deprecate document-search caller identity.
- `neos/api/models/query_models.py` — deprecate query and stream caller identity.
- `neos/api/handlers/chat_handlers.py` — require active-user and resource dependencies across chat HTTP routes.
- `neos/api/services/chat_stream_pipeline.py` — assert the already-authorized conversation owner before the first message write.
- `neos/api/handlers/document_handlers.py` — authenticate and scope all document operations.
- `neos/api/services/document_service.py` — add owner-scoped document lookup and deletion interfaces.
- `neos/api/handlers/approval_handlers.py` — scope pending approval lookup, resolution, and resume streams by user.
- `neos/api/handlers/ui_submit_handlers.py` — scope frame lookup and atomic update by user.
- `neos/api/handlers/query_handlers.py` — derive workflow/history identity from the principal and protect admin operations.
- `neos/api/handlers/workflow_stream_handlers.py` — authenticate SSE execution and reject cross-user session reuse.
- `neos/main.py` — protect `/metrics`, `/api/v1/metrics/stats`, and `/info` with admin authentication.
- `docs/NEOS_WORKFLOW.md` — document authenticated HTTP ownership behavior and the WebSocket follow-up constraint.

## Shared Interfaces

The following names and signatures are fixed for all tasks. Task 1 contains their complete implementations.

- `get_owned_conversation(conversation_id: str, current_user: User) -> dict[str, Any]`
- `get_readable_conversation(conversation_id: str, current_user: User) -> dict[str, Any]`
- `get_owned_message(message_id: str, current_user: User) -> dict[str, Any]`
- `get_owned_document(document_id: int, current_user: User) -> Document`
- `require_same_user_id(requested_user_id: str, current_user: User) -> None`
- `require_stream_session_owner(session: StreamSession, current_user: User) -> None`

All resource helpers raise:

```python
raise HTTPException(status_code=404, detail="Resource not found")
```

for both absence and owner mismatch. `require_same_user_id` also uses 404 so user-scoped collection paths do not reveal whether another user exists.

---

### Task 1: Resource Access Dependencies

**Files:**
- Create: `neos/api/dependencies/resource_access.py`
- Modify: `neos/api/dependencies/__init__.py`
- Create: `tests/api/dependencies/test_resource_access.py`

**Interfaces:**
- Consumes: `get_current_active_user`, `ChatService.get_conversation()`, `ChatService.get_message()`, `DocumentService.get_document_by_id()`, `StreamSession.user_id`.
- Produces: all six shared interfaces defined above.

- [ ] **Step 1: Write failing owner/read-access tests**

Create `tests/api/dependencies/test_resource_access.py` with tests covering owner success, public conversation read, private cross-user denial, message-to-conversation ownership, document ownership, same-user path validation, and stream-session ownership:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from neos.api.dependencies import resource_access


@pytest.fixture
def owner():
    return SimpleNamespace(user_id="user-a", is_active=True)


@pytest.mark.asyncio
async def test_owned_conversation_returns_owner_resource(monkeypatch, owner):
    conversation = {"conversation_id": "c1", "user_id": "user-a", "visibility": "private"}
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(return_value=conversation),
    )
    assert await resource_access.get_owned_conversation("c1", owner) == conversation


@pytest.mark.asyncio
async def test_owned_conversation_hides_cross_user_resource(monkeypatch, owner):
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(return_value={"conversation_id": "c1", "user_id": "user-b", "visibility": "private"}),
    )
    with pytest.raises(HTTPException) as exc:
        await resource_access.get_owned_conversation("c1", owner)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_readable_conversation_allows_authenticated_public_read(monkeypatch, owner):
    conversation = {"conversation_id": "c1", "user_id": "user-b", "visibility": "public"}
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(return_value=conversation),
    )
    assert await resource_access.get_readable_conversation("c1", owner) == conversation


@pytest.mark.asyncio
async def test_owned_message_checks_parent_conversation(monkeypatch, owner):
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_message",
        AsyncMock(return_value={"message_id": "m1", "conversation_id": "c1"}),
    )
    monkeypatch.setattr(
        resource_access.ChatService,
        "get_conversation",
        AsyncMock(return_value={"conversation_id": "c1", "user_id": "user-b", "visibility": "private"}),
    )
    with pytest.raises(HTTPException) as exc:
        await resource_access.get_owned_message("m1", owner)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_owned_document_checks_document_user(monkeypatch, owner):
    monkeypatch.setattr(
        resource_access.DocumentService,
        "get_document_by_id",
        AsyncMock(return_value=SimpleNamespace(id=7, user_id="user-b")),
    )
    with pytest.raises(HTTPException) as exc:
        await resource_access.get_owned_document(7, owner)
    assert exc.value.status_code == 404


def test_same_user_path_and_stream_session_are_scoped(owner):
    resource_access.require_same_user_id("user-a", owner)
    resource_access.require_stream_session_owner(
        SimpleNamespace(user_id="user-a"), owner
    )
    with pytest.raises(HTTPException):
        resource_access.require_same_user_id("user-b", owner)
    with pytest.raises(HTTPException):
        resource_access.require_stream_session_owner(
            SimpleNamespace(user_id="user-b"), owner
        )
```

- [ ] **Step 2: Run tests and verify the module is missing**

Run:

```bash
pytest -q tests/api/dependencies/test_resource_access.py
```

Expected: collection fails with `ImportError` for `resource_access`.

- [ ] **Step 3: Implement the resource dependencies**

Create `neos/api/dependencies/resource_access.py`:

```python
from typing import Any

from fastapi import Depends, HTTPException, status

from neos.api.dependencies.auth import get_current_active_user
from neos.api.services.chat_service import ChatService
from neos.api.services.document_service import DocumentService
from neos.database.models import Document, User
from neos.workflow.stream_manager import StreamSession


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Resource not found",
    )


async def get_owned_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    conversation = await ChatService.get_conversation(conversation_id)
    if not conversation or conversation.get("user_id") != current_user.user_id:
        raise _not_found()
    return conversation


async def get_readable_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    conversation = await ChatService.get_conversation(conversation_id)
    if not conversation:
        raise _not_found()
    is_owner = conversation.get("user_id") == current_user.user_id
    is_public = conversation.get("visibility") == "public"
    if not (is_owner or is_public):
        raise _not_found()
    return conversation


async def get_owned_message(
    message_id: str,
    current_user: User = Depends(get_current_active_user),
) -> dict[str, Any]:
    message = await ChatService.get_message(message_id)
    if not message:
        raise _not_found()
    conversation = await ChatService.get_conversation(message["conversation_id"])
    if not conversation or conversation.get("user_id") != current_user.user_id:
        raise _not_found()
    return message


async def get_owned_document(
    document_id: int,
    current_user: User = Depends(get_current_active_user),
) -> Document:
    document = await DocumentService.get_document_by_id(document_id)
    if not document or document.user_id != current_user.user_id:
        raise _not_found()
    return document


def require_same_user_id(requested_user_id: str, current_user: User) -> None:
    if requested_user_id != current_user.user_id:
        raise _not_found()


def require_stream_session_owner(session: StreamSession, current_user: User) -> None:
    if not session.user_id or session.user_id != current_user.user_id:
        raise _not_found()
```

Export the six public names from `neos/api/dependencies/__init__.py`.

- [ ] **Step 4: Run the dependency tests**

Run:

```bash
pytest -q tests/api/dependencies/test_resource_access.py
```

Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add neos/api/dependencies/resource_access.py neos/api/dependencies/__init__.py tests/api/dependencies/test_resource_access.py
git commit -m "security: add resource ownership dependencies"
```

---

### Task 2: Chat Conversation HTTP Authorization

**Files:**
- Modify: `neos/api/models/chat_models.py:47-68`
- Modify: `neos/api/handlers/chat_handlers.py:149-376`
- Create: `tests/api/handlers/test_chat_authorization.py`

**Interfaces:**
- Consumes: `get_owned_conversation`, `get_readable_conversation`, `require_same_user_id` from Task 1.
- Produces: authenticated conversation create/read/update/delete/archive/list/title/count behavior for Task 3 and the current Next.js BFF.

- [ ] **Step 1: Write failing identity and route dependency tests**

Create `tests/api/handlers/test_chat_authorization.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute

from neos.api.handlers import chat_handlers
from neos.api.models.chat_models import CreateConversationRequest


@pytest.mark.asyncio
async def test_create_conversation_uses_authenticated_user(monkeypatch):
    create = AsyncMock(return_value={
        "conversation_id": "c1",
        "user_id": "owner",
        "title": "New chat",
        "summary": None,
        "model_name": "claude-sonnet-4-5-20250929",
        "model_version": None,
        "system_prompt": None,
        "temperature": 0.7,
        "max_tokens": None,
        "mode": "standard",
        "status": "active",
        "is_pinned": False,
        "is_shared": False,
        "share_token": None,
        "visibility": "private",
        "message_count": 0,
        "total_tokens_used": 0,
        "total_cost": 0.0,
        "last_message_at": None,
        "last_accessed_at": None,
        "created_at": "2026-07-01T00:00:00",
        "updated_at": "2026-07-01T00:00:00",
        "tags": [],
        "metadata": {},
    })
    monkeypatch.setattr(chat_handlers.ChatService, "create_conversation", create)
    request = CreateConversationRequest(user_id="attacker", conversation_id="c1")

    await chat_handlers.create_conversation(
        request,
        current_user=SimpleNamespace(user_id="owner", is_active=True),
    )

    assert create.await_args.kwargs["user_id"] == "owner"


def test_conversation_routes_declare_access_dependencies():
    expected = {
        ("/conversations/{conversation_id}", "GET"): "get_readable_conversation",
        ("/conversations/{conversation_id}/full", "GET"): "get_readable_conversation",
        ("/conversations/{conversation_id}", "PATCH"): "get_owned_conversation",
        ("/conversations/{conversation_id}", "DELETE"): "get_owned_conversation",
        ("/conversations/{conversation_id}/archive", "POST"): "get_owned_conversation",
        ("/conversations/{conversation_id}/generate-title", "POST"): "get_owned_conversation",
    }
    routes = [route for route in chat_handlers.router.routes if isinstance(route, APIRoute)]
    for (path, method), dependency_name in expected.items():
        route = next(r for r in routes if r.path == path and method in r.methods)
        names = {dependency.call.__name__ for dependency in route.dependant.dependencies}
        assert dependency_name in names
```

- [ ] **Step 2: Run the tests and confirm identity spoofing or missing dependencies**

Run:

```bash
pytest -q tests/api/handlers/test_chat_authorization.py
```

Expected: failure because `create_conversation` has no `current_user` argument and conversation routes lack access dependencies.

- [ ] **Step 3: Deprecate the request identity field**

Change `CreateConversationRequest.user_id` to:

```python
user_id: Optional[str] = Field(
    default=None,
    deprecated=True,
    description="Deprecated compatibility field; authenticated identity is used",
)
```

Do not use this field in handlers.

- [ ] **Step 4: Apply authentication and access dependencies to conversation routes**

Import:

```python
from neos.api.dependencies.auth import get_current_active_user
from neos.api.dependencies.resource_access import (
    get_owned_conversation,
    get_readable_conversation,
    require_same_user_id,
)
```

Use these exact rules:

| Handler | Principal/access rule |
| --- | --- |
| `create_conversation` | `current_user: User = Depends(get_current_active_user)`; pass `current_user.user_id` |
| `get_conversation` | `_conversation = Depends(get_readable_conversation)` |
| `get_conversation_with_messages` | `_conversation = Depends(get_readable_conversation)` |
| `update_conversation` | `_conversation = Depends(get_owned_conversation)` |
| `delete_conversation` | `_conversation = Depends(get_owned_conversation)` |
| `archive_conversation` | `_conversation = Depends(get_owned_conversation)` |
| `generate_conversation_title` | `_conversation = Depends(get_owned_conversation)` |
| `delete_messages_after_timestamp` | `_conversation = Depends(get_owned_conversation)` |
| `list_user_conversations` | active user + `require_same_user_id(user_id, current_user)` |
| `delete_all_user_conversations` | active user + `require_same_user_id(user_id, current_user)` |
| `get_user_message_count` | active user + `require_same_user_id(user_id, current_user)` |
| `get_user_statistics` | active user + `require_same_user_id(user_id, current_user)` |

The create handler must call:

```python
conversation = await ChatService.create_conversation(
    user_id=current_user.user_id,
    conversation_id=request.conversation_id,
    model_name=request.model_name,
    title=request.title,
    system_prompt=request.system_prompt,
    temperature=request.temperature,
    max_tokens=request.max_tokens,
    mode=request.mode.value if hasattr(request.mode, "value") else request.mode,
    template_id=request.template_id,
    visibility=request.visibility,
    metadata=request.metadata,
)
```

Do not return 403 for ownership mismatch; the Task 1 dependency returns 404.

- [ ] **Step 5: Run chat authorization and existing chat service tests**

Run:

```bash
pytest -q tests/api/handlers/test_chat_authorization.py tests/test_chat_service.py
```

Expected: authorization tests pass. If the existing stale `MagicMock` create test still fails, replace that test's awaited repository mocks with `AsyncMock`; do not weaken production awaits.

- [ ] **Step 6: Commit**

```bash
git add neos/api/models/chat_models.py neos/api/handlers/chat_handlers.py tests/api/handlers/test_chat_authorization.py tests/test_chat_service.py
git commit -m "security: scope conversation routes to users"
```

---

### Task 3: Chat Message and Stream Authorization

**Files:**
- Modify: `neos/api/models/chat_models.py:71-109`
- Modify: `neos/api/handlers/chat_handlers.py:378-680`
- Modify: `neos/api/services/chat_stream_pipeline.py:72-130`
- Modify: `tests/api/handlers/test_chat_authorization.py`
- Modify: `tests/api/services/test_chat_stream_pipeline_autonomy.py`

**Interfaces:**
- Consumes: readable/owned conversation and owned-message dependencies from Task 1.
- Produces: owner-scoped message mutations and authenticated public/owner reads; the stream pipeline receives an authorized conversation.

- [ ] **Step 1: Add failing message route and stream-owner tests**

Append a route audit to `test_chat_authorization.py` asserting these dependencies:

```python
def test_message_routes_declare_access_dependencies():
    expected = {
        ("/conversations/{conversation_id}/messages", "POST"): "get_owned_conversation",
        ("/conversations/{conversation_id}/messages", "GET"): "get_readable_conversation",
        ("/messages/{message_id}", "GET"): "get_owned_message",
        ("/messages/{message_id}", "PATCH"): "get_owned_message",
        ("/messages/{message_id}/feedback", "POST"): "get_owned_message",
        ("/messages/{message_id}", "DELETE"): "get_owned_message",
        ("/messages/{message_id}/regenerate", "POST"): "get_owned_message",
        ("/conversations/{conversation_id}/messages/stream", "POST"): "get_owned_conversation",
    }
    routes = [route for route in chat_handlers.router.routes if isinstance(route, APIRoute)]
    for (path, method), dependency_name in expected.items():
        route = next(r for r in routes if r.path == path and method in r.methods)
        names = {dependency.call.__name__ for dependency in route.dependant.dependencies}
        assert dependency_name in names
```

Add a pipeline test proving no write occurs when the authorized conversation does not match the principal:

```python
@pytest.mark.asyncio
async def test_chat_pipeline_rejects_conversation_owner_mismatch():
    _FakeChatService.messages = []
    pipeline = ChatStreamPipeline(
        chat_llm_service=object(),
        cost_calculator=object(),
        get_core_tools_fn=lambda: None,
        get_search_handler_fn=lambda: None,
        chat_service_cls=_FakeChatService,
        multi_agent_workflow=object(),
        workflow_callback_cls=object(),
        map_node_to_agent_fn=lambda node: node,
    )
    request = SimpleNamespace(
        role=SimpleNamespace(value="user"),
        content="secret",
        attachments=[],
        parent_message_id=None,
        metadata={},
    )
    chunks = [
        chunk
        async for chunk in pipeline.run(
            "conversation_123",
            request,
            SimpleNamespace(user_id="attacker"),
            authorized_conversation={"conversation_id": "conversation_123", "user_id": "owner"},
        )
    ]
    assert _FakeChatService.messages == []
    assert any("response.failed" in chunk for chunk in chunks)
```

- [ ] **Step 2: Run tests and verify failures**

Run:

```bash
pytest -q tests/api/handlers/test_chat_authorization.py tests/api/services/test_chat_stream_pipeline_autonomy.py
```

Expected: missing message dependencies and missing `authorized_conversation` argument failures.

- [ ] **Step 3: Remove spoofable edit identity and apply message dependencies**

Change `EditMessageRequest.user_id` to a deprecated optional compatibility field and use `current_user.user_id` as `edited_by`.

Apply exact access rules:

| Handler | Access |
| --- | --- |
| `send_message` | owned conversation |
| `get_conversation_messages` | readable conversation |
| `get_message` | owned message |
| `edit_message` | owned message + active current user |
| `add_message_feedback` | owned message |
| `delete_message` | owned message |
| `regenerate_message` | owned message |
| `stream_message` | owned conversation + current active user |
| `stream_message_legacy` | owned conversation + current active user while deprecated route remains |

Pass the dependency result into the stream pipeline:

```python
@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: User = Depends(get_current_active_user),
    authorized_conversation: dict = Depends(get_owned_conversation),
):
    pipeline = _get_chat_stream_pipeline()
    return StreamingResponse(
        pipeline.run(
            conversation_id,
            request,
            current_user,
            authorized_conversation=authorized_conversation,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-OpenResponses-Version": OPEN_RESPONSES_VERSION,
        },
    )
```

- [ ] **Step 4: Add a defense-in-depth stream pipeline check**

Change the pipeline signature and perform the check before `ChatService.add_message()`:

```python
async def run(
    self,
    conversation_id: str,
    request,
    current_user,
    *,
    authorized_conversation: dict[str, Any],
) -> AsyncGenerator[str, None]:
    acc = StreamAccumulator()
    stream_state: Optional[StreamAdapterState] = None
    if (
        authorized_conversation.get("conversation_id") != conversation_id
        or authorized_conversation.get("user_id") != current_user.user_id
    ):
        logger.warning("Rejected chat stream owner mismatch")
        state, _ = create_stream_generator(
            response_id=conversation_id,
            message_id=str(uuid.uuid4()),
        )
        state.response.status = ResponseStatus.FAILED
        state.response.error = ErrorInfo(
            type="not_found",
            message="Resource not found",
        )
        yield format_sse_event(ResponseFailedEvent(response=state.response))
        yield format_done_token()
        return
```

Use `authorized_conversation` instead of reloading the conversation in Step 3 of the pipeline. Update existing pipeline tests to pass the fake conversation explicitly.

- [ ] **Step 5: Run message/stream tests**

Run:

```bash
pytest -q tests/api/handlers/test_chat_authorization.py tests/api/services/test_chat_stream_pipeline_autonomy.py
```

Expected: all tests pass and owner mismatch produces no message write.

- [ ] **Step 6: Commit**

```bash
git add neos/api/models/chat_models.py neos/api/handlers/chat_handlers.py neos/api/services/chat_stream_pipeline.py tests/api/handlers/test_chat_authorization.py tests/api/services/test_chat_stream_pipeline_autonomy.py
git commit -m "security: protect chat messages and streams"
```

---

### Task 4: Document HTTP Authorization

**Files:**
- Modify: `neos/api/models/document_models.py:74-80`
- Modify: `neos/api/services/document_service.py:20-220`
- Modify: `neos/api/handlers/document_handlers.py:32-270`
- Create: `tests/api/handlers/test_document_authorization.py`

**Interfaces:**
- Consumes: `get_owned_document` and active current user.
- Produces: owner-scoped upload, list, detail, delete, chunk, knowledge-graph, and semantic search.

- [ ] **Step 1: Write failing document identity tests**

Create `tests/api/handlers/test_document_authorization.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from neos.api.handlers import document_handlers
from neos.api.models.document_models import DocumentSearchRequest
from neos.api.services.document_service import DocumentProcessor, DocumentService


@pytest.mark.asyncio
async def test_document_search_uses_authenticated_user(monkeypatch):
    search = AsyncMock(return_value=[])
    monkeypatch.setattr(document_handlers.DocumentService, "search_documents", search)
    await document_handlers.search_documents(
        DocumentSearchRequest(query="private", user_id="attacker"),
        current_user=SimpleNamespace(user_id="owner", is_active=True),
    )
    assert search.await_args.kwargs["user_id"] == "owner"


@pytest.mark.asyncio
async def test_document_list_uses_authenticated_user(monkeypatch):
    list_documents = AsyncMock(return_value={"total": 0, "documents": []})
    monkeypatch.setattr(
        document_handlers.DocumentService,
        "list_documents",
        list_documents,
    )
    await document_handlers.list_documents(
        status=None,
        skip=0,
        limit=100,
        current_user=SimpleNamespace(user_id="owner", is_active=True),
    )
    assert list_documents.await_args.args[0] == "owner"
```

Add a service test proving delete is owner scoped:

```python
@pytest.mark.asyncio
async def test_delete_document_for_user_requires_owned_lookup(monkeypatch):
    lookup = AsyncMock(return_value=None)
    processor_delete = AsyncMock(return_value=True)
    monkeypatch.setattr(
        DocumentService,
        "get_document_for_user",
        lookup,
    )
    monkeypatch.setattr(DocumentProcessor, "delete_document", processor_delete)
    assert await DocumentService.delete_document_for_user(7, "owner") is False
    processor_delete.assert_not_awaited()
```

- [ ] **Step 2: Run tests and verify caller identity is trusted today**

Run:

```bash
pytest -q tests/api/handlers/test_document_authorization.py
```

Expected: handler signature failures and missing scoped service methods.

- [ ] **Step 3: Add owner-scoped document service methods**

Add to `DocumentService`:

```python
@staticmethod
async def get_document_for_user(document_id: int, user_id: str) -> Optional[Document]:
    async with db_manager.get_session() as session:
        result = await session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()


@staticmethod
async def delete_document_for_user(document_id: int, user_id: str) -> bool:
    document = await DocumentService.get_document_for_user(document_id, user_id)
    if not document:
        return False
    processor = DocumentProcessor()
    return await processor.delete_document(document_id)
```

Keep the old unscoped methods for internal compatibility but do not call them from HTTP mutation handlers.

- [ ] **Step 4: Authenticate and scope every document handler**

Use `current_user: User = Depends(get_current_active_user)` on upload, list, and search. Use `owned_document: Document = Depends(get_owned_document)` on detail, delete, chunks, and knowledge graph.

Exact identity behavior:

```python
# upload
document = await DocumentService.upload_and_process_document(
    file_content=file_content,
    filename=file.filename,
    user_id=current_user.user_id,
    metadata=metadata_dict,
    mime_type=file.content_type,
)

# list
result = await DocumentService.list_documents(
    current_user.user_id,
    status,
    skip,
    limit,
)

# search
results = await DocumentService.search_documents(
    query=request.query,
    top_k=request.top_k,
    user_id=current_user.user_id,
)

# delete
success = await DocumentService.delete_document_for_user(
    owned_document.id,
    current_user.user_id,
)
```

For chunks and knowledge graph, use `owned_document.id` rather than trusting the path value after dependency resolution.

Change `DocumentSearchRequest.user_id` to an optional deprecated compatibility field. Keep upload form `user_id` optional for compatibility, but never use it.

- [ ] **Step 5: Run document and resource dependency tests**

Run:

```bash
pytest -q tests/api/handlers/test_document_authorization.py tests/api/dependencies/test_resource_access.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add neos/api/models/document_models.py neos/api/services/document_service.py neos/api/handlers/document_handlers.py tests/api/handlers/test_document_authorization.py
git commit -m "security: scope document APIs to owners"
```

---

### Task 5: Approval Ownership

**Files:**
- Modify: `neos/api/handlers/approval_handlers.py:70-300`
- Create: `tests/api/handlers/test_approval_authorization.py`

**Interfaces:**
- Consumes: `pending_approvals.user_id`, `StreamSession.user_id`, `require_stream_session_owner`.
- Produces: user-scoped approval validation, resolution, allowlisting, and resume stream access.

- [ ] **Step 1: Write failing pending-approval and stream ownership tests**

Create `tests/api/handlers/test_approval_authorization.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from neos.api.handlers import approval_handlers


@pytest.mark.asyncio
async def test_pending_approval_lookup_is_scoped_to_user(monkeypatch):
    fetch_one = AsyncMock(return_value=None)
    monkeypatch.setattr(approval_handlers.db_manager, "fetch_one", fetch_one)
    with pytest.raises(HTTPException) as exc:
        await approval_handlers._require_pending_approval_owner(
            session_id="s1",
            request_id="r1",
            user_id="user-a",
        )
    assert exc.value.status_code == 404
    assert "user_id = $3" in fetch_one.await_args.args[0]


@pytest.mark.asyncio
async def test_resume_stream_hides_other_users_session(monkeypatch):
    monkeypatch.setattr(
        approval_handlers.stream_manager,
        "get_session",
        lambda _session_id: SimpleNamespace(user_id="user-b"),
    )
    with pytest.raises(HTTPException) as exc:
        await approval_handlers.stream_resume_result(
            "s1",
            current_user=SimpleNamespace(user_id="user-a"),
        )
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Run tests and verify missing ownership functions**

Run:

```bash
pytest -q tests/api/handlers/test_approval_authorization.py
```

Expected: missing `_require_pending_approval_owner` and cross-user stream failure.

- [ ] **Step 3: Add pending approval owner lookup**

Import `db_manager` at module scope and add:

```python
async def _require_pending_approval_owner(
    session_id: str,
    request_id: str,
    user_id: str,
) -> dict:
    row = await db_manager.fetch_one(
        """
        SELECT request_id, session_id, user_id, skill_name, resolved
        FROM pending_approvals
        WHERE session_id = $1
          AND request_id = $2
          AND user_id = $3
          AND resolved = FALSE
        """,
        session_id,
        request_id,
        user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Resource not found")
    return {
        "request_id": row[0],
        "session_id": row[1],
        "user_id": row[2],
        "skill_name": row[3],
        "resolved": row[4],
    }
```

Call it before `graph.aget_state()`. Validate `skill_name` against this persisted row and the graph pending entry.

- [ ] **Step 4: Scope state mutation, stream sessions, and resolution**

Change `_mark_approval_resolved` to accept `user_id` and execute:

```sql
UPDATE pending_approvals
SET resolved = TRUE
WHERE request_id = $1 AND user_id = $2 AND resolved = FALSE
```

Before reusing an existing stream session:

```python
session = stream_manager.get_session(session_id)
if session:
    require_stream_session_owner(session, current_user)
else:
    stream_manager.create_session(session_id, current_user.user_id)
```

Perform the same check synchronously at the start of `stream_resume_result`, before constructing `StreamingResponse`. This avoids returning HTTP 200 followed by an authorization error event.

- [ ] **Step 5: Run approval tests**

Run:

```bash
pytest -q tests/api/handlers/test_approval_authorization.py tests/api/services/test_chat_stream_pipeline_autonomy.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add neos/api/handlers/approval_handlers.py tests/api/handlers/test_approval_authorization.py
git commit -m "security: scope workflow approvals to owners"
```

---

### Task 6: UI Frame Ownership

**Files:**
- Modify: `neos/api/handlers/ui_submit_handlers.py:48-180`
- Create: `tests/api/handlers/test_ui_submit_authorization.py`

**Interfaces:**
- Consumes: authenticated `current_user.user_id` and `UIFrameSession.user_id`.
- Produces: owner-scoped frame lookup and atomic single submission.

- [ ] **Step 1: Write a failing SQL ownership test**

Create `tests/api/handlers/test_ui_submit_authorization.py` with a fake async session that captures SQLAlchemy statements. Assert that both the initial select and atomic update include `UIFrameSession.user_id == current_user.user_id`:

```python
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from neos.api.handlers import ui_submit_handlers


@pytest.mark.asyncio
async def test_ui_frame_lookup_receives_authenticated_user(monkeypatch):
    captured = {}

    async def fake_get_owned_frame(frame_id, user_id):
        captured.update(frame_id=frame_id, user_id=user_id)
        return None

    monkeypatch.setattr(
        ui_submit_handlers,
        "_get_owned_frame_session",
        fake_get_owned_frame,
    )
    body = SimpleNamespace(
        frame_id="00000000-0000-0000-0000-000000000001",
        session_id="s1",
        values={},
    )
    with pytest.raises(HTTPException) as exc:
        await ui_submit_handlers.submit_ui_frame(
            body,
            current_user=SimpleNamespace(user_id="user-a"),
        )
    assert exc.value.status_code == 404
    assert captured["user_id"] == "user-a"
```

- [ ] **Step 2: Run the test and verify the helper is missing**

Run:

```bash
pytest -q tests/api/handlers/test_ui_submit_authorization.py
```

Expected: missing `_get_owned_frame_session`.

- [ ] **Step 3: Implement owner-scoped lookup and update**

Add:

```python
async def _get_owned_frame_session(frame_id: uuid.UUID, user_id: str):
    async with get_db_session() as db:
        result = await db.execute(
            select(UIFrameSession).where(
                UIFrameSession.frame_id == frame_id,
                UIFrameSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()
```

Use it in `submit_ui_frame`. A missing or cross-user frame returns `HTTPException(404, "Resource not found")`.

Add the same user predicate to the atomic update:

```python
sa_update(UIFrameSession).where(
    UIFrameSession.frame_id == frame_uuid,
    UIFrameSession.user_id == current_user.user_id,
    UIFrameSession.submitted_at.is_(None),
)
```

Before executing the workflow, verify `frame_session.session_id == body.session_id`; mismatch returns 404. Derive workflow `user_id` only from `current_user.user_id`.

- [ ] **Step 4: Run UI frame tests**

Run:

```bash
pytest -q tests/api/handlers/test_ui_submit_authorization.py tests/unit/test_ui_submit_event_generator.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add neos/api/handlers/ui_submit_handlers.py tests/api/handlers/test_ui_submit_authorization.py
git commit -m "security: protect ui frame submissions"
```

---

### Task 7: Query, SSE Session, and Operational Endpoint Authorization

**Files:**
- Modify: `neos/api/models/query_models.py:7-17,129-149`
- Modify: `neos/api/handlers/query_handlers.py:16-180`
- Modify: `neos/api/handlers/workflow_stream_handlers.py:450-602`
- Modify: `neos/main.py:520-700`
- Create: `tests/api/handlers/test_query_authorization.py`
- Modify: `tests/api/handlers/test_query_handlers_autonomy.py`

**Interfaces:**
- Consumes: active user, admin user, `require_same_user_id`, `require_stream_session_owner`.
- Produces: authenticated query execution/history/SSE and administrator-only operational data.

- [ ] **Step 1: Write failing query principal and session tests**

Create `tests/api/handlers/test_query_authorization.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException

from neos.api.handlers import query_handlers, workflow_stream_handlers
from neos.api.models.query_models import QueryRequest, WorkflowStreamRequest


@pytest.mark.asyncio
async def test_process_query_uses_authenticated_user(monkeypatch):
    process = AsyncMock(return_value={
        "success": True,
        "response": "ok",
        "session_id": "s1",
        "metadata": {},
        "execution_time_ms": 1,
        "quality_score": 1.0,
        "errors": [],
    })
    monkeypatch.setattr(query_handlers.QueryService, "get_or_create_user", AsyncMock())
    monkeypatch.setattr(query_handlers.QueryService, "process_query_workflow", process)
    await query_handlers.process_query(
        QueryRequest(query="hello", user_id="attacker", session_id="s1"),
        BackgroundTasks(),
        current_user=SimpleNamespace(user_id="owner", is_active=True),
    )
    assert process.await_args.kwargs["user_id"] == "owner"


@pytest.mark.asyncio
async def test_stream_query_rejects_cross_user_session(monkeypatch):
    monkeypatch.setattr(
        workflow_stream_handlers.stream_manager,
        "get_session",
        lambda _session_id: SimpleNamespace(user_id="user-b"),
    )
    with pytest.raises(HTTPException) as exc:
        await workflow_stream_handlers.stream_query(
            WorkflowStreamRequest(query="hello", session_id="s1"),
            SimpleNamespace(headers={}),
            current_user=SimpleNamespace(user_id="user-a", is_active=True),
        )
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Run tests and verify current handlers trust body identity**

Run:

```bash
pytest -q tests/api/handlers/test_query_authorization.py tests/api/handlers/test_query_handlers_autonomy.py
```

Expected: current handler signatures fail and body `user_id` is used.

- [ ] **Step 3: Authenticate query and user-history handlers**

Change `QueryRequest.user_id` and `WorkflowStreamRequest.user_id` to deprecated optional compatibility fields.

Add `current_user: User = Depends(get_current_active_user)` to `process_query`; use:

```python
user_id = current_user.user_id
session_id = request.session_id or str(uuid.uuid4())
```

Require current user on `/history/{user_id}` and call `require_same_user_id`. Keep `/health`, `/trending`, and `/related/{query_id}` public. Require `get_current_admin_user` on `/cache/{cache_key}` and `/stats/system`.

Update existing autonomy tests to pass `current_user=SimpleNamespace(user_id="user_123")`.

- [ ] **Step 4: Authenticate and scope SSE sessions before returning HTTP 200**

Change the handler signature:

```python
async def stream_query(
    body: WorkflowStreamRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
):
```

Before defining `generate_stream`, perform:

```python
session_id = body.session_id or str(uuid.uuid4())
user_id = current_user.user_id
existing_session = stream_manager.get_session(session_id)
if existing_session:
    require_stream_session_owner(existing_session, current_user)
```

Inside the generator, create a session only when one does not exist. Remove the endpoint-specific `Access-Control-Allow-Origin: *` header and rely on the application CORS policy.

- [ ] **Step 5: Protect operational endpoints**

Add `current_user: User = Depends(get_current_admin_user)` to:

- `metrics_endpoint`
- `metrics_stats`
- `system_info`

Do not add auth to `/` or `/api/v1/health`. Remove sensitive model/timeouts/provider details from the public root response; root should retain only name, version, status, health path, and docs path when debug is enabled.

- [ ] **Step 6: Run query and configuration tests**

Run:

```bash
pytest -q tests/api/handlers/test_query_authorization.py tests/api/handlers/test_query_handlers_autonomy.py tests/test_auth_api.py tests/config
```

Expected: all authorization assertions pass. Tests requiring local DB services may be reported separately if the environment cannot start them; missing Python dependencies are not an acceptable pass condition.

- [ ] **Step 7: Commit**

```bash
git add neos/api/models/query_models.py neos/api/handlers/query_handlers.py neos/api/handlers/workflow_stream_handlers.py neos/main.py tests/api/handlers/test_query_authorization.py tests/api/handlers/test_query_handlers_autonomy.py
git commit -m "security: authenticate query and operations APIs"
```

---

### Task 8: Security Regression Matrix and Documentation

**Files:**
- Modify: `docs/NEOS_WORKFLOW.md`
- Modify: `docs/superpowers/specs/2026-07-01-neos-research-platform-design.md` only if implementation reveals a factual mismatch.
- Test: all files created in Tasks 1-7.

**Interfaces:**
- Consumes: all authenticated HTTP interfaces from Tasks 1-7.
- Produces: documented access matrix and a single reproducible verification command.

- [ ] **Step 1: Add the HTTP access matrix to the workflow documentation**

Document these exact policies:

| Resource | Read | Mutate |
| --- | --- | --- |
| Private conversation | owner | owner |
| Public conversation | authenticated user | owner |
| Message | conversation owner; public list through conversation route only | conversation owner |
| Document/chunk/KG/search | owner | owner |
| Approval/resume stream | owner | owner |
| UI frame | owner | owner, one submission |
| Query/history/SSE | authenticated user/self | authenticated user/self |
| Health/trending/related | public | none |
| Metrics/info/cache/stats | admin | admin |

Also state that current WebSocket endpoints are not covered by this HTTP plan and must remain disabled at the deployment perimeter until the authenticated WebSocket plan is implemented.

- [ ] **Step 2: Run format and placeholder checks**

Run:

```bash
rg -n "TB[D]|TO[D]O|FIXM[E]|implement[ ]later|appropriate[ ]error[ ]handling" docs/NEOS_WORKFLOW.md neos/api/dependencies/resource_access.py tests/api
```

Expected: no newly introduced placeholders.

- [ ] **Step 3: Run the complete targeted security suite**

Run:

```bash
pytest -q \
  tests/api/dependencies/test_resource_access.py \
  tests/api/handlers/test_chat_authorization.py \
  tests/api/handlers/test_document_authorization.py \
  tests/api/handlers/test_approval_authorization.py \
  tests/api/handlers/test_ui_submit_authorization.py \
  tests/api/handlers/test_query_authorization.py \
  tests/api/handlers/test_query_handlers_autonomy.py \
  tests/api/services/test_chat_stream_pipeline_autonomy.py
```

Expected: all targeted tests pass.

- [ ] **Step 4: Run broader backend and frontend static verification**

Run:

```bash
pytest -q tests/test_security.py tests/test_jwt.py tests/test_auth_service.py tests/test_auth_api.py
```

Expected: all tests pass when PostgreSQL and declared dependencies are available.

Run:

```bash
pnpm --dir web exec tsc --noEmit --incremental false
```

Expected: exit code 0 without modifying `web/tsconfig.tsbuildinfo`.

- [ ] **Step 5: Inspect the final route dependency coverage**

Run:

```bash
pytest -q tests/api/handlers -k "authorization or autonomy"
```

Expected: all selected tests pass. Manually compare every HTTP decorator in the touched handler files against the access matrix; public exceptions must be limited to health, trending, related, root, and authentication bootstrap routes.

- [ ] **Step 6: Commit documentation and any test-only corrections**

```bash
git add docs/NEOS_WORKFLOW.md tests/api
git commit -m "docs: record HTTP resource access policy"
```

## Follow-up Plans Required Before Production Hardening Is Complete

This plan intentionally does not absorb the other Stage 0 sub-projects. Create separate plans in this order:

1. `neos-websocket-authentication` — remove unauthenticated WebSocket identity payloads or replace them with short-lived one-time connection tickets.
2. `neos-asset-artifact-route-contract` — replace duplicated `/documents` namespace composition with `/assets` and `/artifacts` plus compatibility adapters.
3. `neos-attachment-document-reference` — preserve `document_id`, readiness, and selected-document scope from upload through research execution.
4. `neos-model-capability-routing` — server capability registry and actual-model audit trail.
5. `neos-durable-stream-state` — idempotent run state, duplicate `[DONE]` removal, reconnect without replay, pagination.
6. `neos-content-part-persistence` — round-trip attachments, reasoning summaries, tools, citations, UI frames, and artifacts.

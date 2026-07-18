# Sidebar Cursor Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the sidebar conversation list re-loading the same page forever by replacing the broken offset-drop with real keyset (cursor) pagination.

**Architecture:** The backend issues an opaque base64 cursor encoding the last row's sort tuple `(is_pinned, last_message_at, created_at, conversation_id)`. The repository does keyset filtering with a `LIMIT n+1` has-more probe, preserving the existing `is_pinned DESC, last_message_at DESC NULLS LAST, created_at DESC` order plus a `conversation_id DESC` unique tiebreaker. The frontend threads the opaque cursor through the `/api/history` route and SWRInfinite key builder — it never inspects the cursor's contents.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy-core text queries (`db_manager`), pytest + pytest-asyncio (backend); Next.js 16 / React 19 / SWR, `tsx --test` node test runner (frontend).

## Global Constraints

- Preserve existing sort semantics exactly: `is_pinned DESC, last_message_at DESC NULLS LAST, created_at DESC`, with `conversation_id DESC` appended only as a deterministic tiebreaker.
- The cursor is **opaque to the frontend**. Only backend `pagination.py` encodes/decodes it.
- NULL `last_message_at` sentinel is Python `datetime.min` (`0001-01-01 00:00:00`) bound as a real parameter — never the SQL literal `'-infinity'` (asyncpg/SQLAlchemy cannot encode it into a TIMESTAMP param).
- `offset` parameter stays for backward compatibility; when `cursor` is present, `offset` is ignored.
- Column types: `last_message_at`, `created_at` are `TIMESTAMP` (no tz); `is_pinned` is `BOOLEAN`; `conversation_id` is the PK string.
- Frontend pure logic lives in `web/lib/*.ts` with a matching `web/tests/source/*.test.ts`, mirroring `message-parts.ts` / `auth-tokens.ts` / `stream-errors.ts`.
- Spec: `docs/superpowers/specs/2026-07-17-sidebar-pagination-design.md`.

---

## File Structure

**Backend**
- Create `neos/api/services/pagination.py` — cursor codec (pure, no framework/DB deps).
- Modify `neos/database/repositories/chat_repository.py` — `list_conversations` keyset + `LIMIT n+1` + 3-tuple return.
- Modify `neos/api/services/chat_service.py` — `list_conversations` decodes cursor, computes `next_cursor`.
- Modify `neos/api/models/chat_models.py` — `ConversationListResponse.next_cursor`.
- Modify `neos/api/handlers/chat_handlers.py` — `cursor` query param, 400 on bad cursor.
- Create `tests/api/services/test_pagination.py` — codec round-trip.
- Create `tests/database/repositories/test_chat_repository_pagination.py` — keyset query mechanics via FakeDB.
- Modify `tests/test_chat_service.py` — update the two existing list tests for the 3-tuple + `next_cursor`.

**Frontend**
- Create `web/lib/chat-history-pagination.ts` — `ChatHistory` type, `PAGE_SIZE`, `getChatHistoryPaginationKey`.
- Modify `web/lib/adapters/chat-adapters.ts` — pass `next_cursor` → `nextCursor`.
- Modify `web/components/sidebar-history.tsx` — import + re-export from the new lib; drop inlined pagination logic.
- Modify `web/app/(chat)/api/history/route.ts` — read `cursor`, drop hardcoded `offset=0`.
- Create `web/tests/source/chat-history-pagination.test.ts` — key builder behavior.

**Docs**
- Modify `docs/FE_AUDIT_260717.md` — mark §1 row #5, §3.4, §7 #7 resolved.

---

## Task 1: Backend cursor codec

**Files:**
- Create: `neos/api/services/pagination.py`
- Test: `tests/api/services/test_pagination.py`

**Interfaces:**
- Consumes: nothing (pure module).
- Produces:
  - `@dataclass(frozen=True) class ConversationCursor` with fields `is_pinned: bool`, `last_message_at: datetime | None`, `created_at: datetime`, `conversation_id: str`.
  - `encode_conversation_cursor(is_pinned: bool, last_message_at: datetime | None, created_at: datetime, conversation_id: str) -> str`
  - `decode_conversation_cursor(token: str) -> ConversationCursor` — raises `ValueError` on malformed input.

- [ ] **Step 1: Write the failing test**

Create `tests/api/services/test_pagination.py`:

```python
from datetime import datetime

import pytest

from neos.api.services.pagination import (
    ConversationCursor,
    decode_conversation_cursor,
    encode_conversation_cursor,
)


def test_roundtrip_with_last_message_at():
    token = encode_conversation_cursor(
        is_pinned=True,
        last_message_at=datetime(2026, 7, 17, 12, 30, 45, 123456),
        created_at=datetime(2026, 7, 1, 9, 0, 0),
        conversation_id="conv_abc",
    )
    assert isinstance(token, str)
    decoded = decode_conversation_cursor(token)
    assert decoded == ConversationCursor(
        is_pinned=True,
        last_message_at=datetime(2026, 7, 17, 12, 30, 45, 123456),
        created_at=datetime(2026, 7, 1, 9, 0, 0),
        conversation_id="conv_abc",
    )


def test_roundtrip_with_null_last_message_at():
    token = encode_conversation_cursor(
        is_pinned=False,
        last_message_at=None,
        created_at=datetime(2026, 7, 1, 9, 0, 0),
        conversation_id="conv_xyz",
    )
    decoded = decode_conversation_cursor(token)
    assert decoded.last_message_at is None
    assert decoded.is_pinned is False
    assert decoded.conversation_id == "conv_xyz"


def test_decode_rejects_garbage():
    with pytest.raises(ValueError):
        decode_conversation_cursor("!!!not-base64!!!")


def test_decode_rejects_missing_fields():
    import base64
    import json

    bad = base64.urlsafe_b64encode(json.dumps({"p": True}).encode()).decode()
    with pytest.raises(ValueError):
        decode_conversation_cursor(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/services/test_pagination.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neos.api.services.pagination'`

- [ ] **Step 3: Write minimal implementation**

Create `neos/api/services/pagination.py`:

```python
"""대화 목록 keyset 페이지네이션 커서 코덱.

커서는 정렬 튜플 (is_pinned, last_message_at, created_at, conversation_id)을
base64url(JSON)로 인코딩한 불투명 토큰이다. 프론트엔드는 내용을 해석하지 않고
그대로 되돌려 보낸다. 상세: docs/superpowers/specs/2026-07-17-sidebar-pagination-design.md
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ConversationCursor:
    is_pinned: bool
    last_message_at: datetime | None
    created_at: datetime
    conversation_id: str


def encode_conversation_cursor(
    is_pinned: bool,
    last_message_at: datetime | None,
    created_at: datetime,
    conversation_id: str,
) -> str:
    payload = {
        "p": bool(is_pinned),
        "m": last_message_at.isoformat() if last_message_at is not None else None,
        "t": created_at.isoformat(),
        "i": conversation_id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_conversation_cursor(token: str) -> ConversationCursor:
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        payload = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeError) as exc:
        raise ValueError(f"malformed cursor token: {exc}") from exc

    if not isinstance(payload, dict) or not {"p", "m", "t", "i"} <= payload.keys():
        raise ValueError("cursor payload missing required fields")

    try:
        return ConversationCursor(
            is_pinned=bool(payload["p"]),
            last_message_at=(
                datetime.fromisoformat(payload["m"])
                if payload["m"] is not None
                else None
            ),
            created_at=datetime.fromisoformat(payload["t"]),
            conversation_id=str(payload["i"]),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid cursor field: {exc}") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/services/test_pagination.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add neos/api/services/pagination.py tests/api/services/test_pagination.py
git commit -m "feat(pagination): add opaque conversation cursor codec

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Backend repository keyset query

**Files:**
- Modify: `neos/database/repositories/chat_repository.py` (`list_conversations`, currently lines 321-419)
- Test: `tests/database/repositories/test_chat_repository_pagination.py`

**Interfaces:**
- Consumes: `ConversationCursor` from `neos.api.services.pagination` (Task 1).
- Produces: `ChatRepository.list_conversations(user_id, status=None, include_archived=False, limit=50, offset=0, cursor: ConversationCursor | None = None) -> tuple[list[dict], int, bool]` — now a **3-tuple** `(conversations, total_count, has_more)`.

**Note on has_more:** computed via a `LIMIT limit + 1` probe. If `limit + 1` rows return, `has_more=True` and the extra row is dropped. `total_count` is a separate `COUNT(*)` over the base predicate **without** the cursor clause.

- [ ] **Step 1: Write the failing test**

Create `tests/database/repositories/test_chat_repository_pagination.py`:

```python
from datetime import datetime

import pytest

from neos.api.services.pagination import ConversationCursor
from neos.database.repositories.chat_repository import ChatRepository


def _row(i: int, *, pinned=False, lma=None):
    # positional shape matches list_conversations SELECT (12 columns)
    return (
        f"conv_{i}", "user_1", f"Title {i}", "claude", "active", "private",
        pinned, 3, lma, datetime(2026, 7, 1, 9, 0, 0), "hi", "bye",
    )


class FakeDB:
    def __init__(self, list_rows, count):
        self.list_rows = list_rows
        self.count = count
        self.queries = []

    async def fetch_all(self, query, *params):
        self.queries.append((query, params))
        return self.list_rows

    async def fetch_one(self, query, *params):
        self.queries.append((query, params))
        return (self.count,)


@pytest.mark.asyncio
async def test_first_page_has_more_true_and_truncates(monkeypatch):
    # limit=2 -> repo asks for 3 rows; 3 returned => has_more, truncate to 2
    fake = FakeDB(list_rows=[_row(1), _row(2), _row(3)], count=10)
    monkeypatch.setattr(
        "neos.database.repositories.chat_repository.db_manager", fake
    )

    convs, total, has_more = await ChatRepository.list_conversations(
        user_id="user_1", limit=2
    )

    assert total == 10
    assert has_more is True
    assert len(convs) == 2
    assert [c["conversation_id"] for c in convs] == ["conv_1", "conv_2"]
    # ORDER BY carries the unique tiebreaker
    list_query = fake.queries[0][0]
    assert "conversation_id DESC" in list_query
    # first page: no cursor predicate, LIMIT is limit+1
    assert "COALESCE(last_message_at" not in list_query


@pytest.mark.asyncio
async def test_last_page_has_more_false(monkeypatch):
    fake = FakeDB(list_rows=[_row(1), _row(2)], count=2)
    monkeypatch.setattr(
        "neos.database.repositories.chat_repository.db_manager", fake
    )

    convs, total, has_more = await ChatRepository.list_conversations(
        user_id="user_1", limit=2
    )

    assert has_more is False
    assert len(convs) == 2


@pytest.mark.asyncio
async def test_cursor_adds_keyset_predicate_and_params(monkeypatch):
    fake = FakeDB(list_rows=[_row(4)], count=10)
    monkeypatch.setattr(
        "neos.database.repositories.chat_repository.db_manager", fake
    )
    cursor = ConversationCursor(
        is_pinned=False,
        last_message_at=None,
        created_at=datetime(2026, 7, 1, 9, 0, 0),
        conversation_id="conv_3",
    )

    convs, total, has_more = await ChatRepository.list_conversations(
        user_id="user_1", limit=2, cursor=cursor
    )

    list_query, list_params = fake.queries[0]  # fetch_all is first call here
    # keyset predicate present with COALESCE sentinel
    assert "COALESCE(last_message_at" in list_query
    assert "is_pinned <" in list_query
    # sentinel datetime.min is bound as a real param (never the string '-infinity')
    assert datetime.min in list_params
    assert "'-infinity'" not in list_query
    # NULL last_message_at in the cursor is normalized to the sentinel
    assert list_params.count(datetime.min) >= 2  # COALESCE arg + normalized :m
    assert has_more is False  # only 1 row < limit+1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/database/repositories/test_chat_repository_pagination.py -v`
Expected: FAIL — `list_conversations` returns a 2-tuple (ValueError: not enough values to unpack) and lacks the `cursor` kwarg.

- [ ] **Step 3: Write minimal implementation**

In `neos/database/repositories/chat_repository.py`, add the import near the top (with the other imports):

```python
from datetime import datetime
from neos.api.services.pagination import ConversationCursor
```

Replace the entire `list_conversations` method body (lines 321-419) with:

```python
    @staticmethod
    async def list_conversations(
        user_id: str,
        status: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
        cursor: Optional[ConversationCursor] = None,
    ) -> Tuple[List[Dict[str, Any]], int, bool]:
        """대화 목록 조회 (keyset 커서 페이지네이션)

        Args:
            user_id: 사용자 ID
            status: 상태 필터
            include_archived: 아카이브 포함 여부
            limit: 최대 결과 수
            offset: 오프셋 (cursor가 주어지면 무시)
            cursor: keyset 커서. 주어지면 이 위치 다음부터 조회

        Returns:
            (대화 목록, 전체 개수, 다음 페이지 존재 여부)
        """
        # NULL last_message_at 정렬 센티넬. ORDER BY ... NULLS LAST와 동일 순서를
        # 주도록 어떤 실제 timestamp보다도 작은 값을 실제 파라미터로 바인드한다.
        null_lma_sentinel = datetime.min

        # ---- 기본 WHERE (COUNT와 목록 공용) ----
        base_where = ["user_id = $1", "deleted_at IS NULL"]
        base_params: List[Any] = [user_id]
        idx = 2

        if status:
            base_where.append(f"status = ${idx}")
            base_params.append(status)
            idx += 1
        elif not include_archived:
            base_where.append("status != 'archived'")

        base_where_sql = " AND ".join(base_where)

        # ---- 전체 개수 (커서와 무관) ----
        count_query = f"""
        SELECT COUNT(*)
        FROM conversations
        WHERE {base_where_sql}
        """
        count_result = await db_manager.fetch_one(count_query, *base_params)
        total_count = count_result[0] if count_result else 0

        # ---- 목록 WHERE (기본 + 선택적 커서 술어) ----
        list_where = list(base_where)
        list_params = list(base_params)
        lidx = idx

        if cursor is not None:
            cursor_m = (
                cursor.last_message_at
                if cursor.last_message_at is not None
                else null_lma_sentinel
            )
            p, m, t, i, s = lidx, lidx + 1, lidx + 2, lidx + 3, lidx + 4
            list_where.append(
                "("
                f"is_pinned < ${p} "
                f"OR (is_pinned = ${p} AND COALESCE(last_message_at, ${s}) < ${m}) "
                f"OR (is_pinned = ${p} AND COALESCE(last_message_at, ${s}) = ${m} "
                f"AND created_at < ${t}) "
                f"OR (is_pinned = ${p} AND COALESCE(last_message_at, ${s}) = ${m} "
                f"AND created_at = ${t} AND conversation_id < ${i})"
                ")"
            )
            list_params.extend(
                [
                    cursor.is_pinned,
                    cursor_m,
                    cursor.created_at,
                    cursor.conversation_id,
                    null_lma_sentinel,
                ]
            )
            lidx += 5

        list_where_sql = " AND ".join(list_where)

        # has_more 판정용으로 limit+1 행을 읽는다.
        limit_idx = lidx
        list_query = f"""
        SELECT
            conversation_id,
            user_id,
            title,
            model_name,
            status,
            visibility,
            is_pinned,
            message_count,
            last_message_at,
            created_at,
            (
                SELECT content
                FROM messages m
                WHERE m.conversation_id = c.conversation_id
                  AND m.role = 'user'
                ORDER BY m.sequence_number ASC
                LIMIT 1
            ) as first_message_preview,
            (
                SELECT content
                FROM messages m
                WHERE m.conversation_id = c.conversation_id
                ORDER BY m.sequence_number DESC
                LIMIT 1
            ) as last_message_preview
        FROM conversations c
        WHERE {list_where_sql}
        ORDER BY is_pinned DESC, last_message_at DESC NULLS LAST,
                 created_at DESC, conversation_id DESC
        LIMIT ${limit_idx}"""
        list_params.append(limit + 1)

        if cursor is None:
            list_query += f" OFFSET ${limit_idx + 1}"
            list_params.append(offset)

        rows = await db_manager.fetch_all(list_query, *list_params)

        has_more = len(rows) > limit
        rows = rows[:limit]

        conversations = [
            {
                "conversation_id": row[0],
                "user_id": row[1],
                "title": row[2],
                "model_name": row[3],
                "status": row[4],
                "visibility": row[5] if row[5] else "private",
                "is_pinned": row[6],
                "message_count": row[7],
                "last_message_at": row[8],
                "created_at": row[9],
                "first_message_preview": row[10][:100] if row[10] else None,
                "last_message_preview": row[11][:100] if row[11] else None,
            }
            for row in rows
        ]

        return conversations, total_count, has_more
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/database/repositories/test_chat_repository_pagination.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add neos/database/repositories/chat_repository.py tests/database/repositories/test_chat_repository_pagination.py
git commit -m "feat(pagination): keyset cursor query in conversation repository

ORDER BY gains conversation_id tiebreaker; LIMIT n+1 has_more probe;
returns (conversations, total_count, has_more). datetime.min sentinel
for NULL last_message_at (never SQL '-infinity').

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Backend service, model, and handler wiring

**Files:**
- Modify: `neos/api/services/chat_service.py` (`list_conversations`, lines 156-177)
- Modify: `neos/api/models/chat_models.py` (`ConversationListResponse`, lines 239-242)
- Modify: `neos/api/handlers/chat_handlers.py` (`list_user_conversations`, lines 301-328)
- Test: `tests/test_chat_service.py` (update the two existing list tests, lines 250-297)

**Interfaces:**
- Consumes: repository 3-tuple (Task 2); `encode_conversation_cursor`, `decode_conversation_cursor` (Task 1).
- Produces: `ChatService.list_conversations(...)` dict now includes `next_cursor: str | None`; accepts `cursor: str | None = None`. `ConversationListResponse` gains `next_cursor`. Handler accepts `cursor` query param.

- [ ] **Step 1: Update the failing tests**

In `tests/test_chat_service.py`, replace `test_list_conversations_success` (lines 250-277) and `test_list_conversations_with_pagination` (lines 279-297) with:

```python
    @pytest.mark.asyncio
    async def test_list_conversations_success(self):
        """Test listing conversations (no more pages)."""
        user_id = "user_123"
        mock_conversations = [
            {"conversation_id": "conv_1", "title": "Chat 1"},
            {"conversation_id": "conv_2", "title": "Chat 2"},
        ]

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.list_conversations = AsyncMock(
                return_value=(mock_conversations, 2, False)
            )

            result = await ChatService.list_conversations(
                user_id=user_id, limit=10
            )

            assert result["total_count"] == 2
            assert result["has_more"] is False
            assert result["next_cursor"] is None
            assert len(result["conversations"]) == 2

    @pytest.mark.asyncio
    async def test_list_conversations_emits_next_cursor_when_more(self):
        """When has_more, service encodes a cursor from the last row."""
        from datetime import datetime

        user_id = "user_123"
        last = {
            "conversation_id": "conv_10",
            "is_pinned": False,
            "last_message_at": datetime(2026, 7, 17, 12, 0, 0),
            "created_at": datetime(2026, 7, 1, 9, 0, 0),
        }
        mock_conversations = [{"conversation_id": f"conv_{i}"} for i in range(9)] + [last]

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.list_conversations = AsyncMock(
                return_value=(mock_conversations, 50, True)
            )

            result = await ChatService.list_conversations(
                user_id=user_id, limit=10
            )

            assert result["has_more"] is True
            assert isinstance(result["next_cursor"], str) and result["next_cursor"]

            # round-trips back to the last row's tuple
            from neos.api.services.pagination import decode_conversation_cursor

            decoded = decode_conversation_cursor(result["next_cursor"])
            assert decoded.conversation_id == "conv_10"

    @pytest.mark.asyncio
    async def test_list_conversations_decodes_incoming_cursor(self):
        """A string cursor is decoded and forwarded to the repository."""
        from neos.api.services.pagination import encode_conversation_cursor
        from datetime import datetime

        token = encode_conversation_cursor(
            is_pinned=False,
            last_message_at=None,
            created_at=datetime(2026, 7, 1, 9, 0, 0),
            conversation_id="conv_3",
        )

        with patch("neos.api.services.chat_service.ChatRepository") as mock_repo:
            mock_repo.list_conversations = AsyncMock(return_value=([], 0, False))

            await ChatService.list_conversations(
                user_id="user_123", limit=10, cursor=token
            )

            _, kwargs = mock_repo.list_conversations.call_args
            assert kwargs["cursor"].conversation_id == "conv_3"

    @pytest.mark.asyncio
    async def test_list_conversations_rejects_bad_cursor(self):
        with pytest.raises(ValueError):
            await ChatService.list_conversations(
                user_id="user_123", limit=10, cursor="!!!garbage!!!"
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_chat_service.py -k list_conversations -v`
Expected: FAIL — service returns no `next_cursor`, doesn't accept `cursor`, and unpacks a 2-tuple.

- [ ] **Step 3: Implement service, model, and handler**

In `neos/api/services/chat_service.py`, add import near the top:

```python
from neos.api.services.pagination import (
    decode_conversation_cursor,
    encode_conversation_cursor,
)
```

Replace `list_conversations` (lines 156-177) with:

```python
    @staticmethod
    async def list_conversations(
        user_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """사용자의 대화 목록 조회 (keyset 커서 페이지네이션).

        cursor가 손상된 경우 ValueError를 전파한다 (핸들러가 400으로 변환).
        """
        decoded_cursor = (
            decode_conversation_cursor(cursor) if cursor else None
        )

        conversations, total_count, has_more = await ChatRepository.list_conversations(
            user_id=user_id,
            status=status,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
            cursor=decoded_cursor,
        )

        next_cursor = None
        if has_more and conversations:
            last = conversations[-1]
            next_cursor = encode_conversation_cursor(
                is_pinned=last["is_pinned"],
                last_message_at=last["last_message_at"],
                created_at=last["created_at"],
                conversation_id=last["conversation_id"],
            )

        return {
            "conversations": conversations,
            "total_count": total_count,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }
```

In `neos/api/models/chat_models.py`, replace `ConversationListResponse` (lines 239-242) with:

```python
class ConversationListResponse(BaseModel):
    conversations: List[ConversationSummary]
    total_count: int
    has_more: bool
    next_cursor: Optional[str] = None
```

In `neos/api/handlers/chat_handlers.py`, replace `list_user_conversations` (lines 301-328) with:

```python
@router.get("/users/{user_id}/conversations", response_model=ConversationListResponse)
async def list_user_conversations(
    user_id: str,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    cursor: Optional[str] = None,
    include_archived: bool = False,
    current_user: User = Depends(get_current_active_user),
):
    """사용자의 대화 목록 조회 (keyset 커서 페이지네이션)."""
    require_same_user_id(user_id, current_user)
    try:
        result = await ChatService.list_conversations(
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset,
            include_archived=include_archived,
            cursor=cursor,
        )

        return ConversationListResponse(
            conversations=[ConversationSummary(**conv) for conv in result["conversations"]],
            total_count=result["total_count"],
            has_more=result["has_more"],
            next_cursor=result["next_cursor"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid cursor: {e}")
    except Exception as e:
        logger.error(f"Failed to list conversations: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chat_service.py -k list_conversations -v`
Expected: PASS (5 passed — the 4 above plus any archived-adjacent case unchanged)

Also run the broader chat suites to catch fallout from the tuple change:
Run: `python -m pytest tests/test_chat_service.py tests/api/handlers/test_chat_authorization.py -v`
Expected: PASS (no unpack errors)

- [ ] **Step 5: Commit**

```bash
git add neos/api/services/chat_service.py neos/api/models/chat_models.py neos/api/handlers/chat_handlers.py tests/test_chat_service.py
git commit -m "feat(pagination): thread cursor through service, model, handler

Service decodes incoming cursor + emits next_cursor; response model
gains next_cursor; handler adds cursor query param and 400s on bad cursor.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Frontend pure pagination module + adapter

**Files:**
- Create: `web/lib/chat-history-pagination.ts`
- Modify: `web/lib/adapters/chat-adapters.ts` (lines 14-18, 33-40)
- Modify: `web/components/sidebar-history.tsx` (lines 39-42, 44, 79-98 — extract + re-export)
- Test: `web/tests/source/chat-history-pagination.test.ts`

**Interfaces:**
- Consumes: `Chat` type from `@/lib/db/schema`.
- Produces:
  - `type ChatHistory = { chats: Chat[]; hasMore: boolean; nextCursor: string | null }`
  - `const PAGE_SIZE = 20`
  - `getChatHistoryPaginationKey(pageIndex: number, previousPageData: ChatHistory | null): string | null`
  - `adaptBEConversationList(data) -> { chats, hasMore, nextCursor }`

- [ ] **Step 1: Write the failing test**

Create `web/tests/source/chat-history-pagination.test.ts`:

```typescript
import { strict as assert } from "node:assert/strict";
import { describe, test } from "node:test";

import {
  type ChatHistory,
  getChatHistoryPaginationKey,
  PAGE_SIZE,
} from "../../lib/chat-history-pagination";

const page = (over: Partial<ChatHistory> = {}): ChatHistory => ({
  chats: [],
  hasMore: true,
  nextCursor: "CURSOR_A",
  ...over,
});

describe("getChatHistoryPaginationKey", () => {
  test("first page requests limit only, no cursor", () => {
    assert.equal(
      getChatHistoryPaginationKey(0, null),
      `/api/history?limit=${PAGE_SIZE}`
    );
  });

  test("subsequent page forwards the opaque cursor, url-encoded", () => {
    const prev = page({ nextCursor: "a+b/c=" });
    assert.equal(
      getChatHistoryPaginationKey(1, prev),
      `/api/history?cursor=${encodeURIComponent("a+b/c=")}&limit=${PAGE_SIZE}`
    );
  });

  test("stops when previous page has no more", () => {
    assert.equal(getChatHistoryPaginationKey(1, page({ hasMore: false })), null);
  });

  test("stops when previous page has a null cursor", () => {
    assert.equal(
      getChatHistoryPaginationKey(1, page({ nextCursor: null })),
      null
    );
  });

  test("never emits the legacy offset/ending_before params", () => {
    const key = getChatHistoryPaginationKey(1, page());
    assert.ok(key && !key.includes("offset="));
    assert.ok(key && !key.includes("ending_before="));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && pnpm test:source`
Expected: FAIL — cannot find module `../../lib/chat-history-pagination`.

- [ ] **Step 3: Implement the module and adapter**

Create `web/lib/chat-history-pagination.ts`:

```typescript
import type { Chat } from "@/lib/db/schema";

export type ChatHistory = {
  chats: Chat[];
  hasMore: boolean;
  nextCursor: string | null;
};

export const PAGE_SIZE = 20;

/**
 * SWRInfinite 키 빌더. 백엔드가 발급한 불투명 커서를 그대로 되돌려 보낸다
 * (내용을 해석하지 않는다). 근거: docs/FE_AUDIT_260717 §3.4.
 */
export function getChatHistoryPaginationKey(
  pageIndex: number,
  previousPageData: ChatHistory | null
): string | null {
  if (previousPageData && previousPageData.hasMore === false) {
    return null;
  }

  if (pageIndex === 0) {
    return `/api/history?limit=${PAGE_SIZE}`;
  }

  const cursor = previousPageData?.nextCursor;
  if (!cursor) {
    return null;
  }

  return `/api/history?cursor=${encodeURIComponent(cursor)}&limit=${PAGE_SIZE}`;
}
```

In `web/lib/adapters/chat-adapters.ts`, update the interface (lines 14-18) to add `next_cursor`:

```typescript
interface BEConversationListResponse {
  conversations: BEConversationResponse[];
  total_count: number;
  has_more: boolean;
  next_cursor?: string | null;
}
```

And update `adaptBEConversationList` (lines 33-40):

```typescript
export function adaptBEConversationList(
  data: BEConversationListResponse
): { chats: Chat[]; hasMore: boolean; nextCursor: string | null } {
  return {
    chats: data.conversations.map(adaptBEConversation),
    hasMore: data.has_more,
    nextCursor: data.next_cursor ?? null,
  };
}
```

In `web/components/sidebar-history.tsx`, remove the local `ChatHistory` type (lines 39-42), `PAGE_SIZE` (line 44), and the whole `getChatHistoryPaginationKey` function (lines 79-98). Replace them with a re-export near the top-level declarations so the four other importers keep working unchanged:

```typescript
export {
  type ChatHistory,
  getChatHistoryPaginationKey,
  PAGE_SIZE,
} from "@/lib/chat-history-pagination";
```

Keep the `import { type ChatHistory } from "@/lib/chat-history-pagination"` usage available for the component body (the `useSWRInfinite<ChatHistory>` call already references `ChatHistory`; the re-export above brings it into scope).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && pnpm test:source`
Expected: PASS (all source tests, including the 5 new pagination-key cases)

- [ ] **Step 5: Commit**

```bash
git add web/lib/chat-history-pagination.ts web/lib/adapters/chat-adapters.ts web/components/sidebar-history.tsx web/tests/source/chat-history-pagination.test.ts
git commit -m "feat(pagination): extract pure pagination key builder + adapter nextCursor

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Frontend route wiring + typecheck

**Files:**
- Modify: `web/app/(chat)/api/history/route.ts` (lines 10, 19-21)

**Interfaces:**
- Consumes: `adaptBEConversationList` (now returns `nextCursor`) from Task 4.
- Produces: `/api/history?cursor=<opaque>&limit=<n>` → backend `?limit=<n>&cursor=<opaque>`.

- [ ] **Step 1: Implement the route change**

In `web/app/(chat)/api/history/route.ts`, replace the `GET` body's limit/backend-call section (lines 10, 19-21) so it reads the cursor and drops the hardcoded `offset=0`:

```typescript
  const limit = Number.parseInt(searchParams.get("limit") || "10", 10);
  const cursor = searchParams.get("cursor");

  const session = await auth();

  if (!session?.user) {
    return new ChatSDKError("unauthorized:chat").toResponse();
  }

  const userId = session.user.backendUserId || session.user.id;
  const query = cursor
    ? `limit=${limit}&cursor=${encodeURIComponent(cursor)}`
    : `limit=${limit}`;
  const res = await callBackendAPI(
    `/api/v1/chat/users/${userId}/conversations?${query}`
  );
```

Leave the rest of `GET` (the `!res.ok` guard and `adaptBEConversationList` return) and the entire `DELETE` handler unchanged.

- [ ] **Step 2: Typecheck**

Run: `cd web && pnpm exec tsc --noEmit`
Expected: PASS — `ChatHistory` now carries `nextCursor` everywhere it flows (route return, SWR generic, `use-chat-visibility.ts`).

- [ ] **Step 3: Lint the touched files**

Run: `cd web && pnpm lint`
Expected: PASS (no new violations in the changed files)

- [ ] **Step 4: Re-run source tests as a regression gate**

Run: `cd web && pnpm test:source`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add "web/app/(chat)/api/history/route.ts"
git commit -m "fix(pagination): history route forwards cursor, drops offset=0 (FE_AUDIT 3.4)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Manual end-to-end verification + audit doc update

**Files:**
- Modify: `docs/FE_AUDIT_260717.md` (§1 row #5, §3.4, §7 #7)

**Note:** The in-harness tests cover the codec (full), the repo query mechanics (FakeDB), the service cursor flow, and the FE key builder. True Postgres keyset correctness (no page overlap/skip across a real seeded table) is **not** exercised by any automated test here, so it must be verified manually before marking the audit resolved.

- [ ] **Step 1: Manual keyset verification against a running stack**

With the backend + a seeded database running (>40 conversations for the user, a mix of pinned/unpinned and some with NULL `last_message_at`):

1. Open the app, scroll the sidebar to the bottom repeatedly.
2. Confirm: each "load more" appends **new** conversations, no duplicates, no infinite spinner, and the list terminates.
3. In devtools Network, confirm requests go `/api/history?limit=20` then `/api/history?cursor=...&limit=20`, and the final page response has `next_cursor: null` / `has_more: false`.
4. Tamper check: hit `/api/v1/chat/users/<id>/conversations?cursor=garbage` (authenticated) and confirm a `400`, not a `500`.

Record the result (pass/fail + notes) in the commit message for Step 3.

- [ ] **Step 2: Update the audit document**

In `docs/FE_AUDIT_260717.md`:

- §1 summary table row #5 (`| 5 | 🟡 | 🔴 **미해결** | ...페이지네이션...`): change the 상태 cell to `✅ 해결됨`.
- Update the line under the table that reads `**즉, 남은 top-5 이슈는 #5(§3.4) 하나뿐이다** ...` to state that #5 is now resolved and no top-5 issues remain open.
- §3.4 heading: change to `### 3.4 ✅ 해결됨 (2026-07-17) — 대화 목록 페이지네이션 불일치` and add a resolution note block above the original analysis:

```markdown
> **해결:** keyset(cursor) 페이지네이션으로 교체했다. 백엔드가 정렬 튜플
> (is_pinned, last_message_at, created_at, conversation_id)을 불투명 base64 커서로
> 발급하고(`neos/api/services/pagination.py`), 리포지토리가 keyset WHERE + LIMIT n+1로
> 조회한다(`neos/database/repositories/chat_repository.py`). FE는 커서를 해석 없이
> 되돌려 보낸다(`web/lib/chat-history-pagination.ts`, `web/app/(chat)/api/history/route.ts`).
> 회귀 방지: `web/tests/source/chat-history-pagination.test.ts`,
> `tests/api/services/test_pagination.py`, `tests/database/repositories/test_chat_repository_pagination.py`.
> 설계: `docs/superpowers/specs/2026-07-17-sidebar-pagination-design.md`.
>
> **잔여(범위 밖):** FE는 `created_at`으로 날짜 그룹(Today/Yesterday/…)을 나누는데
> BE 정렬은 `last_message_at` 기준이다. 따라서 "더 보기"가 이미 렌더된 날짜 그룹
> 중간에 항목을 삽입할 수 있다 — 기존 동작이며 버그가 아니고, 정렬 기준 통일은
> 별도 제품 결정이라 이번 범위에서 제외했다.
>
> 아래는 감사 시점의 원래 분석이다(기록 보존).
```

- §7 recommendations table row #7 (`| 7 | **P1** | **페이지네이션 수정**(§3.4)...`): change priority cell to `~~**P1**~~ ✅ 완료` and set the 비고 to `2026-07-17 완료 (keyset 커서, web/lib/chat-history-pagination.ts + neos/api/services/pagination.py)`.
- In the §1 status-update note block, add `§3.4` and `§7 #7` to the list of sections that carry a status marker.

- [ ] **Step 3: Commit**

```bash
git add docs/FE_AUDIT_260717.md
git commit -m "docs(audit): mark §3.4 pagination resolved (§1 #5, §7 #7)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- Cursor codec (§①) → Task 1. ✅
- Repository keyset + ORDER BY tiebreaker + limit+1 + sentinel (§②) → Task 2. ✅
- Service next_cursor + decode (§③) → Task 3. ✅
- Model + handler cursor param + 400 (§④) → Task 3. ✅
- FE adapter nextCursor (§⑤) → Task 4. ✅
- FE route cursor + drop offset=0 (§⑥) → Task 5. ✅
- FE sidebar key builder + ChatHistory.nextCursor (§⑦) → Task 4 (extraction) + Task 5 (typecheck). ✅
- Tests: BE codec, repo mechanics, FE key builder (§Tests) → Tasks 1,2,4; Postgres correctness noted as manual in Task 6. ✅
- Out-of-scope group mismatch recorded (§범위 밖) → Task 6 audit note. ✅
- Docs update (§문서 갱신) → Task 6. ✅

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows full code.

**Type consistency:** `ConversationCursor` fields (`is_pinned`, `last_message_at`, `created_at`, `conversation_id`) are identical across Tasks 1→2→3. Repository returns the 3-tuple `(conversations, total_count, has_more)` in Task 2 and is consumed as such in Task 3. `ChatHistory { chats, hasMore, nextCursor }` is identical across Task 4 module, test, and adapter return shape. `getChatHistoryPaginationKey` signature matches between the module (Task 4) and its test (Task 4).

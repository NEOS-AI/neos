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

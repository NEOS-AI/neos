from datetime import datetime, timezone

import pytest

from neos.database.repositories import model_preference_repository as mod

pytestmark = pytest.mark.no_db


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeDB:
    """읽기는 fetch_one, 쓰기는 execute_in_transaction (커밋하는 쪽)."""

    def __init__(self, one=None, many=None):
        self.one, self.many, self.calls = one, many or [], []

    async def fetch_one(self, query, *params):
        self.calls.append(("fetch_one", query, params))
        return self.one

    async def fetch_all(self, query, *params):
        self.calls.append(("fetch_all", query, params))
        return self.many

    async def execute_in_transaction(self, query, *params):
        self.calls.append(("tx", query, params))
        return _Result(self.one)


@pytest.mark.asyncio
async def test_get_effort_reads_one_row(monkeypatch) -> None:
    db = FakeDB(one=("high",))
    monkeypatch.setattr(mod, "db_manager", db)

    assert await mod.ModelPreferenceRepository.get_effort("u1", "m1") == "high"
    assert db.calls[0][2] == ("u1", "m1")


@pytest.mark.asyncio
async def test_get_effort_is_none_without_a_row(monkeypatch) -> None:
    monkeypatch.setattr(mod, "db_manager", FakeDB(one=None))
    assert await mod.ModelPreferenceRepository.get_effort("u1", "m1") is None


@pytest.mark.asyncio
async def test_effort_for_conversation_is_one_joined_query(monkeypatch) -> None:
    db = FakeDB(one=("low",))
    monkeypatch.setattr(mod, "db_manager", db)

    got = await mod.ModelPreferenceRepository.get_effort_for_conversation("c1", "m1")

    assert got == "low"
    assert len(db.calls) == 1
    _, query, params = db.calls[0]
    assert "JOIN user_model_preferences" in query
    assert params == ("c1", "m1")


@pytest.mark.asyncio
async def test_upsert_commits_and_returns_the_stored_row(monkeypatch) -> None:
    now = datetime(2026, 9, 24, tzinfo=timezone.utc)
    db = FakeDB(one=("m1", "low", now))
    monkeypatch.setattr(mod, "db_manager", db)

    pref = await mod.ModelPreferenceRepository.upsert_effort("u1", "m1", "low")

    assert pref == mod.ModelPreference(model_pin="m1", effort="low", updated_at=now)
    kind, query, _ = db.calls[0]
    assert kind == "tx"  # fetch_one 은 INSERT 를 커밋하지 않는다
    assert "ON CONFLICT (user_id, model_pin) DO UPDATE" in query


@pytest.mark.asyncio
async def test_delete_commits_and_reports_whether_a_row_went(monkeypatch) -> None:
    db = FakeDB(one=("m1",))
    monkeypatch.setattr(mod, "db_manager", db)
    assert await mod.ModelPreferenceRepository.delete("u1", "m1") is True
    assert db.calls[0][0] == "tx"
    monkeypatch.setattr(mod, "db_manager", FakeDB(one=None))
    assert await mod.ModelPreferenceRepository.delete("u1", "m1") is False


@pytest.mark.asyncio
async def test_list_for_user(monkeypatch) -> None:
    now = datetime(2026, 9, 24, tzinfo=timezone.utc)
    monkeypatch.setattr(mod, "db_manager", FakeDB(many=[("a", "low", now), ("b", "max", now)]))
    rows = await mod.ModelPreferenceRepository.list_for_user("u1")
    assert [(r.model_pin, r.effort) for r in rows] == [("a", "low"), ("b", "max")]

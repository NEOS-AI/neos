import pytest

import importlib

from neos.learn.lessons import reset_lesson_store, resolve_lesson_session_factory

curator_mod = importlib.import_module("neos.tasks.curate_learned_skills")

pytestmark = pytest.mark.no_db


class RecordingDatabaseManager:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def initialize(self) -> None:
        self.calls.append("initialize")

    async def close(self) -> None:
        self.calls.append("close")

    async def get_session(self):
        raise AssertionError("curator must not open a session during bind")


@pytest.mark.asyncio
async def test_curate_uses_worker_database_when_factory_unset(monkeypatch) -> None:
    reset_lesson_store()
    manager = RecordingDatabaseManager()
    seen: list[object] = []

    async def fake_curate(store, *, stale_days, archive_days):
        del stale_days, archive_days
        from neos.learn.postgres import PostgresLessonStore

        assert isinstance(store, PostgresLessonStore)
        seen.append(resolve_lesson_session_factory())
        return {"archived": 0, "skipped": 0}

    monkeypatch.setattr(curator_mod, "DatabaseManager", lambda: manager)
    monkeypatch.setattr(curator_mod, "curate_lessons_async", fake_curate)

    result = await curator_mod._curate_learned_skills(stale_days=30, archive_days=90)

    assert result == {"archived": 0, "skipped": 0}
    assert manager.calls == ["initialize", "close"]
    assert seen == [manager.get_session]
    assert resolve_lesson_session_factory() is None

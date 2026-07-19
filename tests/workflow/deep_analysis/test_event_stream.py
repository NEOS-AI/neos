"""커서 리더 단위 테스트 — Fake 세션만 쓰므로 Postgres가 필요 없다."""

import json
from types import SimpleNamespace

import pytest

from neos.workflow.deep_analysis.event_stream import (
    get_run_owner,
    read_events_after,
)


pytestmark = pytest.mark.no_db


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return iter(self._rows)


class FakeSession:
    """seq > after 필터와 정렬을 SQL 대신 파이썬에서 재현하는 세션 더블.

    실제 세션은 SQLAlchemy Select를 받아 DB에서 거른다. 여기서는 select
    객체를 무시하고 `self.rows`를 그대로 돌려주되, 호출부가 넘긴 커서를
    검증할 수 있도록 execute 호출을 기록한다.
    """

    def __init__(self, rows=None, run=None):
        self.rows = rows or []
        self.run = run
        self.executed = []

    async def execute(self, statement):
        self.executed.append(statement)
        return FakeScalars(self.rows)

    async def get(self, model, key):
        return self.run


def _event(seq, kind, qid, payload):
    return SimpleNamespace(
        seq=seq,
        kind=kind,
        qid=qid,
        payload=json.dumps(payload, ensure_ascii=False),
    )


@pytest.mark.asyncio
async def test_read_events_after_shapes_rows_for_sse():
    session = FakeSession(
        rows=[
            _event(1, "job_started", None, {"profile": "dev"}),
            _event(2, "question_opened", "q1000000", {"depth": 0}),
        ]
    )

    events = await read_events_after(session, "run00001", 0)

    assert events == [
        {"seq": 1, "type": "job_started", "qid": None, "payload": {"profile": "dev"}},
        {
            "seq": 2,
            "type": "question_opened",
            "qid": "q1000000",
            "payload": {"depth": 0},
        },
    ]


@pytest.mark.asyncio
async def test_read_events_after_tolerates_malformed_payload():
    """P4대로 이벤트 로그는 append-only라 나쁜 payload를 고칠 수 없다.
    리더가 죽으면 그 run의 스트림이 통째로 닫히므로 빈 dict로 낮춘다."""
    row = SimpleNamespace(seq=9, kind="dead_end", qid="q1", payload="not json")
    session = FakeSession(rows=[row])

    events = await read_events_after(session, "run00001", 0)

    assert events == [{"seq": 9, "type": "dead_end", "qid": "q1", "payload": {}}]


@pytest.mark.asyncio
async def test_get_run_owner_returns_none_for_missing_run():
    assert await get_run_owner(FakeSession(run=None), "nope") is None


@pytest.mark.asyncio
async def test_get_run_owner_returns_user_and_status():
    run = SimpleNamespace(user_id="owner", status="running")

    assert await get_run_owner(FakeSession(run=run), "run00001") == (
        "owner",
        "running",
    )

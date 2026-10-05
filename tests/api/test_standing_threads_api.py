"""Q8c: the owner's thread API, and what is absent when it is off
(docs/Q8_CROSS_CHANNEL_THREAD_DESIGN_261005.md §9)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neos.api.handlers.standing_thread_handlers as mod
from neos.api.dependencies.auth import get_current_user
from neos.api.handlers.standing_agent_handlers import get_standing_agent_store
from neos.standing.models import StandingAgentStatus
from neos.standing.store import InMemoryStandingAgentStore
from neos.standing.threads import InMemoryAgentThreadStore

pytestmark = pytest.mark.no_db

SLACK_DM = "v2:slack:T1:D_alice:-"
TELEGRAM_DM = "v2:telegram:dm:42:-"


def _run(coro):
    return asyncio.run(coro)


class World:
    def __init__(self) -> None:
        self.agents = InMemoryStandingAgentStore()
        self.threads = InMemoryAgentThreadStore(self.agents)
        self.alice = _run(self.agents.create("alice", "Dot"))
        self.bob = _run(self.agents.create("bob", "Bob's"))
        self.user = SimpleNamespace(user_id="alice")
        app = FastAPI()
        app.include_router(mod.router)
        app.dependency_overrides.update(
            {
                get_current_user: lambda: self.user,
                get_standing_agent_store: lambda: self.agents,
                mod.get_thread_store: lambda: self.threads,
            }
        )
        self.http = TestClient(app)

    def talk(self, agent, session=SLACK_DM, channel="slack", *texts: str):
        async def go():
            thread = await self.threads.attach_session(agent.agent_id, session, channel)
            for index, body in enumerate(texts):
                role = "user" if index % 2 == 0 else "assistant"
                await self.threads.append_turn(
                    thread.agent_thread_id, session, channel, role, body
                )
            return thread

        return _run(go())


@pytest.fixture
def world():
    return World()


def test_reading_the_active_thread_does_not_open_one(world) -> None:
    response = world.http.get(f"/standing-agents/{world.alice.agent_id}/thread")

    assert response.status_code == 200
    assert response.json() == {"thread": None, "sessions": []}
    assert _run(world.threads.list_threads(world.alice.agent_id)) == []


def test_the_active_thread_lists_its_sessions(world) -> None:
    thread = world.talk(world.alice, SLACK_DM, "slack", "hi")
    world.talk(world.alice, TELEGRAM_DM, "telegram")

    body = world.http.get(f"/standing-agents/{world.alice.agent_id}/thread").json()

    assert body["thread"]["agent_thread_id"] == thread.agent_thread_id
    assert body["thread"]["archived_at"] is None
    assert sorted((s["session_id"], s["channel_type"]) for s in body["sessions"]) == [
        (SLACK_DM, "slack"),
        (TELEGRAM_DM, "telegram"),
    ]


def test_rotate_archives_and_the_list_shows_both(world) -> None:
    old = world.talk(world.alice, SLACK_DM, "slack", "before")

    rotated = world.http.post(f"/standing-agents/{world.alice.agent_id}/thread/rotate")
    listed = world.http.get(f"/standing-agents/{world.alice.agent_id}/threads").json()

    assert rotated.status_code == 200
    new_id = rotated.json()["agent_thread_id"]
    assert new_id != old.agent_thread_id
    assert [(t["agent_thread_id"], t["archived_at"] is None) for t in listed] == [
        (old.agent_thread_id, False),
        (new_id, True),
    ]
    # The session moved with the rotation.
    active = world.http.get(f"/standing-agents/{world.alice.agent_id}/thread").json()
    assert [s["session_id"] for s in active["sessions"]] == [SLACK_DM]


def test_rotate_works_for_a_paused_agent(world) -> None:
    """Starting over creates no work, so the agent's status does not gate it."""
    _run(world.agents.update("alice", world.alice.agent_id, status=StandingAgentStatus.PAUSED))

    assert world.http.post(f"/standing-agents/{world.alice.agent_id}/thread/rotate").status_code == 200


@pytest.mark.parametrize("page", [1, 2, 50])
def test_the_turn_feed_pages_every_turn_once(world, page) -> None:
    thread = world.talk(world.alice, SLACK_DM, "slack", "a", "b", "c", "d", "e")
    url = f"/standing-agents/{world.alice.agent_id}/threads/{thread.agent_thread_id}/turns"

    seen, after = [], None
    for _ in range(10):
        params = {"limit": page} | ({"after": after} if after else {})
        body = world.http.get(url, params=params).json()
        if not body["turns"]:
            assert body["next"] == after  # an empty page hands the cursor back
            break
        seen += [(t["role"], t["content"]) for t in body["turns"]]
        after = body["next"]

    assert seen == [
        ("user", "a"), ("assistant", "b"), ("user", "c"), ("assistant", "d"), ("user", "e")
    ]


def test_an_archived_threads_turns_are_still_readable(world) -> None:
    old = world.talk(world.alice, SLACK_DM, "slack", "kept")
    world.http.post(f"/standing-agents/{world.alice.agent_id}/thread/rotate")

    body = world.http.get(
        f"/standing-agents/{world.alice.agent_id}/threads/{old.agent_thread_id}/turns"
    ).json()

    assert [t["content"] for t in body["turns"]] == ["kept"]


def test_an_unreadable_cursor_is_unprocessable(world) -> None:
    thread = world.talk(world.alice, SLACK_DM, "slack", "x")

    response = world.http.get(
        f"/standing-agents/{world.alice.agent_id}/threads/{thread.agent_thread_id}/turns",
        params={"after": "not-a-cursor"},
    )

    assert response.status_code == 422


def test_detach_then_the_session_is_gone(world) -> None:
    world.talk(world.alice, SLACK_DM, "slack", "x")
    url = f"/standing-agents/{world.alice.agent_id}/thread/sessions/{SLACK_DM}"

    assert world.http.delete(url).status_code == 204
    assert world.http.get(f"/standing-agents/{world.alice.agent_id}/thread").json()["sessions"] == []
    assert world.http.delete(url).status_code == 404


def test_someone_elses_agent_thread_and_session_are_not_found(world) -> None:
    alice_thread = world.talk(world.alice, SLACK_DM, "slack", "private")
    bob_thread = world.talk(world.bob, TELEGRAM_DM, "telegram", "bob's")
    a, b = world.alice.agent_id, world.bob.agent_id

    # Alice addressing Bob's agent: every verb is 404.
    for method, path in [
        ("GET", f"/standing-agents/{b}/thread"),
        ("GET", f"/standing-agents/{b}/threads"),
        ("GET", f"/standing-agents/{b}/threads/{bob_thread.agent_thread_id}/turns"),
        ("POST", f"/standing-agents/{b}/thread/rotate"),
        ("DELETE", f"/standing-agents/{b}/thread/sessions/{TELEGRAM_DM}"),
    ]:
        assert world.http.request(method, path).status_code == 404, (method, path)
    # Alice's own agent, Bob's thread id or session: 404 as well, and nothing moved.
    assert (
        world.http.get(f"/standing-agents/{a}/threads/{bob_thread.agent_thread_id}/turns").status_code
        == 404
    )
    assert world.http.delete(f"/standing-agents/{a}/thread/sessions/{TELEGRAM_DM}").status_code == 404
    assert _run(world.threads.thread_for_session(TELEGRAM_DM)) == bob_thread
    assert _run(world.threads.active(world.bob.agent_id)) == bob_thread
    assert _run(world.threads.active(world.alice.agent_id)) == alice_thread


def test_a_deleted_agent_is_not_found(world) -> None:
    world.talk(world.alice, SLACK_DM, "slack", "x")
    _run(world.agents.delete("alice", world.alice.agent_id))

    assert world.http.get(f"/standing-agents/{world.alice.agent_id}/thread").status_code == 404
    assert world.http.post(f"/standing-agents/{world.alice.agent_id}/thread/rotate").status_code == 404


def test_the_default_app_serves_no_thread_routes() -> None:
    from tests.api.test_retired_routes import _routes

    served = _routes()
    assert ("POST", "/api/v1/coding/tasks") in served  # the reader sees included routers
    assert not [path for _method, path in served if "/thread" in path and "standing" in path]


# ---- Q8d: the web agent conversation ---------------------------------------------


class FakeConversations:
    def __init__(self) -> None:
        self.live: dict[str, str] = {}  # conversation_id -> user_id
        self.deleted: list[str] = []
        self._next = 0

    async def owned(self, user_id: str, conversation_id: str) -> bool:
        return self.live.get(conversation_id) == user_id

    async def create(self, user_id: str, title: str) -> str:
        self._next += 1
        conversation_id = f"conv_{self._next}"
        self.live[conversation_id] = user_id
        return conversation_id

    async def delete(self, conversation_id: str) -> None:
        self.live.pop(conversation_id, None)
        self.deleted.append(conversation_id)


@pytest.fixture
def web(world):
    conversations = FakeConversations()
    world.http.app.dependency_overrides[mod.get_conversation_port] = lambda: conversations
    return world, conversations


def _open(world, agent=None):
    agent = agent or world.alice
    return world.http.post(f"/standing-agents/{agent.agent_id}/thread/web-conversation")


def test_the_web_conversation_is_made_once_and_attached(web) -> None:
    world, conversations = web

    first = _open(world)
    second = _open(world)

    assert first.status_code == 201 and first.json()["created"] is True
    assert second.status_code == 200 and second.json()["created"] is False
    conversation_id = first.json()["conversation_id"]
    assert second.json()["conversation_id"] == conversation_id
    assert list(conversations.live) == [conversation_id]
    attached = _run(world.threads.thread_for_session(f"web:{conversation_id}"))
    assert attached is not None and attached.agent_thread_id == first.json()["agent_thread_id"]


def test_a_deleted_web_conversation_is_replaced(web) -> None:
    world, conversations = web
    old = _open(world).json()["conversation_id"]
    conversations.live.pop(old)  # the owner deleted it in the web UI

    renewed = _open(world)

    assert renewed.status_code == 201
    assert renewed.json()["conversation_id"] != old
    assert _run(world.threads.thread_for_session(f"web:{old}")) is None


def test_a_lost_race_deletes_its_conversation_and_returns_the_winner(web) -> None:
    world, conversations = web
    real_attach = world.threads.attach_session

    async def racing_attach(agent_id, session_id, channel_type):
        # Another request attaches its web conversation first.
        if channel_type == "web" and session_id != "web:winner":
            conversations.live["winner"] = "alice"
            await real_attach(agent_id, "web:winner", "web")
        return await real_attach(agent_id, session_id, channel_type)

    world.threads.attach_session = racing_attach

    response = _open(world)

    assert response.status_code == 200
    assert response.json() == {
        "conversation_id": "winner",
        "agent_thread_id": response.json()["agent_thread_id"],
        "created": False,
    }
    assert conversations.deleted == ["conv_1"]


def test_someone_elses_agent_gets_no_web_conversation(web) -> None:
    world, conversations = web

    assert _open(world, world.bob).status_code == 404
    assert conversations.live == {}

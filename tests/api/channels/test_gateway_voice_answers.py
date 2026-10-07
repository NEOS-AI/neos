"""Q9 x Q15 integration: a voice DM can answer a waiting agent question
(docs/Q9_ASK_AND_WAIT_DESIGN_261005.md §7, docs/Q15_VOICE_DESIGN_261005.md §8).

The gateway order is "transcribe first, then the answer check" (`_route`). The real
ChannelGateway, the real `speech_to_text.transcribe` with a fake OpenAI client
(so the limits run for real and "provider called 0 times" reads its call log), the
in-memory agent/thread/ask stores and the in-memory run repository's
`answer_user_question`.

Prefix decision: the transcript body is `"[voice] <transcript>"` (Q15). The recorded
answer -- what the resumed tool call receives -- drops that marker; the owner's thread
turn keeps the text exactly as transcribed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from neos.api.channels.base import ChannelMessage
from neos.api.channels.gateway import ChannelGateway
from neos.api.channels.media import AudioBytes
from neos.coding.domain.phases import CodingCheckpoint
from neos.config.schema import ChannelPrincipal, ChannelVoiceConfig
from neos.services import speech_to_text
from neos.standing.ask_answers import ChannelAskAnswers
from neos.standing.channel_threads import ChannelAgentThreads
from neos.standing.store import InMemoryStandingAgentStore
from neos.standing.threads import InMemoryAgentThreadStore
from tests.api.channels.conftest import install_channel_settings
from tests.coding.fakes import InMemoryCodingRunRepository

pytestmark = pytest.mark.no_db

OWNER = "u_alice"
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
SLACK_DM = "v2:slack:T1:D_alice:-"
AUDIO = b"OggS-raw-voice-audio-0123456789"
PRINCIPALS = [ChannelPrincipal(platform="slack", platform_user_id="U_alice", user_id=OWNER)]


class FakeTranscriptions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.text = "main"

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.text, languages=[SimpleNamespace(code="en")], usage=None)


class RecordingWorkflow:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute_workflow(self, payload, use_checkpointer=True):
        self.calls.append(payload)
        return {"final_response": f"reply {len(self.calls)}"}


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> FakeTranscriptions:
    fake = FakeTranscriptions()
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=fake))
    monkeypatch.setattr(speech_to_text, "build_async_openai", lambda **_kw: client)
    return fake


def _settings(monkeypatch: pytest.MonkeyPatch, *, voice: ChannelVoiceConfig | None = None):
    installed = install_channel_settings(
        monkeypatch,
        allowed_users=["U_alice"],
        principals=PRINCIPALS,
        voice=voice or ChannelVoiceConfig(enabled=True),
    )
    standing = installed.config.standing_agents
    standing.enabled = True
    standing.threads.enabled = True
    standing.notifications.enabled = True
    standing.ask.enabled = True
    return installed


def _voice_dm(caption: str = "", *, idem: str = "v1") -> ChannelMessage:
    return ChannelMessage(
        user_id=OWNER,
        session_id=SLACK_DM,
        text=caption,
        channel_type="slack",
        channel_id="D_alice",
        metadata={
            "slack_user_id": "U_alice",
            "is_dm": True,
            "idempotency_key": idem,
            "voice": {
                "bytes": AudioBytes(AUDIO),
                "filename": "voice.ogg",
                "content_type": "audio/ogg",
                "duration_seconds": 3.0,
                "refused": None,
            },
        },
    )


class World:
    def __init__(self) -> None:
        self.agents = InMemoryStandingAgentStore()
        self.threads = InMemoryAgentThreadStore(self.agents)
        self.runs = InMemoryCodingRunRepository(task_prompts={"ct_1": "p"})
        self.asks = self.runs.asks
        self.workflow = RecordingWorkflow()
        self.woken: list[tuple[str, str | None]] = []
        self.gateway = ChannelGateway(
            self.workflow,
            agent_threads=ChannelAgentThreads(self.agents, self.threads),
            ask_answers=ChannelAskAnswers(
                self.agents, self.threads, self.asks, resume=self._resume, clock=lambda: NOW
            ),
        )

    async def _resume(self, ask, owner_id, answers, channel_type):
        commit = await self.runs.answer_user_question(
            ask_id=ask.ask_id,
            owner_id=owner_id,
            answers=answers,
            channel_type=channel_type,
            now=NOW,
        )
        if commit is not None:
            self.woken.append((ask.task_id, commit.checkpoint_id))
        return commit

    async def waiting(self, questions=("Which branch?",)):
        agent = await self.agents.create(OWNER, "Dot")
        self.runs.task_statuses["ct_1"] = "waiting_user"
        self.runs.task_owners["ct_1"] = OWNER
        self.runs.checkpoints.append(
            CodingCheckpoint("cc_ask", "ct_1", "cr_1", 7, {"x": 1}, "rev", NOW)
        )
        await self.asks.open(
            agent_id=agent.agent_id,
            task_id="ct_1",
            run_id="cr_1",
            tool_call_id="a1",
            questions=list(questions),
            reply_session_id=SLACK_DM,
            asked_at=NOW,
            expires_at=NOW + timedelta(hours=24),
        )
        return agent

    async def user_turns(self, agent) -> list[str]:
        thread = await self.threads.active(agent.agent_id)
        turns = await self.threads.recent_turns(thread.agent_thread_id, limit=50)
        return [t.content for t in turns if t.role == "user"]


async def test_a_voice_dm_is_transcribed_and_becomes_the_answer(monkeypatch, provider) -> None:
    _settings(monkeypatch)
    world = World()
    agent = await world.waiting()

    reply = await world.gateway.dispatch(_voice_dm())

    assert reply.startswith("Answer recorded — resuming.")
    assert len(provider.calls) == 1  # transcribed before the answer check
    answered = await world.asks.for_call("ct_1", "cr_1", "a1")
    # the answer value drops the "[voice] " marker ...
    assert (answered.status, answered.answers) == ("answered", ("main",))
    assert world.runs.task_statuses["ct_1"] == "running"
    assert world.woken == [("ct_1", "cc_ask")]
    assert world.workflow.calls == []  # an answer is not a chat turn
    # ... the owner's thread turn keeps the text as transcribed.
    assert await world.user_turns(agent) == ["[voice] main"]


async def test_a_spoken_answer_splits_one_line_per_question(monkeypatch, provider) -> None:
    """The marker would otherwise stick to the first answer."""
    _settings(monkeypatch)
    world = World()
    await world.waiting(("Which branch?", "Run the slow tests?"))
    provider.text = "main\nyes"

    reply = await world.gateway.dispatch(_voice_dm())

    assert reply.startswith("Answer recorded")
    answered = await world.asks.for_call("ct_1", "cr_1", "a1")
    assert answered.answers == ("main", "yes")


async def test_a_refused_transcription_does_not_answer(monkeypatch, provider) -> None:
    """Over the byte limit: no provider call, the refusal is the reply, the task waits on."""
    _settings(monkeypatch, voice=ChannelVoiceConfig(enabled=True, max_bytes=len(AUDIO) - 1))
    world = World()
    await world.waiting()

    reply = await world.gateway.dispatch(_voice_dm("main"))

    assert reply == "The voice message is too large to transcribe."
    assert provider.calls == []
    assert (await world.asks.for_call("ct_1", "cr_1", "a1")).status == "waiting"
    assert world.runs.task_statuses["ct_1"] == "waiting_user"
    assert world.woken == []
    assert world.workflow.calls == []

"""Q15c — the real ChannelGateway transcribes a voice message before the conversation
(docs/Q15_VOICE_DESIGN_261005.md §8-§9).

The provider is the real `speech_to_text.transcribe` with a fake OpenAI client
(`build_async_openai` patched), so the limits run for real and "provider called 0
times" reads the fake client's call log. The workflow is a recorder.
"""

from __future__ import annotations

import asyncio
import logging
import pickle
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from neos.api.channels.base import ChannelMessage
from neos.api.channels.gateway import ChannelGateway
from neos.api.channels.media import AudioBytes
from neos.config.schema import ChannelPrincipal, ChannelVoiceConfig
from neos.services import speech_to_text
from neos.standing.channel_threads import ChannelAgentThreads
from neos.standing.store import InMemoryStandingAgentStore
from neos.standing.threads import InMemoryAgentThreadStore
from tests.api.channels.conftest import install_channel_settings

pytestmark = pytest.mark.no_db

OWNER = "u_alice"
SLACK_DM = "v2:slack:T1:D_alice:-"
AUDIO = b"OggS-raw-voice-audio-0123456789"
PRINCIPALS = [ChannelPrincipal(platform="slack", platform_user_id="U_alice", user_id=OWNER)]


class FakeTranscriptions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.text = "hello there"
        self.error: BaseException | None = None
        self.delay = 0.0

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
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


def _settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    voice: ChannelVoiceConfig | None = None,
    principals: list[ChannelPrincipal] | None = None,
    threads: bool = False,
    **kwargs: Any,
):
    installed = install_channel_settings(
        monkeypatch,
        allowed_users=kwargs.pop("allowed_users", ["U_alice"]),
        principals=PRINCIPALS if principals is None else principals,
        voice=voice or ChannelVoiceConfig(enabled=True),
        **kwargs,
    )
    installed.config.standing_agents.enabled = threads
    installed.config.standing_agents.threads.enabled = threads
    return installed


def _voice(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "bytes": AudioBytes(AUDIO),
        "filename": "voice.ogg",
        "content_type": "audio/ogg",
        "duration_seconds": 3.0,
        "refused": None,
    }
    entry.update(overrides)
    return entry


def _message(text: str = "", *, voice: dict[str, Any] | None = None, user: str = "U_alice", idem: str = "m1") -> ChannelMessage:
    metadata: dict[str, Any] = {"slack_user_id": user, "is_dm": True, "idempotency_key": idem}
    metadata["voice"] = _voice() if voice is None else voice
    return ChannelMessage(
        user_id=OWNER,
        session_id=SLACK_DM,
        text=text,
        channel_type="slack",
        channel_id="D_alice",
        metadata=metadata,
    )


def _count(outcome: str) -> float:
    from neos.observability.metrics import metrics

    return metrics.channel_voice_transcriptions_total.labels(outcome=outcome)._value.get()


def _contains_audio(value: Any) -> bool:
    if isinstance(value, (bytes, bytearray)):
        return AUDIO in bytes(value)
    if isinstance(value, str):
        return AUDIO.decode() in value
    if isinstance(value, dict):
        return any(_contains_audio(k) or _contains_audio(v) for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_audio(v) for v in value)
    return False


# ---- the transcript is the message ---------------------------------------------


async def test_transcript_reaches_the_workflow_query(monkeypatch, provider) -> None:
    _settings(monkeypatch)
    workflow = RecordingWorkflow()
    gateway = ChannelGateway(workflow)
    before = _count("ok")

    reply = await gateway.dispatch(_message())

    assert reply == "reply 1"
    assert "[voice] hello there" in workflow.calls[0]["query"]
    assert len(provider.calls) == 1
    assert provider.calls[0]["file"] == ("voice.ogg", AUDIO, "audio/ogg")
    assert _count("ok") == before + 1


async def test_caption_follows_the_transcript(monkeypatch, provider) -> None:
    _settings(monkeypatch)
    workflow = RecordingWorkflow()

    await ChannelGateway(workflow).dispatch(_message("see this"))

    assert "[voice] hello there\n\nsee this" in workflow.calls[0]["query"]


async def test_agent_dm_thread_user_turn_is_the_transcript(monkeypatch, provider) -> None:
    from neos.standing.threads import thread_window

    _settings(monkeypatch, threads=True)
    agents = InMemoryStandingAgentStore()
    threads = InMemoryAgentThreadStore(agents)
    agent = await agents.create(OWNER, "Dot")
    workflow = RecordingWorkflow()
    gateway = ChannelGateway(workflow, agent_threads=ChannelAgentThreads(agents, threads))

    await gateway.dispatch(_message())

    active = await threads.active(agent.agent_id)
    turns = await thread_window(threads, active.agent_thread_id, limit=10)
    assert [(t.role, t.content) for t in turns] == [
        ("user", "[voice] hello there"),
        ("assistant", "reply 1"),
    ]


async def test_spoken_slash_new_is_not_a_command(monkeypatch, provider) -> None:
    _settings(monkeypatch)
    provider.text = "/new please"
    workflow = RecordingWorkflow()

    reply = await ChannelGateway(workflow).dispatch(_message())

    assert reply == "reply 1"
    assert "[voice] /new please" in workflow.calls[0]["query"]


async def test_a_bound_coding_session_steers_with_the_transcript(monkeypatch, provider) -> None:
    _settings(monkeypatch)

    class Steering:
        def __init__(self) -> None:
            self.steered: list[str] = []

        async def steer(self, *, task_id, owner_id, instruction):
            self.steered.append(instruction)
            return "steered"

    coding = Steering()
    workflow = RecordingWorkflow()
    gateway = ChannelGateway(workflow, coding=coding)
    await gateway.bind_session(SLACK_DM, "ct_1", OWNER)

    assert await gateway.dispatch(_message()) == "steered"
    assert workflow.calls == []
    assert len(coding.steered) == 1 and "[voice] hello there" in coding.steered[0]


# ---- refusals: a reply, no workflow --------------------------------------------


@pytest.mark.parametrize(
    ("setup", "expected", "outcome", "provider_calls"),
    [
        ("provider_error", "Could not transcribe the voice message.", "provider_error", 1),
        ("timeout", "Could not transcribe the voice message.", "timeout", 1),
        ("empty", "No speech was found in the voice message.", "empty", 1),
        ("refused_too_large", "The voice message is too large to transcribe.", "too_large", 0),
        ("refused_too_long", "The voice message is too long to transcribe (limit: 600s).", "too_long", 0),
        ("refused_download", "Could not read the voice message.", "download_failed", 0),
        ("bytes_over_limit", "The voice message is too large to transcribe.", "too_large", 0),
        ("duration_over_limit", "The voice message is too long to transcribe (limit: 600s).", "too_long", 0),
        ("unsupported", "This audio format can't be transcribed.", "unsupported_format", 0),
        ("no_bytes", "Could not read the voice message.", "download_failed", 0),
    ],
)
async def test_refusal_replies_and_runs_no_workflow(
    monkeypatch, provider, setup: str, expected: str, outcome: str, provider_calls: int
) -> None:
    voice_config = ChannelVoiceConfig(enabled=True, timeout_seconds=0.05 if setup == "timeout" else 60)
    _settings(monkeypatch, voice=voice_config)
    voice = _voice()
    if setup == "provider_error":
        provider.error = RuntimeError("503")
    elif setup == "timeout":
        provider.delay = 1.0
    elif setup == "empty":
        provider.text = "   "
    elif setup == "refused_too_large":
        voice.update(bytes=None, refused="too_large")
    elif setup == "refused_too_long":
        voice.update(bytes=None, refused="too_long")
    elif setup == "refused_download":
        voice.update(bytes=None, refused="download_failed")
    elif setup == "bytes_over_limit":
        voice_config = ChannelVoiceConfig(enabled=True, max_bytes=len(AUDIO) - 1)
        _settings(monkeypatch, voice=voice_config)
    elif setup == "duration_over_limit":
        voice.update(duration_seconds=601.0)
    elif setup == "unsupported":
        voice.update(filename="voice.amr", content_type="audio/amr")
    elif setup == "no_bytes":
        voice.update(bytes=None)
    workflow = RecordingWorkflow()
    before = _count(outcome)

    reply = await ChannelGateway(workflow).dispatch(_message(voice=voice))

    assert reply == expected
    assert workflow.calls == []
    assert len(provider.calls) == provider_calls
    assert _count(outcome) == before + 1


async def test_a_refusal_writes_no_thread_turn(monkeypatch, provider) -> None:
    _settings(monkeypatch, threads=True)
    provider.error = RuntimeError("down")
    agents = InMemoryStandingAgentStore()
    threads = InMemoryAgentThreadStore(agents)
    agent = await agents.create(OWNER, "Dot")
    gateway = ChannelGateway(RecordingWorkflow(), agent_threads=ChannelAgentThreads(agents, threads))

    await gateway.dispatch(_message())

    assert await threads.list_threads(agent.agent_id) == []


# ---- Review Focus 5 (gateway side): an unmapped sender is never transcribed ----


async def test_unmapped_sender_is_not_transcribed(monkeypatch, provider) -> None:
    _settings(monkeypatch, allowed_users=["U_alice", "U_mallory"])
    workflow = RecordingWorkflow()

    reply = await ChannelGateway(workflow).dispatch(_message(user="U_mallory"))

    assert reply == "Owner is not configured."
    assert provider.calls == []
    assert workflow.calls == []


async def test_without_principals_the_sender_is_transcribed(monkeypatch, provider) -> None:
    _settings(monkeypatch, principals=[])
    workflow = RecordingWorkflow()

    await ChannelGateway(workflow).dispatch(_message())

    assert len(provider.calls) == 1
    assert "[voice] hello there" in workflow.calls[0]["query"]


# ---- what is not transcribed ---------------------------------------------------


async def test_a_command_caption_ignores_the_voice(monkeypatch, provider) -> None:
    _settings(monkeypatch)
    workflow = RecordingWorkflow()

    reply = await ChannelGateway(workflow).dispatch(_message("/help"))

    assert provider.calls == []
    assert workflow.calls == []
    assert "/new" in reply or "help" in reply.lower()


async def test_flag_off_never_calls_the_provider(monkeypatch, provider) -> None:
    _settings(monkeypatch, voice=ChannelVoiceConfig(enabled=False))
    workflow = RecordingWorkflow()

    await ChannelGateway(workflow).dispatch(_message("caption only"))

    assert provider.calls == []
    assert "[voice]" not in workflow.calls[0]["query"]
    assert "caption only" in workflow.calls[0]["query"]


async def test_a_retry_with_the_same_idempotency_key_does_not_transcribe_again(monkeypatch, provider) -> None:
    _settings(monkeypatch)
    gateway = ChannelGateway(RecordingWorkflow())

    first = await gateway.dispatch(_message(idem="same"))
    second = await gateway.dispatch(_message(idem="same"))

    assert first == second
    assert len(provider.calls) == 1


async def test_a_parked_voice_is_transcribed_when_it_folds(monkeypatch, provider) -> None:
    _settings(monkeypatch)
    workflow = RecordingWorkflow()
    gateway = ChannelGateway(workflow)
    assert gateway._inflight.acquire(SLACK_DM)

    await gateway.dispatch(_message())
    assert provider.calls == []
    gateway._inflight.release(SLACK_DM)
    await gateway._fold_parked(SLACK_DM)

    assert len(provider.calls) == 1
    assert "[voice] hello there" in workflow.calls[0]["query"]


# ---- the audio goes to the provider and nowhere else ---------------------------


async def test_audio_bytes_are_not_in_the_workflow_input(monkeypatch, provider) -> None:
    _settings(monkeypatch, inbound_media=True)
    workflow = RecordingWorkflow()
    message = _message()
    message.metadata["attachments"] = [
        {"name": "a.txt", "content_type": "text/plain", "bytes": b"note", "size": 4}
    ]

    await ChannelGateway(workflow).dispatch(message)

    payload = workflow.calls[0]
    assert not _contains_audio(payload)
    assert [b["name"] for b in payload["channel_attachments"]] == ["a.txt"]


async def test_audio_bytes_are_dropped_from_the_message_after_transcription(monkeypatch, provider) -> None:
    _settings(monkeypatch)
    message = _message()

    await ChannelGateway(RecordingWorkflow()).dispatch(message)

    assert message.metadata["voice"]["bytes"] is None


@pytest.mark.parametrize("fail", [False, True])
async def test_audio_bytes_never_reach_a_log_line(monkeypatch, provider, caplog, fail: bool) -> None:
    _settings(monkeypatch)
    if fail:
        provider.error = RuntimeError("boom")
    caplog.set_level(logging.DEBUG)
    message = _message()
    # 누군가 메시지를 통째로 찍는다면 — 오디오가 아직 실려 있을 때(전사 전) 형식화한다.
    logging.getLogger("test.q15").info(f"message={message!r} metadata={message.metadata}")

    await ChannelGateway(RecordingWorkflow()).dispatch(message)

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert AUDIO.decode() not in text
    assert "<audio: " in text


async def test_audio_bytes_are_not_stored_in_the_inbound_idempotency_record(monkeypatch, provider) -> None:
    _settings(monkeypatch)
    gateway = ChannelGateway(RecordingWorkflow())

    await gateway.dispatch(_message(idem="k1"))

    record = await gateway._inbound.get(SLACK_DM, "k1")
    assert not _contains_audio(record.outcome)


def test_audio_bytes_redact_their_repr_and_refuse_to_pickle() -> None:
    audio = AudioBytes(AUDIO)

    assert audio == AUDIO
    assert AUDIO.decode() not in repr(audio)
    assert AUDIO.decode() not in str(audio)
    assert AUDIO.decode() not in repr(_message())
    with pytest.raises(TypeError):
        pickle.dumps(audio)


# ---- Review Focus 5 (adapter side): outside the gate nothing is downloaded or sent ----


def _real_gateway() -> tuple[ChannelGateway, RecordingWorkflow]:
    workflow = RecordingWorkflow()
    return ChannelGateway(workflow), workflow


async def test_telegram_ignored_chat_voice_is_never_downloaded_or_sent(monkeypatch, provider) -> None:
    from neos.api.channels.adapters.telegram import TelegramAdapter

    _settings(monkeypatch, allowed_users=["12345"], principals=[], ignored_channels=["12345"], require_mention=False)
    gateway, workflow = _real_gateway()
    adapter, get_file, fetch_calls = _telegram_adapter(TelegramAdapter, gateway)

    await adapter._handle_message(_telegram_voice_update(), None)

    get_file.assert_not_awaited()
    assert fetch_calls == []
    assert provider.calls == []
    assert workflow.calls == []


async def test_telegram_bot_voice_is_never_downloaded_or_sent(monkeypatch, provider) -> None:
    from neos.api.channels.adapters.telegram import TelegramAdapter

    _settings(monkeypatch, allowed_users=["12345"], principals=[], require_mention=False)
    gateway, workflow = _real_gateway()
    adapter, get_file, fetch_calls = _telegram_adapter(TelegramAdapter, gateway)

    await adapter._handle_message(_telegram_voice_update(is_bot=True), None)

    get_file.assert_not_awaited()
    assert fetch_calls == []
    assert provider.calls == []
    assert workflow.calls == []


async def test_telegram_admitted_voice_reaches_the_provider(monkeypatch, provider) -> None:
    from neos.api.channels.adapters.telegram import TelegramAdapter

    _settings(monkeypatch, allowed_users=["12345"], principals=[], require_mention=False)
    gateway, workflow = _real_gateway()
    adapter, get_file, fetch_calls = _telegram_adapter(TelegramAdapter, gateway)

    await adapter._handle_message(_telegram_voice_update(), None)

    get_file.assert_awaited_once()
    assert len(fetch_calls) == 1
    assert len(provider.calls) == 1
    assert "[voice] hello there" in workflow.calls[0]["query"]


def _telegram_adapter(adapter_cls, gateway):
    adapter = adapter_cls(token="test-token", gateway=gateway)
    get_file = AsyncMock(return_value=SimpleNamespace(file_path="voice/file_1.oga"))
    adapter._app = SimpleNamespace(
        bot=SimpleNamespace(
            username="neos_bot", id=999, send_message=AsyncMock(), get_file=get_file, token="t"
        )
    )
    fetch_calls: list[str] = []

    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        fetch_calls.append(url)
        return 200, AUDIO

    adapter._media_fetch = fetch
    adapter._media_resolve = lambda _host: ["1.2.3.4"]
    return adapter, get_file, fetch_calls


def _telegram_voice_update(*, is_bot: bool = False) -> SimpleNamespace:
    chat = SimpleNamespace(id=12345, type="private", send_action=AsyncMock(), send_message=AsyncMock())
    user = SimpleNamespace(id=12345, is_bot=is_bot, username="alice")
    message = SimpleNamespace(
        text=None,
        caption=None,
        entities=[],
        message_id=7,
        message_thread_id=None,
        photo=None,
        document=None,
        video=None,
        voice=SimpleNamespace(file_id="v1", duration=2, mime_type="audio/ogg", file_size=len(AUDIO)),
        audio=None,
    )
    return SimpleNamespace(effective_chat=chat, effective_user=user, effective_message=message, update_id=77)


async def test_slack_ignored_channel_and_bot_voice_never_reach_the_provider(monkeypatch, provider) -> None:
    from neos.api.channels.adapters.slack import SlackAdapter

    _settings(monkeypatch, principals=[], ignored_channels=["C_ignored"], require_mention=False)
    gateway, workflow = _real_gateway()
    adapter = SlackAdapter(token="xoxb-test", gateway=gateway)
    adapter._bot_user_id = "U_BOT"
    fetch_calls: list[str] = []

    async def fetch(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        fetch_calls.append(url)
        return 200, AUDIO

    adapter._media_fetch = fetch
    adapter._media_resolve = lambda _host: ["1.2.3.4"]
    audio_file = {
        "id": "F1",
        "mimetype": "audio/webm",
        "name": "clip.webm",
        "size": len(AUDIO),
        "url_private": "https://files.slack.com/files-pri/T/F1",
    }
    base = {"user": "U_alice", "text": "", "ts": "1.0", "subtype": "file_share", "files": [audio_file]}

    await adapter._handle_message({**base, "channel": "C_ignored"}, AsyncMock(), client=None)
    await adapter._handle_message({**base, "channel": "D_alice", "channel_type": "im", "bot_id": "B1"}, AsyncMock(), client=None)

    assert fetch_calls == []
    assert provider.calls == []
    assert workflow.calls == []


async def test_discord_ignored_channel_and_bot_voice_never_reach_the_provider(monkeypatch, provider) -> None:
    from tests.api.channels.test_discord_adapter import CHANNEL_ID, FakeChannel, _adapter, _author, _message as _dmessage

    _settings(
        monkeypatch,
        allowed_users=["1001"],
        principals=[],
        ignored_channels=[str(CHANNEL_ID)],
        require_mention=False,
    )
    gateway, workflow = _real_gateway()
    channel = FakeChannel(CHANNEL_ID)
    adapter = _adapter(gateway, channel)
    reads: list[int] = []

    async def read() -> bytes:
        reads.append(1)
        return AUDIO

    attachment = SimpleNamespace(
        filename="voice-message.ogg", content_type="audio/ogg", size=len(AUDIO), duration=2.0, read=read
    )
    ignored = _dmessage(content="", channel=channel)
    ignored.attachments = [attachment]
    bot = _dmessage(content="", channel=channel, guild=None, author=_author(bot=True))
    bot.attachments = [attachment]

    await adapter._handle_message(ignored)
    await adapter._handle_message(bot)

    assert reads == []
    assert provider.calls == []
    assert workflow.calls == []

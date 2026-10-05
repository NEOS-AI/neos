"""Q15a — 상한 뒤의 전사 클라이언트(설계 `docs/Q15_VOICE_DESIGN_261005.md` §7).

공급자는 늘 가짜다. 실제 OpenAI 를 부르지 않는다.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from neos.config.schema import AppConfig, ChannelVoiceConfig
from neos.services import speech_to_text
from neos.services.speech_to_text import (
    REFUSAL_REASONS,
    Transcription,
    TranscriptionRefused,
    transcribe,
)

pytestmark = pytest.mark.no_db

_OGG = b"OggS" + b"\x00" * 60


class _FakeTranscriptions:
    def __init__(self, *, result: Any = None, error: BaseException | None = None, delay: float = 0.0):
        self.calls: list[dict[str, Any]] = []
        self._result = result
        self._error = error
        self._delay = delay

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._result


class _FakeClient:
    def __init__(self, **kwargs: Any) -> None:
        self.audio = SimpleNamespace(transcriptions=_FakeTranscriptions(**kwargs))

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.audio.transcriptions.calls


def _result(text: str = "hello there", *, languages=("en",), seconds: float | None = None):
    usage = SimpleNamespace(type="duration", seconds=seconds) if seconds is not None else None
    return SimpleNamespace(
        text=text,
        languages=[SimpleNamespace(code=code) for code in languages] if languages is not None else None,
        usage=usage,
    )


def _config(**overrides: Any) -> ChannelVoiceConfig:
    return ChannelVoiceConfig(enabled=True, **overrides)


async def _run(client: _FakeClient, audio: bytes = _OGG, **kwargs: Any) -> Transcription:
    params: dict[str, Any] = {
        "filename": "voice.ogg",
        "content_type": "audio/ogg",
        "duration_seconds": 3.0,
        "config": _config(),
        "client": client,
    }
    params.update(kwargs)
    return await transcribe(audio, **params)


# ---- 정상 전사 ----


async def test_transcribes_text_language_and_duration() -> None:
    client = _FakeClient(result=_result("  hello there  ", languages=("ko", "en")))

    result = await _run(client)

    assert result == Transcription(text="hello there", language="ko", duration_seconds=3.0)
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["file"] == ("voice.ogg", _OGG, "audio/ogg")
    assert call["response_format"] == "json"


async def test_provider_reported_duration_wins_over_channel_duration() -> None:
    client = _FakeClient(result=_result(seconds=4.5))

    result = await _run(client, duration_seconds=3.0)

    assert result.duration_seconds == 4.5


async def test_no_language_detected_is_none() -> None:
    client = _FakeClient(result=_result(languages=()))

    result = await _run(client, duration_seconds=None)

    assert result.language is None
    assert result.duration_seconds is None


async def test_model_comes_from_the_catalog_transcription_default() -> None:
    from neos.config.model_config import model_config

    catalog = model_config.catalog
    expected = catalog.resolve_alias("transcription", catalog.defaults["transcription"])
    client = _FakeClient(result=_result())

    await _run(client)

    assert expected == "gpt-transcribe"
    assert client.calls[0]["model"] == "gpt-transcribe"


async def test_provider_timeout_is_passed_to_the_request() -> None:
    client = _FakeClient(result=_result())

    await _run(client, config=_config(timeout_seconds=7))

    assert client.calls[0]["timeout"] == 7


# ---- Review Focus 4: 상한은 공급자보다 먼저 ----


async def test_over_max_bytes_refuses_without_calling_the_provider() -> None:
    client = _FakeClient(result=_result())

    with pytest.raises(TranscriptionRefused) as refused:
        await _run(client, audio=b"x" * 101, config=_config(max_bytes=100))

    assert refused.value.reason == "too_large"
    assert client.calls == []


async def test_exactly_max_bytes_is_allowed() -> None:
    client = _FakeClient(result=_result())

    await _run(client, audio=b"x" * 100, config=_config(max_bytes=100))

    assert len(client.calls) == 1


async def test_over_max_seconds_refuses_without_calling_the_provider() -> None:
    client = _FakeClient(result=_result())

    with pytest.raises(TranscriptionRefused) as refused:
        await _run(client, duration_seconds=601.0, config=_config(max_seconds=600))

    assert refused.value.reason == "too_long"
    assert client.calls == []


async def test_exactly_max_seconds_is_allowed() -> None:
    client = _FakeClient(result=_result())

    await _run(client, duration_seconds=600.0, config=_config(max_seconds=600))

    assert len(client.calls) == 1


async def test_unknown_duration_skips_the_length_check() -> None:
    client = _FakeClient(result=_result())

    await _run(client, duration_seconds=None, config=_config(max_seconds=1))

    assert len(client.calls) == 1


async def test_refusal_happens_before_the_client_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[dict[str, Any]] = []

    def _factory(**kwargs: Any) -> Any:
        built.append(kwargs)
        return _FakeClient(result=_result())

    monkeypatch.setattr(speech_to_text, "build_async_openai", _factory)

    with pytest.raises(TranscriptionRefused):
        await transcribe(
            b"x" * 101,
            filename="voice.ogg",
            content_type="audio/ogg",
            duration_seconds=None,
            config=_config(max_bytes=100),
        )

    assert built == []


async def test_default_client_disables_sdk_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[dict[str, Any]] = []
    client = _FakeClient(result=_result())

    def _factory(**kwargs: Any) -> Any:
        built.append(kwargs)
        return client

    monkeypatch.setattr(speech_to_text, "build_async_openai", _factory)

    await transcribe(
        _OGG,
        filename="voice.ogg",
        content_type="audio/ogg",
        duration_seconds=None,
        config=_config(),
    )

    assert built == [{"max_retries": 0}]
    assert len(client.calls) == 1


# ---- 형식 ----


@pytest.mark.parametrize(
    ("filename", "content_type", "expected_name", "expected_type"),
    [
        ("voice.ogg", "audio/ogg; codecs=opus", "voice.ogg", "audio/ogg"),
        ("voice", "audio/ogg", "voice.ogg", "audio/ogg"),
        ("voice", "audio/ogg; codecs=opus", "voice.ogg", "audio/ogg"),
        ("voice", " Audio/OGG ", "voice.ogg", "audio/ogg"),
        ("clip.m4a", "application/octet-stream", "clip.m4a", "audio/mp4"),
        ("clip", "audio/mpeg", "clip.mp3", "audio/mpeg"),
        ("clip.webm", "audio/webm", "clip.webm", "audio/webm"),
        ("clip.WAV", "audio/x-wav", "clip.WAV", "audio/wav"),
        ("clip", "video/mp4", "clip.mp4", "video/mp4"),
    ],
)
async def test_supported_formats_reach_the_provider_with_an_extension(
    filename: str, content_type: str, expected_name: str, expected_type: str
) -> None:
    client = _FakeClient(result=_result())

    await _run(client, filename=filename, content_type=content_type)

    name, _, sent_type = client.calls[0]["file"]
    assert name == expected_name
    assert sent_type == expected_type


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("voice.amr", "audio/amr"),
        ("file", "application/octet-stream"),
        ("photo.jpg", "image/jpeg"),
        ("", ""),
    ],
)
async def test_unsupported_format_refuses_without_calling_the_provider(
    filename: str, content_type: str
) -> None:
    client = _FakeClient(result=_result())

    with pytest.raises(TranscriptionRefused) as refused:
        await _run(client, filename=filename, content_type=content_type)

    assert refused.value.reason == "unsupported_format"
    assert client.calls == []


# ---- 실패 ----


async def test_slow_provider_is_a_timeout() -> None:
    client = _FakeClient(result=_result(), delay=1.0)

    with pytest.raises(TranscriptionRefused) as refused:
        await _run(client, config=_config(timeout_seconds=0.05))

    assert refused.value.reason == "timeout"


async def test_sdk_timeout_error_is_a_timeout() -> None:
    import httpx
    import openai

    error = openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions"))
    client = _FakeClient(error=error)

    with pytest.raises(TranscriptionRefused) as refused:
        await _run(client)

    assert refused.value.reason == "timeout"


@pytest.mark.parametrize("error", [RuntimeError("boom"), ValueError("bad request")])
async def test_provider_exception_is_a_provider_error(error: BaseException) -> None:
    client = _FakeClient(error=error)

    with pytest.raises(TranscriptionRefused) as refused:
        await _run(client)

    assert refused.value.reason == "provider_error"
    assert len(client.calls) == 1


async def test_provider_status_error_is_a_provider_error() -> None:
    import httpx
    import openai

    request = httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")
    error = openai.BadRequestError(
        "unsupported", response=httpx.Response(400, request=request), body=None
    )
    client = _FakeClient(error=error)

    with pytest.raises(TranscriptionRefused) as refused:
        await _run(client)

    assert refused.value.reason == "provider_error"


@pytest.mark.parametrize("text", ["", "   \n\t "])
async def test_empty_transcript_is_refused(text: str) -> None:
    client = _FakeClient(result=_result(text))

    with pytest.raises(TranscriptionRefused) as refused:
        await _run(client)

    assert refused.value.reason == "empty"


async def test_response_without_text_is_empty() -> None:
    client = _FakeClient(result=SimpleNamespace())

    with pytest.raises(TranscriptionRefused) as refused:
        await _run(client)

    assert refused.value.reason == "empty"


# ---- 이름 ----


def test_refusal_reasons_are_fixed() -> None:
    assert REFUSAL_REASONS == frozenset(
        {"too_large", "too_long", "unsupported_format", "provider_error", "timeout", "empty"}
    )


def test_unknown_refusal_reason_is_rejected() -> None:
    with pytest.raises(ValueError):
        TranscriptionRefused("nope")


# ---- 설정 ----


def test_voice_config_defaults_off() -> None:
    voice = AppConfig().channels.voice
    assert voice.enabled is False
    assert voice.max_bytes == 25_000_000
    assert voice.max_seconds == 600
    assert voice.timeout_seconds == 60


def test_voice_max_bytes_cannot_exceed_the_provider_limit() -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"channels": {"voice": {"max_bytes": 25_000_001}}})


@pytest.mark.parametrize(
    "voice",
    [{"max_bytes": 0}, {"max_seconds": 0}, {"timeout_seconds": 0}, {"model": "whisper-1"}],
)
def test_voice_config_rejects_bad_values_and_unknown_keys(voice: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"channels": {"voice": voice}})


def test_voice_config_loads_when_enabled() -> None:
    config = AppConfig.model_validate(
        {"channels": {"voice": {"enabled": True, "max_bytes": 1000, "max_seconds": 30, "timeout_seconds": 5}}}
    )
    assert config.channels.voice.enabled is True
    assert config.channels.voice.max_bytes == 1000


# ---- 카탈로그 · 계측 ----


def test_catalog_entry_is_internal_and_unpriced() -> None:
    from neos.config.model_config import model_config

    spec = model_config.catalog.models["gpt-transcribe"]
    assert spec.provider == "openai"
    assert spec.selectable is False
    assert spec.pricing is None
    assert spec.picker is None


def test_transcription_model_stays_out_of_the_fe_catalog() -> None:
    from pathlib import Path

    generated = Path("web/lib/ai/catalog.generated.ts").read_text(encoding="utf-8")
    assert "gpt-transcribe" not in generated


def test_transcription_counter_is_registered() -> None:
    from neos.observability.metrics import metrics

    counter = metrics.channel_voice_transcriptions_total
    before = counter.labels(outcome="ok")._value.get()
    counter.labels(outcome="ok").inc()
    assert counter.labels(outcome="ok")._value.get() == before + 1

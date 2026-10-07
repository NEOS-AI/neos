"""채널 음성 → 텍스트(Q15a). 공급자 = OpenAI 전사 API.

설계 `docs/Q15_VOICE_DESIGN_261005.md` §7. 규칙:

- **상한을 먼저 본다.** 크기 → 길이(아는 경우만) → 형식 순으로 보고, 하나라도 걸리면
  클라이언트를 만들지도 부르지도 않고 `TranscriptionRefused` 를 던진다
- 모델은 설정이 아니라 카탈로그(`aliases.transcription` / `defaults.transcription`)가 고른다
- 재시도하지 않는다(SDK 재시도도 끈다). 시간 상한 = 사용자 대기 시간이고, 재시도는 같은
  오디오로 비용을 두 번 낸다
- 오디오 바이트와 전사 내용은 로그에 남기지 않는다
- 계측(`channel_voice_transcriptions_total`)은 여기서 하지 않는다 — 게이트웨이 한 곳이 센다(Q15c)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from neos.utils.openai_client import build_async_openai

if TYPE_CHECKING:
    from neos.config.schema import ChannelVoiceConfig

logger = logging.getLogger(__name__)

REFUSAL_REASONS = frozenset(
    {"too_large", "too_long", "unsupported_format", "provider_error", "timeout", "empty"}
)

# 공급자가 받는 형식 — API 레퍼런스 `file` 파라미터(2026-10-05 조회):
# https://developers.openai.com/api/reference/python/resources/audio/subresources/transcriptions/methods/create
# 가이드는 ogg·flac 을 빼먹었다(설계 §4). 그래서 development 에서도 켜기 전에 라이브 dry run 이 필요하다.
_EXTENSION_CONTENT_TYPE: dict[str, str] = {
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
    "mp4": "video/mp4",
    "mpeg": "audio/mpeg",
    "mpga": "audio/mpeg",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "wav": "audio/wav",
    "webm": "audio/webm",
}

# 채널이 주는 MIME → 확장자. 매개변수(`; codecs=opus`)는 떼고 본다.
_CONTENT_TYPE_EXTENSION: dict[str, str] = {
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mpga": "mpga",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "video/mp4": "mp4",
    "video/webm": "webm",
}


@dataclass(frozen=True, slots=True)
class Transcription:
    text: str
    language: str | None
    duration_seconds: float | None


class TranscriptionRefused(Exception):
    """전사하지 않았다(또는 못 했다). `reason` 은 `REFUSAL_REASONS` 중 하나."""

    def __init__(self, reason: str) -> None:
        if reason not in REFUSAL_REASONS:
            raise ValueError(f"unknown transcription refusal reason: {reason!r}")
        self.reason = reason
        super().__init__(reason)


def transcription_model() -> str:
    """카탈로그가 고른 전사 모델의 wire id."""
    from neos.config.model_config import model_config

    catalog = model_config.catalog
    pin = catalog.resolve_alias("transcription", catalog.defaults["transcription"])
    spec = catalog.models[pin]
    return spec.wire_id or pin


def _upload_name_and_type(filename: str, content_type: str) -> tuple[str, str] | None:
    """공급자가 형식을 알아볼 수 있는 (확장자 있는 이름, MIME). 목록 밖이면 None."""
    name = (filename or "").strip()
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    stem, dot, ext = name.rpartition(".")
    ext = ext.lower() if dot and stem else ""
    if ext in _EXTENSION_CONTENT_TYPE:
        return name, _EXTENSION_CONTENT_TYPE[ext]
    mapped = _CONTENT_TYPE_EXTENSION.get(mime)
    if not mapped:
        return None
    return f"{name or 'audio'}.{mapped}", _EXTENSION_CONTENT_TYPE[mapped]


def _language(response: Any) -> str | None:
    languages = getattr(response, "languages", None) or []
    for item in languages:
        code = getattr(item, "code", None)
        if code:
            return str(code)
    return None


def _duration(response: Any, fallback: float | None) -> float | None:
    usage = getattr(response, "usage", None)
    if usage is not None and getattr(usage, "type", None) == "duration":
        seconds = getattr(usage, "seconds", None)
        if seconds is not None:
            return float(seconds)
    return fallback


async def transcribe(
    audio: bytes,
    *,
    filename: str,
    content_type: str,
    duration_seconds: float | None,
    config: ChannelVoiceConfig,
    client: Any = None,
) -> Transcription:
    # 1) 상한 — 공급자에 아무것도 보내기 전에.
    if len(audio) > config.max_bytes:
        raise TranscriptionRefused("too_large")
    if duration_seconds is not None and duration_seconds > config.max_seconds:
        raise TranscriptionRefused("too_long")
    upload = _upload_name_and_type(filename, content_type)
    if upload is None:
        raise TranscriptionRefused("unsupported_format")
    upload_name, upload_type = upload

    # 2) 공급자.
    import openai

    try:
        if client is None:
            client = build_async_openai(max_retries=0)
        response = await asyncio.wait_for(
            client.audio.transcriptions.create(
                file=(upload_name, audio, upload_type),
                model=transcription_model(),
                response_format="json",
                timeout=config.timeout_seconds,
            ),
            timeout=config.timeout_seconds,
        )
    except (asyncio.TimeoutError, openai.APITimeoutError):
        logger.info("[speech-to-text] timeout after %ss", config.timeout_seconds)
        raise TranscriptionRefused("timeout") from None
    except Exception as exc:  # noqa: BLE001 -- 공급자 실패는 모두 거절 하나로
        logger.warning("[speech-to-text] provider error: %s", type(exc).__name__)
        raise TranscriptionRefused("provider_error") from exc

    text = str(getattr(response, "text", "") or "").strip()
    if not text:
        raise TranscriptionRefused("empty")
    return Transcription(
        text=text,
        language=_language(response),
        duration_seconds=_duration(response, duration_seconds),
    )

"""OpenAI 클라이언트를 짓는 단 한 곳.

코딩 루프와 LangChain 바깥의 네이티브 SDK 호출이 각자 `AsyncOpenAI(...)` 를
만들지 않도록 모은다. Anthropic 의 `build_async_anthropic` 과 같은 역할이다.
"""

from __future__ import annotations

from openai import AsyncOpenAI

from neos.config.settings import settings


def build_async_openai(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs,
) -> AsyncOpenAI:
    resolved_key = (
        api_key
        if api_key is not None
        else getattr(settings, "OPENAI_API_KEY", None)
    )
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncOpenAI(api_key=resolved_key, **kwargs)

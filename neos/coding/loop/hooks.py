"""Loop hook helpers. Default missing methods stay silent."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NotRequired, Protocol, TypedDict

from neos.coding.model.base import CanonicalMessage


class CompactInstruction(TypedDict):
    instruction: NotRequired[str]


class GenerateNote(TypedDict):
    system: NotRequired[str]
    append: NotRequired[str]


class CompactHookPort(Protocol):
    async def pre_compact(
        self, before: Sequence[CanonicalMessage]
    ) -> CompactInstruction | str | None: ...

    async def post_compact(
        self,
        before: Sequence[CanonicalMessage],
        after: Sequence[CanonicalMessage],
    ) -> CompactInstruction | str | None: ...


def compact_instruction_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        raw = value.get("instruction")
        if raw is None:
            raw = value.get("text")
        if isinstance(raw, str):
            return raw.strip()
    return ""


async def invoke_pre_compact(hooks: object, before: Sequence[CanonicalMessage]) -> str:
    method = getattr(hooks, "pre_compact", None)
    if not callable(method):
        return ""
    try:
        return compact_instruction_text(await method(before))
    except Exception:
        return ""


async def invoke_post_compact(
    hooks: object,
    before: Sequence[CanonicalMessage],
    after: Sequence[CanonicalMessage],
) -> str:
    method = getattr(hooks, "post_compact", None)
    if not callable(method):
        return ""
    try:
        return compact_instruction_text(await method(before, after))
    except Exception:
        return ""


def generate_note_parts(value: object) -> GenerateNote:
    system = ""
    append = ""
    if isinstance(value, str):
        append = value.strip()
    elif isinstance(value, Mapping):
        raw_system = value.get("system")
        raw_append = value.get("append")
        if isinstance(raw_system, str):
            system = raw_system.strip()
        if isinstance(raw_append, str):
            append = raw_append.strip()
    return {"system": system, "append": append}


async def invoke_pre_generate(
    hooks: object, transcript: Sequence[CanonicalMessage]
) -> GenerateNote:
    method = getattr(hooks, "pre_generate", None)
    if not callable(method):
        return {"system": "", "append": ""}
    try:
        return generate_note_parts(await method(transcript))
    except Exception:
        return {"system": "", "append": ""}


async def invoke_post_generate(
    hooks: object,
    text: str,
    transcript: Sequence[CanonicalMessage],
) -> None:
    method = getattr(hooks, "post_generate", None)
    if not callable(method):
        return None
    try:
        await method(text, transcript)
    except Exception:
        return None
    return None

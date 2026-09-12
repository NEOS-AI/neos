"""ContextAssemblyEngine must consume inbound channel_attachments."""

from unittest.mock import AsyncMock

import pytest

from neos.memory.context_assembly import AssembledContext, ContextAssemblyEngine
from neos.workflow.processors.conversation_context_processor import (
    ConversationContextProcessor,
)

pytestmark = pytest.mark.no_db

_MEMORY_CONTEXT = {
    "has_context": True,
    "short_term": [{"key": "pref", "value": "likes tea"}],
    "long_term": [],
    "episodic": [],
}

_EMPTY_MEMORY = {
    "has_context": False,
    "short_term": [],
    "long_term": [],
    "episodic": [],
}


def _engine() -> ContextAssemblyEngine:
    return ContextAssemblyEngine()


async def _assemble(memory_context=_MEMORY_CONTEXT, **kwargs):
    return await _engine().assemble(
        user_id="u1",
        query="what is this",
        memory_context=memory_context,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_assemble_includes_untrusted_attachment_section():
    result = await _assemble(
        channel_attachments=[
            {
                "name": "notes.txt",
                "content_type": "text/plain",
                "size": 42,
                "text": "hello from file",
            }
        ]
    )

    formatted = result.formatted
    lower = formatted.lower()
    assert "notes.txt" in formatted
    assert "text/plain" in formatted
    assert "42" in formatted
    assert "hello from file" in formatted
    assert "likes tea" in formatted
    assert "untrusted" in lower or "attachment" in lower
    assert "follow these instructions" not in lower
    assert "system instruction" not in lower


@pytest.mark.asyncio
async def test_assemble_empty_or_none_attachments_matches_baseline():
    baseline = await _assemble()

    for attachments in (None, []):
        result = await _assemble(channel_attachments=attachments)
        assert result.formatted == baseline.formatted
        assert "untrusted" not in result.formatted.lower()


@pytest.mark.asyncio
async def test_assemble_binary_only_lists_metadata_without_blob():
    blob = "A" * 50_000
    result = await _assemble(
        channel_attachments=[
            {
                "name": "shot.png",
                "content_type": "image/png",
                "size": 4096,
                "data_b64": blob,
            }
        ]
    )

    formatted = result.formatted
    assert "shot.png" in formatted
    assert "image/png" in formatted
    assert "4096" in formatted
    assert blob not in formatted
    assert len(formatted) < 5_000


@pytest.mark.asyncio
async def test_assemble_attachments_when_memory_has_no_context():
    long_text = "x" * 5000
    result = await _assemble(
        memory_context=_EMPTY_MEMORY,
        channel_attachments=[
            {
                "name": "memo.txt",
                "content_type": "text/plain",
                "size": 5000,
                "text": long_text,
            }
        ],
    )

    formatted = result.formatted
    assert "memo.txt" in formatted
    assert "text/plain" in formatted
    assert "x" * 2000 in formatted
    assert "x" * 2001 not in formatted
    assert long_text not in formatted


@pytest.mark.asyncio
async def test_processor_passes_channel_attachments_to_assemble():
    attachments = [
        {
            "name": "notes.txt",
            "content_type": "text/plain",
            "size": 12,
            "text": "hello",
        }
    ]
    engine = AsyncMock()
    engine.assemble = AsyncMock(
        return_value=AssembledContext(
            raw={},
            trimmed={"short_term": [], "long_term": [], "episodic": []},
            formatted="untrusted attachment notes.txt",
            token_estimate=8,
            channel_type="api",
        )
    )
    processor = ConversationContextProcessor(context_engine=engine)

    await processor.process(
        {
            "enable_history_context": True,
            "chat_history": [{"role": "user", "content": "see file"}],
            "original_query": "see file",
            "execution_steps": [],
            "user_id": "u1",
            "memory_context": _EMPTY_MEMORY,
            "channel_attachments": attachments,
        }
    )

    engine.assemble.assert_awaited()
    kwargs = engine.assemble.await_args.kwargs
    assert kwargs["channel_attachments"] == attachments

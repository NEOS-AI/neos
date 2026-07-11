import asyncio
import os

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from neos.pipelines.document.chunker import DocumentChunk
from neos.pipelines.document.contextual_retrieval import ContextualChunk, ContextualRetrieval

pytestmark = pytest.mark.no_db


def chunk(index: int) -> DocumentChunk:
    text = f"chunk-{index}"
    return DocumentChunk(chunk_index=index, chunk_text=text, chunk_size=len(text))


@pytest.mark.asyncio
async def test_first_chunk_completes_before_parallel_fanout(monkeypatch):
    retrieval = ContextualRetrieval(max_concurrent=3, max_chunks_per_doc=10)
    events: list[tuple[str, int]] = []

    async def fake_generate(*, full_document, chunk, chunk_index):
        events.append(("start", chunk_index))
        await asyncio.sleep(0)
        events.append(("finish", chunk_index))
        return ContextualChunk(
            original_chunk=chunk,
            contextual_text=chunk.chunk_text,
            context_snippet=f"context-{chunk_index}",
        )

    monkeypatch.setattr(retrieval, "_generate_context_for_chunk", fake_generate)
    result = await retrieval.generate_contexts(
        "document", [chunk(0), chunk(1), chunk(2)]
    )

    assert events.index(("finish", 0)) < events.index(("start", 1))
    assert events.index(("finish", 0)) < events.index(("start", 2))
    assert [item.original_chunk.chunk_index for item in result] == [0, 1, 2]


@pytest.mark.asyncio
async def test_first_chunk_failure_falls_back_before_parallel_fanout(monkeypatch):
    retrieval = ContextualRetrieval(max_concurrent=3, max_chunks_per_doc=10)
    events: list[tuple[str, int]] = []

    async def fake_generate(*, full_document, chunk, chunk_index):
        events.append(("start", chunk_index))
        await asyncio.sleep(0)
        if chunk_index == 0:
            events.append(("fail", chunk_index))
            raise RuntimeError("first call failed")
        events.append(("finish", chunk_index))
        return ContextualChunk(
            original_chunk=chunk,
            contextual_text=chunk.chunk_text,
            context_snippet=f"context-{chunk_index}",
        )

    monkeypatch.setattr(retrieval, "_generate_context_for_chunk", fake_generate)
    result = await retrieval.generate_contexts(
        "document", [chunk(0), chunk(1), chunk(2)]
    )

    assert events.index(("fail", 0)) < events.index(("start", 1))
    assert events.index(("fail", 0)) < events.index(("start", 2))
    assert [item.original_chunk.chunk_index for item in result] == [0, 1, 2]
    assert result[0].context_snippet == ""
    assert [item.context_snippet for item in result[1:]] == ["context-1", "context-2"]

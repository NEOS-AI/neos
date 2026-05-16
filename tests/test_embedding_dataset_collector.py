"""EmbeddingCollector + EmbeddingDatasetManager 단위 테스트"""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from neos.dataset.embedding_collector import EmbeddingCollector
from neos.dataset.embedding_models import EmbeddingRecord
from neos.dataset.embedding_storage import EmbeddingDatasetManager


@pytest.fixture
def collector():
    return EmbeddingCollector(max_buffer=5)


@pytest.mark.asyncio
async def test_record_adds_entry(collector):
    await collector.record(
        embedding=[0.1] * 3072,
        provider="gemini",
        model="gemini-embedding-2-flash",
        dimension=3072,
        modality="text",
        input_text="hello",
    )
    records = await collector.get_all()
    assert len(records) == 1
    assert records[0].input_text == "hello"
    assert records[0].provider == "gemini"
    assert records[0].success is True


@pytest.mark.asyncio
async def test_buffer_eviction(collector):
    # max_buffer=5이므로 6개 삽입 시 첫 번째가 제거됨
    for i in range(6):
        await collector.record(
            embedding=[float(i)] * 3072,
            provider="gemini",
            model="gemini-embedding-2-flash",
            dimension=3072,
            input_text=f"text-{i}",
        )
    records = await collector.get_all()
    assert len(records) == 5
    # deque maxlen FIFO: 첫 번째(text-0)가 제거됨
    assert records[0].input_text == "text-1"


@pytest.mark.asyncio
async def test_save_jsonl():
    collector = EmbeddingCollector(max_buffer=10)
    await collector.record(
        embedding=[0.5] * 3072,
        provider="gemini",
        model="gemini-embedding-2-flash",
        dimension=3072,
        input_text="test text",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = EmbeddingDatasetManager(dataset_dir=Path(tmpdir))

        # embedding_collector 글로벌을 방금 만든 collector로 교체
        with patch("neos.dataset.embedding_storage.embedding_collector", collector):
            path = await manager.save_jsonl(include_embedding=False)

        assert path.exists()
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["input_text"] == "test text"
        assert record["provider"] == "gemini"
        assert "embedding" not in record  # include_embedding=False 기본값 확인

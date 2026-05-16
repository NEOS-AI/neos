"""임베딩 API 호출 인터셉터 — opt-in 샘플링 기반 수집"""

import asyncio
import time
from collections import deque
from typing import List, Optional

from neos.config.settings import settings
from .embedding_models import EmbeddingRecord


class EmbeddingCollector:
    """
    임베딩 호출 결과를 메모리 버퍼에 기록합니다.
    asyncio.Lock으로 동시성 안전을 보장하며 FIFO로 오래된 레코드를 제거합니다.
    """

    def __init__(self, max_buffer: int = 10000):
        self._buffer: deque = deque(maxlen=max_buffer)
        self._lock = asyncio.Lock()

    async def record(
        self,
        embedding: Optional[List[float]],
        provider: str,
        model: str,
        dimension: int,
        modality: str = "text",
        input_text: Optional[str] = None,
        mime_type: Optional[str] = None,
        input_size_bytes: int = 0,
        latency_ms: float = 0.0,
        task_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        rec = EmbeddingRecord(
            provider=provider,
            model=model,
            dimension=dimension,
            modality=modality,
            mime_type=mime_type,
            input_text=input_text,
            input_size_bytes=input_size_bytes,
            embedding=embedding,
            task_type=task_type or settings.GEMINI_EMBEDDING_TASK_TYPE,
            latency_ms=latency_ms,
            success=embedding is not None,
            metadata=metadata or {},
        )
        async with self._lock:
            self._buffer.append(rec)

    async def get_all(self) -> List[EmbeddingRecord]:
        async with self._lock:
            return list(self._buffer)

    async def clear(self) -> None:
        async with self._lock:
            self._buffer.clear()

    @property
    def size(self) -> int:
        return len(self._buffer)


# 전역 싱글톤
embedding_collector = EmbeddingCollector()

"""Document chunking utilities

Phase 2.8: Advanced Chunking Strategies
지원 전략: fixed, sentence, semantic, parent_child
"""

import re
from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import logging

from neos.config.settings import settings


logger = logging.getLogger(__name__)


class ChunkingStrategy(Enum):
    """청킹 전략 타입"""
    FIXED = "fixed"
    SENTENCE = "sentence"
    SEMANTIC = "semantic"
    PARENT_CHILD = "parent_child"


@dataclass
class DocumentChunk:
    """문서 청크 데이터 클래스"""

    chunk_index: int
    chunk_text: str
    chunk_size: int
    page_number: Optional[int] = None
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    chunk_type: str = "paragraph"
    heading_hierarchy: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    # Contextual Retrieval 필드
    contextual_text: Optional[str] = None   # context_snippet + "\n\n" + chunk_text (임베딩 대상)
    context_snippet: Optional[str] = None   # 생성된 컨텍스트 설명 (저장/디버깅용)


class DocumentChunker:
    """문서를 청크로 분할하는 클래스

    전략:
    - fixed: 고정 크기 분할 (문장 경계 무시)
    - sentence: 문장 경계를 존중하는 분할 (기본값)
    - semantic: 임베딩 유사도 기반 토픽 경계 감지
    - parent_child: 큰 부모 청크 + 작은 자식 청크 (검색 정밀도 + 컨텍스트 보존)
    """

    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None,
        respect_sentence_boundaries: bool = True,
        strategy: str = None,
    ):
        """
        DocumentChunker 초기화

        Args:
            chunk_size: 청크 크기 (문자 수)
            chunk_overlap: 청크 간 오버랩 (문자 수)
            respect_sentence_boundaries: 문장 경계 존중 여부 (하위호환, strategy 미지정 시 사용)
            strategy: 청킹 전략 ("fixed", "sentence", "semantic", "parent_child")
        """
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.chunk_overlap = chunk_overlap or settings.CHUNK_OVERLAP

        # strategy 파라미터 우선, 없으면 하위호환 로직
        if strategy:
            self.strategy = strategy
        elif not respect_sentence_boundaries:
            self.strategy = ChunkingStrategy.FIXED.value
        else:
            self.strategy = getattr(settings, "DEFAULT_CHUNKING_STRATEGY", ChunkingStrategy.SENTENCE.value)

        logger.info(
            f"DocumentChunker initialized: strategy={self.strategy}, "
            f"chunk_size={self.chunk_size}, overlap={self.chunk_overlap}"
        )

    def chunk_text(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """
        텍스트를 청크로 분할 (동기 래퍼, 기존 인터페이스 호환)

        semantic/parent_child 전략은 async 호출이 필요하므로
        해당 전략 사용 시 chunk_text_async()를 직접 호출하세요.
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for chunking")
            return []

        if self.strategy == ChunkingStrategy.FIXED.value:
            chunks = self._chunk_by_size(text, metadata)
        elif self.strategy == ChunkingStrategy.SENTENCE.value:
            chunks = self._chunk_by_sentences(text, metadata)
        else:
            # semantic, parent_child는 동기 호출 시 sentence로 fallback
            logger.debug(
                f"Strategy '{self.strategy}' requires async, falling back to sentence"
            )
            chunks = self._chunk_by_sentences(text, metadata)

        logger.info(f"Created {len(chunks)} chunks from text (length: {len(text)})")
        return chunks

    async def chunk_text_async(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """텍스트를 청크로 분할 (비동기 — 모든 전략 지원)"""
        if not text or not text.strip():
            logger.warning("Empty text provided for chunking")
            return []

        if self.strategy == ChunkingStrategy.FIXED.value:
            chunks = self._chunk_by_size(text, metadata)
        elif self.strategy == ChunkingStrategy.SENTENCE.value:
            chunks = self._chunk_by_sentences(text, metadata)
        elif self.strategy == ChunkingStrategy.SEMANTIC.value:
            chunks = await self._chunk_by_semantic(text, metadata)
        elif self.strategy == ChunkingStrategy.PARENT_CHILD.value:
            chunks = self._chunk_parent_child(text, metadata)
        else:
            logger.warning(f"Unknown strategy '{self.strategy}', using sentence")
            chunks = self._chunk_by_sentences(text, metadata)

        logger.info(
            f"Created {len(chunks)} chunks (strategy={self.strategy}, text_len={len(text)})"
        )
        return chunks

    # ─────────────────────────────────────────────
    # Sentence-boundary chunking (기존)
    # ─────────────────────────────────────────────

    @staticmethod
    def _split_into_sentences(text: str) -> List[str]:
        """텍스트를 문장 단위로 분할"""
        sentence_endings = re.compile(r"([.!?]+[\s\n]+|[\n]{2,})")
        parts = sentence_endings.split(text)

        combined = []
        for i in range(0, len(parts) - 1, 2):
            combined.append(parts[i] + (parts[i + 1] if i + 1 < len(parts) else ""))
        if len(parts) % 2 == 1:
            combined.append(parts[-1])

        return [s.strip() for s in combined if s.strip()]

    def _chunk_by_sentences(
        self, text: str, metadata: Optional[Dict[str, Any]] = None
    ) -> List[DocumentChunk]:
        """문장 경계를 존중하면서 청크 생성"""
        combined_sentences = self._split_into_sentences(text)

        chunks = []
        current_chunk = ""
        chunk_index = 0
        current_offset = 0

        for sentence in combined_sentences:
            potential_chunk = current_chunk + " " + sentence if current_chunk else sentence

            if len(potential_chunk) <= self.chunk_size:
                current_chunk = potential_chunk
            else:
                if current_chunk:
                    chunk = DocumentChunk(
                        chunk_index=chunk_index,
                        chunk_text=current_chunk,
                        chunk_size=len(current_chunk),
                        start_offset=current_offset,
                        end_offset=current_offset + len(current_chunk),
                        metadata=metadata or {},
                    )
                    chunks.append(chunk)
                    chunk_index += 1

                    if self.chunk_overlap > 0:
                        overlap_text = current_chunk[-self.chunk_overlap :]
                        current_chunk = overlap_text + " " + sentence
                        current_offset += len(current_chunk) - len(overlap_text) - 1
                    else:
                        current_chunk = sentence
                        current_offset += len(current_chunk)
                else:
                    current_chunk = sentence

        if current_chunk:
            chunk = DocumentChunk(
                chunk_index=chunk_index,
                chunk_text=current_chunk,
                chunk_size=len(current_chunk),
                start_offset=current_offset,
                end_offset=current_offset + len(current_chunk),
                metadata=metadata or {},
            )
            chunks.append(chunk)

        return chunks

    # ─────────────────────────────────────────────
    # Fixed-size chunking (기존)
    # ─────────────────────────────────────────────

    def _chunk_by_size(
        self, text: str, metadata: Optional[Dict[str, Any]] = None
    ) -> List[DocumentChunk]:
        """고정 크기로 청크 생성 (문장 경계 무시)"""
        chunks = []
        chunk_index = 0
        start = 0

        while start < len(text):
            end = start + self.chunk_size
            chunk_text = text[start:end]

            chunk = DocumentChunk(
                chunk_index=chunk_index,
                chunk_text=chunk_text,
                chunk_size=len(chunk_text),
                start_offset=start,
                end_offset=end,
                metadata=metadata or {},
            )
            chunks.append(chunk)

            start = end - self.chunk_overlap
            chunk_index += 1

        return chunks

    # ─────────────────────────────────────────────
    # Phase 2.8: Semantic chunking (NEW)
    # ─────────────────────────────────────────────

    async def _chunk_by_semantic(
        self, text: str, metadata: Optional[Dict[str, Any]] = None
    ) -> List[DocumentChunk]:
        """임베딩 유사도 기반 토픽 경계 감지 청킹

        1. 텍스트를 문장으로 분할
        2. 각 문장의 임베딩 생성
        3. 인접 문장 간 cosine similarity 계산
        4. 유사도 < threshold 인 지점에서 분할 (토픽 전환점)
        """
        sentences = self._split_into_sentences(text)
        if len(sentences) <= 1:
            return self._chunk_by_sentences(text, metadata)

        try:
            from neos.utils.embeddings import embedding_manager

            embeddings = await embedding_manager.get_embeddings_batch(sentences)

            # 임베딩 실패한 문장이 있으면 sentence fallback
            if any(e is None for e in embeddings):
                logger.warning("Some embeddings failed, falling back to sentence chunking")
                return self._chunk_by_sentences(text, metadata)

            # 인접 문장 간 cosine similarity 계산
            similarities = []
            for i in range(len(embeddings) - 1):
                sim = self._cosine_similarity(embeddings[i], embeddings[i + 1])
                similarities.append(sim)

            # threshold 이하인 지점이 토픽 경계
            threshold = getattr(settings, "SEMANTIC_CHUNK_THRESHOLD", 0.75)
            boundaries = [0]
            for i, sim in enumerate(similarities):
                if sim < threshold:
                    boundaries.append(i + 1)
            boundaries.append(len(sentences))

            # 경계 기준으로 청크 생성
            chunks = []
            chunk_index = 0
            for i in range(len(boundaries) - 1):
                chunk_sentences = sentences[boundaries[i]:boundaries[i + 1]]
                chunk_text = " ".join(chunk_sentences)

                # max chunk_size 초과 시 내부 sentence chunking
                if len(chunk_text) > self.chunk_size:
                    sub_chunks = self._chunk_by_sentences(chunk_text, metadata)
                    for sc in sub_chunks:
                        sc.chunk_index = chunk_index
                        sc.chunk_type = "semantic"
                        chunks.append(sc)
                        chunk_index += 1
                else:
                    chunk = DocumentChunk(
                        chunk_index=chunk_index,
                        chunk_text=chunk_text,
                        chunk_size=len(chunk_text),
                        chunk_type="semantic",
                        metadata=metadata or {},
                    )
                    chunks.append(chunk)
                    chunk_index += 1

            logger.info(
                f"Semantic chunking: {len(chunks)} chunks from "
                f"{len(sentences)} sentences ({len(boundaries) - 1} segments)"
            )
            return chunks

        except Exception as e:
            logger.warning(f"Semantic chunking failed: {e}, falling back to sentence")
            return self._chunk_by_sentences(text, metadata)

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """두 벡터의 cosine similarity 계산 (numpy 의존 없이)"""
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a * a for a in vec_a) ** 0.5
        norm_b = sum(b * b for b in vec_b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ─────────────────────────────────────────────
    # Phase 2.8: Parent-Child chunking (NEW)
    # ─────────────────────────────────────────────

    def _chunk_parent_child(
        self, text: str, metadata: Optional[Dict[str, Any]] = None
    ) -> List[DocumentChunk]:
        """부모-자식 계층 청킹

        큰 부모 청크(2x chunk_size)를 생성한 후 내부를 작은 자식 청크로 분할.
        자식 청크: 검색에 사용 (작아서 정밀 매칭)
        부모 텍스트: metadata에 포함 (넓은 컨텍스트 제공)
        """
        parent_chunk_size = self.chunk_size * 2
        child_chunks = []
        parent_index = 0
        start = 0

        while start < len(text):
            end = min(start + parent_chunk_size, len(text))
            parent_text = text[start:end]

            # 부모 내부를 자식 청크로 분할
            child_start = 0
            child_local_index = 0
            while child_start < len(parent_text):
                child_end = min(child_start + self.chunk_size, len(parent_text))
                child_text = parent_text[child_start:child_end]

                chunk = DocumentChunk(
                    chunk_index=len(child_chunks),
                    chunk_text=child_text,
                    chunk_size=len(child_text),
                    start_offset=start + child_start,
                    end_offset=start + child_end,
                    chunk_type="child",
                    metadata={
                        **(metadata or {}),
                        "parent_chunk_id": parent_index,
                        "parent_text": parent_text,
                        "child_local_index": child_local_index,
                    },
                )
                child_chunks.append(chunk)

                child_start = child_end - self.chunk_overlap
                if child_start >= len(parent_text) or child_end >= len(parent_text):
                    break
                child_local_index += 1

            start = end - self.chunk_overlap
            if start >= len(text) or end >= len(text):
                break
            parent_index += 1

        logger.info(
            f"Parent-child chunking: {len(child_chunks)} children "
            f"from {parent_index + 1} parents"
        )
        return child_chunks

    # ─────────────────────────────────────────────
    # Hierarchy chunking (기존)
    # ─────────────────────────────────────────────

    def chunk_with_hierarchy(
        self,
        text: str,
        headings: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """
        헤딩 계층 구조를 고려하여 청크 생성

        Args:
            text: 분할할 텍스트
            headings: 헤딩 정보 [{"level": 1, "text": "Title", "offset": 0}, ...]
            metadata: 청크 메타데이터

        Returns:
            DocumentChunk 리스트
        """
        if not headings:
            return self.chunk_text(text, metadata)

        chunks = []
        heading_stack = []  # 현재 헤딩 계층 스택

        # 헤딩 위치 기준으로 섹션 분할
        for i, heading in enumerate(headings):
            # 현재 헤딩 레벨에 맞게 스택 조정
            while heading_stack and heading_stack[-1]["level"] >= heading["level"]:
                heading_stack.pop()

            heading_stack.append(heading)

            # 다음 헤딩까지의 텍스트 추출
            start_offset = heading["offset"]
            end_offset = (
                headings[i + 1]["offset"] if i + 1 < len(headings) else len(text)
            )

            section_text = text[start_offset:end_offset]

            # 섹션 텍스트를 청크로 분할
            section_chunks = self.chunk_text(section_text, metadata)

            # 각 청크에 헤딩 계층 정보 추가
            heading_hierarchy = [h["text"] for h in heading_stack]
            for chunk in section_chunks:
                chunk.heading_hierarchy = heading_hierarchy
                chunk.start_offset = (
                    start_offset + chunk.start_offset
                    if chunk.start_offset
                    else start_offset
                )
                chunk.end_offset = (
                    start_offset + chunk.end_offset if chunk.end_offset else end_offset
                )
                chunks.append(chunk)

        # 청크 인덱스 재정렬
        for i, chunk in enumerate(chunks):
            chunk.chunk_index = i

        logger.info(
            f"Created {len(chunks)} chunks with hierarchy from text (length: {len(text)})"
        )
        return chunks

"""Document chunking utilities"""

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import logging

from neos.config.settings import settings


logger = logging.getLogger(__name__)


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


class DocumentChunker:
    """문서를 청크로 분할하는 클래스"""

    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None,
        respect_sentence_boundaries: bool = True,
    ):
        """
        DocumentChunker 초기화

        Args:
            chunk_size: 청크 크기 (문자 수)
            chunk_overlap: 청크 간 오버랩 (문자 수)
            respect_sentence_boundaries: 문장 경계를 존중할지 여부
        """
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.chunk_overlap = chunk_overlap or settings.CHUNK_OVERLAP
        self.respect_sentence_boundaries = respect_sentence_boundaries

        logger.info(
            f"DocumentChunker initialized: chunk_size={self.chunk_size}, overlap={self.chunk_overlap}"
        )

    def chunk_text(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """
        텍스트를 청크로 분할

        Args:
            text: 분할할 텍스트
            metadata: 청크 메타데이터

        Returns:
            DocumentChunk 리스트
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for chunking")
            return []

        chunks = []

        if self.respect_sentence_boundaries:
            chunks = self._chunk_by_sentences(text, metadata)
        else:
            chunks = self._chunk_by_size(text, metadata)

        logger.info(f"Created {len(chunks)} chunks from text (length: {len(text)})")
        return chunks

    def _chunk_by_sentences(
        self, text: str, metadata: Optional[Dict[str, Any]] = None
    ) -> List[DocumentChunk]:
        """문장 경계를 존중하면서 청크 생성"""
        # 문장 분할 (간단한 정규식 사용)
        sentence_endings = re.compile(r"([.!?]+[\s\n]+|[\n]{2,})")
        sentences = sentence_endings.split(text)

        # 문장과 구분자를 재결합
        combined_sentences = []
        for i in range(0, len(sentences) - 1, 2):
            combined_sentences.append(sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else ""))
        if len(sentences) % 2 == 1:
            combined_sentences.append(sentences[-1])

        chunks = []
        current_chunk = ""
        chunk_index = 0
        current_offset = 0

        for sentence in combined_sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # 현재 청크에 문장을 추가했을 때 크기 확인
            potential_chunk = current_chunk + " " + sentence if current_chunk else sentence

            if len(potential_chunk) <= self.chunk_size:
                # 청크에 추가
                current_chunk = potential_chunk
            else:
                # 현재 청크를 저장하고 새 청크 시작
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

                    # 오버랩을 위해 마지막 N 문자 유지
                    if self.chunk_overlap > 0:
                        overlap_text = current_chunk[-self.chunk_overlap :]
                        current_chunk = overlap_text + " " + sentence
                        current_offset += len(current_chunk) - len(overlap_text) - 1
                    else:
                        current_chunk = sentence
                        current_offset += len(current_chunk)
                else:
                    # 단일 문장이 chunk_size보다 큰 경우
                    current_chunk = sentence

        # 마지막 청크 추가
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

            # 오버랩 적용
            start = end - self.chunk_overlap
            chunk_index += 1

        return chunks

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

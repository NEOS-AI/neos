"""Smart Content Chunking Module.

This module provides intelligent content chunking for evaluating long sections
without losing semantic meaning by splitting at paragraph boundaries.

Design Philosophy:
- Preserve semantic units (paragraphs, sentences)
- Avoid mid-sentence splits that break coherence
- Overlap chunks to maintain context continuity
- Weight chunks by length when aggregating scores

★ Learning Point ─────────────────
Traditional truncation (content[:4000]) loses information and breaks sentences.
Smart chunking preserves meaning and enables accurate evaluation of long content.
─────────────────────────────────
"""

import re
import logging
from typing import List, Tuple
from dataclasses import dataclass


logger = logging.getLogger(__name__)


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class ContentChunk:
    """A semantic chunk of content.

    Attributes:
        content: The chunk text
        start_char: Starting character position in original
        end_char: Ending character position in original
        chunk_index: Index of this chunk (0-indexed)
        is_complete_paragraphs: Whether this chunk ends at paragraph boundary
    """

    content: str
    start_char: int
    end_char: int
    chunk_index: int
    is_complete_paragraphs: bool = True

    def __len__(self) -> int:
        """Return chunk length."""
        return len(self.content)


# ============================================================================
# Smart Content Chunker
# ============================================================================

class SmartContentChunker:
    """Intelligently chunk long content at semantic boundaries.

    This class splits long text into chunks at paragraph boundaries to preserve
    semantic meaning during evaluation. Includes overlap between chunks to
    maintain context continuity.

    Usage:
        chunker = SmartContentChunker(max_chunk_size=4000, overlap=200)
        chunks = chunker.chunk_content(long_text)

        # Chunks are ready for individual evaluation
        for chunk in chunks:
            quality = evaluate(chunk.content)
    """

    def __init__(
        self,
        max_chunk_size: int = 4000,
        overlap: int = 200,
        min_chunk_size: int = 500,
    ):
        """Initialize smart content chunker.

        Args:
            max_chunk_size: Maximum characters per chunk
            overlap: Characters to overlap between chunks (for context)
            min_chunk_size: Minimum chunk size (avoid tiny chunks)
        """
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
        self.min_chunk_size = min_chunk_size

        logger.debug(
            f"SmartContentChunker initialized: "
            f"max_size={max_chunk_size}, overlap={overlap}"
        )

    def chunk_content(self, content: str) -> List[ContentChunk]:
        """Chunk content at paragraph boundaries.

        Args:
            content: Full text to chunk

        Returns:
            List of ContentChunk objects
        """
        # If content is short enough, return as single chunk
        if len(content) <= self.max_chunk_size:
            return [
                ContentChunk(
                    content=content,
                    start_char=0,
                    end_char=len(content),
                    chunk_index=0,
                    is_complete_paragraphs=True,
                )
            ]

        logger.info(
            f"Content length ({len(content)} chars) exceeds threshold, chunking..."
        )

        # Split content by paragraphs (double newline)
        paragraphs = content.split('\n\n')

        chunks: List[ContentChunk] = []
        current_chunk_content = ""
        current_chunk_start = 0
        chunk_index = 0

        for para_idx, paragraph in enumerate(paragraphs):
            paragraph = paragraph.strip()
            if not paragraph:
                continue

            # Check if this paragraph is too long by itself
            if len(paragraph) > self.max_chunk_size:
                # Handle very long paragraph
                logger.debug(
                    f"Paragraph {para_idx} is very long ({len(paragraph)} chars), "
                    f"splitting at sentence boundaries"
                )

                # Save current chunk if exists
                if current_chunk_content:
                    chunks.append(
                        self._create_chunk(
                            content=current_chunk_content.strip(),
                            start_char=current_chunk_start,
                            chunk_index=chunk_index,
                        )
                    )
                    chunk_index += 1
                    current_chunk_content = ""

                # Split long paragraph
                para_fragments = self._split_long_paragraph(
                    paragraph, self.max_chunk_size - self.overlap
                )

                # Create chunks from fragments
                for fragment in para_fragments:
                    # Add overlap from previous chunk if exists
                    if chunks:
                        overlap_text = self.get_overlap_text(
                            chunks[-1].content, from_end=True
                        )
                        fragment_with_overlap = overlap_text + "\n\n" + fragment
                    else:
                        fragment_with_overlap = fragment

                    chunks.append(
                        self._create_chunk(
                            content=fragment_with_overlap,
                            start_char=len(content),  # Approximate
                            chunk_index=chunk_index,
                            is_complete=False,  # Mid-paragraph split
                        )
                    )
                    chunk_index += 1

                # Reset for next paragraph
                current_chunk_start = len(content)
                continue

            # Check if adding this paragraph would exceed max size
            potential_length = (
                len(current_chunk_content) +
                len(paragraph) +
                (2 if current_chunk_content else 0)  # \n\n separator
            )

            if potential_length > self.max_chunk_size and current_chunk_content:
                # Current chunk is full, save it
                chunks.append(
                    self._create_chunk(
                        content=current_chunk_content.strip(),
                        start_char=current_chunk_start,
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1

                # Start new chunk with overlap from previous
                overlap_text = self.get_overlap_text(
                    current_chunk_content, from_end=True
                )
                current_chunk_content = overlap_text + "\n\n" + paragraph
                current_chunk_start = current_chunk_start + len(chunks[-1].content) - len(overlap_text)
            else:
                # Add paragraph to current chunk
                if current_chunk_content:
                    current_chunk_content += "\n\n" + paragraph
                else:
                    current_chunk_content = paragraph

        # Add final chunk if exists
        if current_chunk_content:
            # Check if final chunk is too small and can be merged with previous
            if (
                chunks and
                len(current_chunk_content) < self.min_chunk_size and
                len(chunks[-1].content) + len(current_chunk_content) <= self.max_chunk_size
            ):
                # Merge with previous chunk
                last_chunk = chunks[-1]
                merged_content = last_chunk.content + "\n\n" + current_chunk_content
                chunks[-1] = self._create_chunk(
                    content=merged_content,
                    start_char=last_chunk.start_char,
                    chunk_index=last_chunk.chunk_index,
                )
                logger.debug(f"Merged small final chunk with previous chunk")
            else:
                chunks.append(
                    self._create_chunk(
                        content=current_chunk_content.strip(),
                        start_char=current_chunk_start,
                        chunk_index=chunk_index,
                    )
                )

        logger.info(
            f"Created {len(chunks)} chunks: "
            f"sizes={[len(c) for c in chunks]}"
        )

        return chunks

    def _create_chunk(
        self,
        content: str,
        start_char: int,
        chunk_index: int,
        is_complete: bool = True,
    ) -> ContentChunk:
        """Create a ContentChunk object.

        Args:
            content: Chunk content
            start_char: Starting position in original
            chunk_index: Chunk index
            is_complete: Whether chunk ends at paragraph boundary

        Returns:
            ContentChunk object
        """
        return ContentChunk(
            content=content,
            start_char=start_char,
            end_char=start_char + len(content),
            chunk_index=chunk_index,
            is_complete_paragraphs=is_complete,
        )

    def _split_long_paragraph(
        self,
        paragraph: str,
        max_size: int,
    ) -> List[str]:
        """Split a very long paragraph at sentence boundaries.

        Used when a single paragraph exceeds max_chunk_size.

        Args:
            paragraph: Long paragraph text
            max_size: Maximum size per split

        Returns:
            List of paragraph fragments
        """
        # Split at sentence boundaries (. ! ? followed by space or newline)
        sentence_pattern = r'(?<=[.!?])\s+(?=[A-Z가-힣])'
        sentences = re.split(sentence_pattern, paragraph)

        fragments = []
        current_fragment = ""

        for sentence in sentences:
            # If adding this sentence would exceed max, create fragment
            if len(current_fragment) + len(sentence) > max_size:
                if current_fragment:
                    fragments.append(current_fragment.strip())
                    current_fragment = sentence
                else:
                    # Sentence itself is too long, force split
                    fragments.append(sentence[:max_size])
                    current_fragment = sentence[max_size:]
            else:
                current_fragment += (" " if current_fragment else "") + sentence

        # Add remaining fragment
        if current_fragment:
            fragments.append(current_fragment.strip())

        return fragments

    def get_overlap_text(
        self,
        content: str,
        from_end: bool = True,
    ) -> str:
        """Extract overlap text from content.

        Args:
            content: Content to extract from
            from_end: If True, get from end; if False, get from start

        Returns:
            Overlap text
        """
        if len(content) <= self.overlap:
            return content

        if from_end:
            # Get last 'overlap' characters, preferably at word boundary
            overlap_text = content[-self.overlap:]
            # Try to start at word boundary
            first_space = overlap_text.find(' ')
            if first_space > 0:
                overlap_text = overlap_text[first_space + 1:]
            return overlap_text
        else:
            # Get first 'overlap' characters, preferably at word boundary
            overlap_text = content[:self.overlap]
            # Try to end at word boundary
            last_space = overlap_text.rfind(' ')
            if last_space > 0:
                overlap_text = overlap_text[:last_space]
            return overlap_text


# ============================================================================
# Utility Functions
# ============================================================================

def aggregate_chunk_qualities(
    chunk_qualities: List[Tuple[ContentChunk, 'SectionQuality']],
) -> 'SectionQuality':
    """Aggregate quality scores from multiple chunks.

    Uses length-weighted averaging to give more weight to longer chunks.

    Args:
        chunk_qualities: List of (ContentChunk, SectionQuality) tuples

    Returns:
        Aggregated SectionQuality
    """
    from .iterative_refiner import SectionQuality

    if not chunk_qualities:
        return SectionQuality()

    if len(chunk_qualities) == 1:
        return chunk_qualities[0][1]

    # Calculate total length for weighting
    total_length = sum(len(chunk) for chunk, _ in chunk_qualities)

    # Weighted average of each metric
    weighted_citation_coverage = 0.0
    weighted_citation_quality = 0.0
    weighted_coherence = 0.0
    weighted_completeness = 0.0
    weighted_clarity = 0.0

    total_claims = 0
    total_cited = 0
    total_citations = 0

    for chunk, quality in chunk_qualities:
        weight = len(chunk) / total_length

        weighted_citation_coverage += quality.citation_coverage * weight
        weighted_citation_quality += quality.citation_quality * weight
        weighted_coherence += quality.coherence_score * weight
        weighted_completeness += quality.completeness * weight
        weighted_clarity += quality.clarity_score * weight

        # Sum metadata
        total_claims += quality.total_claims
        total_cited += quality.cited_claims
        total_citations += quality.total_citations

    return SectionQuality(
        citation_coverage=weighted_citation_coverage,
        citation_quality=weighted_citation_quality,
        coherence_score=weighted_coherence,
        completeness=weighted_completeness,
        clarity_score=weighted_clarity,
        total_claims=total_claims,
        cited_claims=total_cited,
        total_citations=total_citations,
        section_length=total_length,
    )


def should_chunk_content(content: str, threshold: int = 4000) -> bool:
    """Determine if content should be chunked.

    Args:
        content: Content to check
        threshold: Length threshold for chunking

    Returns:
        True if content should be chunked
    """
    return len(content) > threshold

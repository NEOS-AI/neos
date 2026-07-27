"""Iterative Report Refinement Module.

This module implements a Ralph Wiggum Loop-inspired iterative improvement mechanism
for HyperDeepResearch reports. It enables self-referential refinement through:

1. Section-level iteration: Each section is improved until quality threshold is met
2. Abstract generation: Generate comprehensive abstract from section summaries
3. Consistency alignment: Align all sections with the abstract
4. Citation enhancement: Automatically recommend and validate citations

Design Philosophy (inspired by Ralph Loop):
- Self-referential improvement: Each iteration sees previous outputs
- Quality-driven completion: Iterate until quality threshold (not fixed loops)
- Automatic citation: Every iteration checks and adds citations
- Comprehensive tracking: Log all iterations and quality metrics

★ Learning Point ─────────────────
Unlike Ralph Loop's Stop Hook approach, this uses:
- In-memory state instead of file system
- Quality metrics instead of completion-promise string
- Structured phases instead of free-form iteration
- Python-native loops instead of bash hooks
─────────────────────────────────
"""

from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
import logging
import asyncio
import functools

from langchain_core.messages import HumanMessage

from neos.utils.llm_factory import create_llm
from neos.utils.llm_wrapper import create_tracked_llm, extract_text_from_response

from .utils import CitationTracker, CitationRecommender
from .metrics_collector import QualityMetricsCollector
from .learning_feedback import ImprovementTracker
from .prompts import EvaluationPrompts
from .content_chunker import (
    SmartContentChunker,
    should_chunk_content,
    aggregate_chunk_qualities,
)


logger = logging.getLogger(__name__)


# ============================================================================
# Retry Decorator
# ============================================================================

def retry_on_llm_error(max_retries: int = 3, base_delay: float = 1.0):
    """Decorator to retry LLM operations on failure with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (doubled for each retry)

    Returns:
        Decorated async function with retry logic
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except asyncio.TimeoutError as e:
                    last_exception = e
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"{func.__name__} timed out (attempt {attempt + 1}/{max_retries}). "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                except Exception as e:
                    # Check if it's a transient error (network, rate limit, etc.)
                    error_msg = str(e).lower()
                    is_transient = any(
                        keyword in error_msg
                        for keyword in [
                            "timeout",
                            "rate limit",
                            "429",
                            "503",
                            "connection",
                            "network",
                        ]
                    )

                    if is_transient and attempt < max_retries - 1:
                        last_exception = e
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"{func.__name__} failed with transient error (attempt {attempt + 1}/{max_retries}): {e}. "
                            f"Retrying in {delay}s..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        # Non-transient error or final attempt
                        logger.error(f"{func.__name__} failed: {e}")
                        raise

            # All retries exhausted
            logger.error(f"{func.__name__} failed after {max_retries} attempts")
            raise last_exception

        return wrapper
    return decorator


# ============================================================================
# Quality Metrics
# ============================================================================

@dataclass
class SectionQuality:
    """Quality metrics for a report section.

    Each metric is normalized to 0-1 range.

    Attributes:
        citation_coverage: Ratio of claims with citations (0-1)
        citation_quality: Average quality score of citations (0-1)
        coherence_score: Logical flow and coherence (0-1)
        completeness: Content completeness vs. requirements (0-1)
        clarity_score: Writing clarity and readability (0-1)
    """

    citation_coverage: float = 0.0
    citation_quality: float = 0.0
    coherence_score: float = 0.0
    completeness: float = 0.0
    clarity_score: float = 0.0

    # Metadata
    total_claims: int = 0
    cited_claims: int = 0
    total_citations: int = 0
    section_length: int = 0

    # ★ NEW: Custom weights for overall_score calculation (F - Custom Weights)
    custom_weights: Optional[Dict[str, float]] = field(default=None, repr=False)

    def overall_score(self) -> float:
        """Calculate weighted overall quality score.

        Default Weights (if custom_weights not provided):
        - Citation coverage: 30% (critical for academic quality)
        - Citation quality: 25% (source reliability)
        - Coherence: 20% (logical flow)
        - Completeness: 15% (content sufficiency)
        - Clarity: 10% (readability)

        Returns:
            Overall quality score (0-1)
        """
        # ★ NEW: Use custom weights if provided, otherwise use defaults
        if self.custom_weights:
            weights = self.custom_weights
        else:
            weights = {
                "citation_coverage": 0.30,
                "citation_quality": 0.25,
                "coherence": 0.20,
                "completeness": 0.15,
                "clarity": 0.10,
            }

        return (
            self.citation_coverage * weights.get("citation_coverage", 0.30) +
            self.citation_quality * weights.get("citation_quality", 0.25) +
            self.coherence_score * weights.get("coherence", 0.20) +
            self.completeness * weights.get("completeness", 0.15) +
            self.clarity_score * weights.get("clarity", 0.10)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "overall_score": self.overall_score(),
            "citation_coverage": self.citation_coverage,
            "citation_quality": self.citation_quality,
            "coherence_score": self.coherence_score,
            "completeness": self.completeness,
            "clarity_score": self.clarity_score,
            "total_claims": self.total_claims,
            "cited_claims": self.cited_claims,
            "total_citations": self.total_citations,
            "section_length": self.section_length,
        }

    def get_improvement_suggestions(self) -> List[str]:
        """Identify areas needing improvement.

        Returns:
            List of improvement suggestions
        """
        suggestions = []

        if self.citation_coverage < 0.7:
            suggestions.append(
                f"Add more citations (current: {self.cited_claims}/{self.total_claims} claims cited)"
            )

        if self.citation_quality < 0.6:
            suggestions.append(
                "Improve citation quality by using more authoritative sources"
            )

        if self.coherence_score < 0.7:
            suggestions.append(
                "Improve logical flow and coherence between paragraphs"
            )

        if self.completeness < 0.7:
            suggestions.append(
                "Add more content to fully address the section's purpose"
            )

        if self.clarity_score < 0.7:
            suggestions.append(
                "Simplify language and improve readability"
            )

        return suggestions


@dataclass
class IterationHistory:
    """Track iteration history for a section or abstract.

    Attributes:
        iteration_number: Current iteration (1-indexed)
        content: Content at this iteration
        quality: Quality metrics
        improvements_made: List of improvements applied
        timestamp: When this iteration occurred
    """

    iteration_number: int
    content: str
    quality: SectionQuality
    improvements_made: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "iteration_number": self.iteration_number,
            "quality": self.quality.to_dict(),
            "improvements_made": self.improvements_made,
            "timestamp": self.timestamp,
            "content_length": len(self.content),
        }


# ============================================================================
# Section Iterator
# ============================================================================

class SectionIterator:
    """Iteratively improve a single section.

    This class handles the iterative refinement of individual sections,
    similar to how Ralph Loop iteratively improves code.

    Process:
    1. Evaluate current section quality
    2. If quality < threshold, identify improvements
    3. Rewrite section with improvements
    4. Repeat until quality >= threshold or max iterations reached
    """

    def __init__(
        self,
        agent_name: str = "hyper_deep_research",
        citation_tracker: Optional[CitationTracker] = None,
        max_iterations: int = 3,
        quality_threshold: float = 0.8,
        metrics_collector: Optional[QualityMetricsCollector] = None,
        adaptive_threshold_config: Optional['AdaptiveThresholdConfig'] = None,  # ★ NEW (B)
        improvement_tracker: Optional[ImprovementTracker] = None,  # ★ NEW (C): Learning from Feedback
        conditional_refinement_enabled: bool = True,  # ★ NEW (E): Conditional Refinement
        skip_threshold_multiplier: float = 0.95,  # ★ NEW (E): Skip if quality >= threshold * multiplier
        quality_weights: Optional[Dict[str, float]] = None,  # ★ NEW (F): Custom quality weights
    ):
        """Initialize section iterator.

        Args:
            agent_name: Agent name for LLM tracking
            citation_tracker: Citation tracking system
            max_iterations: Maximum improvement iterations per section
            quality_threshold: Default quality score to aim for (0-1)
            metrics_collector: Optional metrics collector for tracking
            adaptive_threshold_config: Optional adaptive threshold configuration
            improvement_tracker: Optional learning system for improvement prioritization
            conditional_refinement_enabled: Skip refinement for already-good sections
            skip_threshold_multiplier: Quality multiplier for skip decision (0.95 = 95% of threshold)
            quality_weights: Optional custom weights for quality metrics (will be normalized)
        """
        self.agent_name = agent_name
        self.citation_tracker = citation_tracker or CitationTracker()
        self.citation_recommender = CitationRecommender()
        self.max_iterations = max_iterations
        self.default_quality_threshold = quality_threshold  # ★ RENAMED
        self.metrics_collector = metrics_collector
        self.adaptive_config = adaptive_threshold_config  # ★ NEW (B)
        self.improvement_tracker = improvement_tracker  # ★ NEW (C): Learning from Feedback
        self.content_chunker = SmartContentChunker()  # ★ NEW (D): Smart Content Chunking
        self.conditional_refinement_enabled = conditional_refinement_enabled  # ★ NEW (E)
        self.skip_threshold_multiplier = skip_threshold_multiplier  # ★ NEW (E)
        self.quality_weights = quality_weights  # ★ NEW (F): Store custom quality weights

    async def refine_section_iteratively(
        self,
        section_title: str,
        section_purpose: str,
        initial_content: str,
        context: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str = "ko",
    ) -> Dict[str, Any]:
        """Refine a section iteratively until quality threshold is met.

        Args:
            section_title: Section title
            section_purpose: Section purpose/goal
            initial_content: Initial section content
            context: Research context (topic analysis, etc.)
            session_id: Session ID for tracking
            user_id: User ID for tracking
            language: Language code

        Returns:
            Dictionary with:
            - final_content: Refined section content
            - iterations_performed: Number of iterations
            - quality_history: List of IterationHistory objects
            - final_quality: Final SectionQuality
        """
        logger.info(f"Starting iterative refinement for section: {section_title}")

        # ★ NEW: Generate section ID for metrics tracking
        section_id = section_title.lower().replace(" ", "_")[:50]

        # ★ NEW (B): Get adaptive threshold for this section
        if self.adaptive_config and self.adaptive_config.enabled:
            quality_threshold = self.adaptive_config.get_threshold(section_title)
            logger.info(f"Using adaptive threshold for '{section_title}': {quality_threshold}")
        else:
            quality_threshold = self.default_quality_threshold

        # ★ NEW (E): Conditional Refinement - Quick quality check
        # Skip refinement if content is already high quality
        conditional_skip_enabled = getattr(self, 'conditional_refinement_enabled', True)
        if conditional_skip_enabled:
            quick_quality = await self._quick_quality_check(
                initial_content, section_title, session_id, user_id, language
            )

            # Skip threshold is slightly lower than target (95% of threshold)
            skip_threshold_multiplier = getattr(self, 'skip_threshold_multiplier', 0.95)
            skip_threshold = quality_threshold * skip_threshold_multiplier

            if quick_quality >= skip_threshold:
                logger.info(
                    f"  🎯 Section already meets quality threshold "
                    f"(quick check: {quick_quality:.2f} >= {skip_threshold:.2f}), "
                    f"skipping refinement"
                )

                # Evaluate full quality for accurate reporting
                full_quality = await self.evaluate_section_quality(
                    initial_content, section_title, session_id, user_id, language
                )

                return {
                    "final_content": initial_content,
                    "iterations_performed": 0,  # No refinement needed
                    "quality_history": [],
                    "final_quality": full_quality,
                    "section_title": section_title,
                    "skipped": True,  # Flag to indicate this was skipped
                    "skip_reason": f"Initial quality ({quick_quality:.2f}) already meets threshold"
                }

        current_content = initial_content
        quality_history: List[IterationHistory] = []

        for iteration in range(1, self.max_iterations + 1):
            logger.info(f"  Iteration {iteration}/{self.max_iterations}")

            # ★ NEW: Start timing this iteration
            iteration_start_time = datetime.now()

            # Step 1: Evaluate quality
            quality = await self.evaluate_section_quality(
                current_content, section_title, session_id, user_id, language
            )

            logger.info(
                f"    Quality: {quality.overall_score():.2f} "
                f"(citations: {quality.citation_coverage:.2f}, "
                f"coherence: {quality.coherence_score:.2f})"
            )

            # Step 2: Check completion condition (Ralph Loop's completion-promise equivalent)
            # Use the effective threshold resolved above (adaptive or default);
            # `self.quality_threshold` no longer exists — it is `default_quality_threshold`.
            if quality.overall_score() >= quality_threshold:
                logger.info(
                    f"    ✓ Quality threshold met ({quality.overall_score():.2f} >= {quality_threshold})"
                )
                quality_history.append(
                    IterationHistory(
                        iteration_number=iteration,
                        content=current_content,
                        quality=quality,
                        improvements_made=["Quality threshold met - no changes needed"],
                    )
                )

                # ★ NEW: Record metrics for this iteration
                if self.metrics_collector:
                    duration_ms = int((datetime.now() - iteration_start_time).total_seconds() * 1000)
                    self.metrics_collector.record_iteration(
                        section_id=section_id,
                        section_title=section_title,
                        iteration_number=iteration,
                        quality_score=quality.overall_score(),
                        citation_coverage=quality.citation_coverage,
                        coherence=quality.coherence_score,
                        completeness=quality.completeness,
                        clarity=quality.clarity_score,
                        duration_ms=duration_ms,
                        llm_calls=1,
                        improvements_made=["Quality threshold met - no changes needed"],
                    )

                break

            # Step 3: Identify improvements needed
            improvements = quality.get_improvement_suggestions()

            # ★ NEW (C): Prioritize improvements using learning system
            if self.improvement_tracker:
                improvements = self.improvement_tracker.prioritize_improvements(
                    improvements=improvements,
                    fallback_order=improvements  # Use original order as fallback
                )
                logger.info(f"    Improvements needed (prioritized): {improvements}")
            else:
                logger.info(f"    Improvements needed: {improvements}")

            # Step 4: Get citation recommendations (automatic enhancement)
            citation_suggestions = {}
            if quality.citation_coverage < 0.8:
                citation_suggestions = self.citation_tracker.get_citation_suggestions_for_section(
                    current_content,
                    min_citations_per_claim=2
                )
                logger.info(
                    f"    Citation suggestions: {citation_suggestions.get('total_claims', 0)} claims"
                )

            # Step 5: Rewrite section with improvements (self-referential improvement)
            improved_content = await self.rewrite_section_with_improvements(
                section_title=section_title,
                section_purpose=section_purpose,
                current_content=current_content,
                improvements=improvements,
                citation_suggestions=citation_suggestions,
                context=context,
                session_id=session_id,
                user_id=user_id,
                language=language,
            )

            # Record iteration
            quality_history.append(
                IterationHistory(
                    iteration_number=iteration,
                    content=current_content,
                    quality=quality,
                    improvements_made=improvements,
                )
            )

            # ★ NEW: Record metrics for this iteration
            if self.metrics_collector:
                duration_ms = int((datetime.now() - iteration_start_time).total_seconds() * 1000)
                self.metrics_collector.record_iteration(
                    section_id=section_id,
                    section_title=section_title,
                    iteration_number=iteration,
                    quality_score=quality.overall_score(),
                    citation_coverage=quality.citation_coverage,
                    coherence=quality.coherence_score,
                    completeness=quality.completeness,
                    clarity=quality.clarity_score,
                    duration_ms=duration_ms,
                    llm_calls=2,  # evaluate + rewrite
                    improvements_made=improvements,
                )

            # Update current content for next iteration
            previous_quality = quality.overall_score()
            current_content = improved_content

            # ★ NEW (C): Record improvement effectiveness in learning system
            # We'll evaluate the next iteration's quality to measure improvement effectiveness
            # This is deferred to the next iteration to avoid extra LLM call

        # Final quality evaluation
        final_quality = await self.evaluate_section_quality(
            current_content, section_title, session_id, user_id, language
        )

        logger.info(
            f"Section refinement complete: {section_title}\n"
            f"  Iterations: {len(quality_history)}\n"
            f"  Initial quality: {quality_history[0].quality.overall_score():.2f}\n"
            f"  Final quality: {final_quality.overall_score():.2f}"
        )

        # ★ NEW (C): Record improvement effectiveness in learning system
        if self.improvement_tracker and len(quality_history) >= 2:
            # Analyze quality progression to learn improvement effectiveness
            for i in range(len(quality_history) - 1):
                current_iter = quality_history[i]
                next_iter = quality_history[i + 1]

                quality_before = current_iter.quality.overall_score()
                quality_after = next_iter.quality.overall_score()

                # Record each improvement that was applied
                for improvement_type in current_iter.improvements_made:
                    # Skip meta-messages
                    if "Quality threshold met" in improvement_type:
                        continue

                    self.improvement_tracker.record_improvement(
                        improvement_type=improvement_type,
                        section_id=section_id,
                        iteration_number=current_iter.iteration_number,
                        quality_before=quality_before,
                        quality_after=quality_after,
                    )

            logger.debug(
                f"Recorded {len(quality_history) - 1} improvement applications to learning system"
            )

        return {
            "final_content": current_content,
            "iterations_performed": len(quality_history),
            "quality_history": quality_history,
            "final_quality": final_quality,
            "section_title": section_title,
        }

    async def evaluate_section_quality(
        self,
        content: str,
        section_title: str,
        session_id: str,
        user_id: str,
        language: str = "ko",
    ) -> SectionQuality:
        """Evaluate section quality across multiple dimensions.

        This uses both automated metrics and LLM-based evaluation.
        For long content (>4000 chars), automatically chunks at paragraph
        boundaries and aggregates evaluation results.

        Args:
            content: Section content to evaluate
            section_title: Section title for context
            session_id: Session ID
            user_id: User ID
            language: Language code

        Returns:
            SectionQuality object with all metrics
        """
        # ★ NEW (D): Check if content needs chunking
        if should_chunk_content(content, threshold=4000):
            logger.info(
                f"Content length ({len(content)} chars) exceeds threshold, "
                f"using smart chunking for evaluation"
            )
            return await self._evaluate_chunked_content(
                content, section_title, session_id, user_id, language
            )

        # Standard evaluation for short content
        # Automated metrics: Citation analysis
        citation_validation = self.citation_tracker.validate_citations(content)
        citation_contexts = self.citation_tracker.parse_citations_from_text(
            content, section_title
        )

        # Calculate citation coverage
        total_claims = max(len(citation_contexts), 1)  # Avoid division by zero
        cited_claims = len([c for c in citation_contexts if c.source_numbers])
        citation_coverage = cited_claims / total_claims if total_claims > 0 else 0.0

        # Calculate citation quality (average of cited source quality scores)
        citation_quality_scores = []
        for context in citation_contexts:
            for source_num in context.source_numbers:
                sources = self.citation_tracker.get_sources_by_numbers([source_num])
                if sources:
                    citation_quality_scores.append(sources[0].quality_score)

        avg_citation_quality = (
            sum(citation_quality_scores) / len(citation_quality_scores)
            if citation_quality_scores
            else 0.5  # Default neutral score
        )

        # LLM-based evaluation: Coherence, Completeness, Clarity
        llm_scores = await self._evaluate_with_llm(
            content, section_title, session_id, user_id, language
        )

        return SectionQuality(
            citation_coverage=min(citation_coverage, 1.0),
            citation_quality=avg_citation_quality,
            coherence_score=llm_scores.get("coherence", 0.7),
            completeness=llm_scores.get("completeness", 0.7),
            clarity_score=llm_scores.get("clarity", 0.7),
            total_claims=total_claims,
            cited_claims=cited_claims,
            total_citations=citation_validation.get("total_citations", 0),
            section_length=len(content),
            custom_weights=self.quality_weights,  # ★ NEW (F): Pass custom weights
        )

    async def _evaluate_chunked_content(
        self,
        content: str,
        section_title: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> SectionQuality:
        """Evaluate long content by chunking at paragraph boundaries.

        Args:
            content: Long section content
            section_title: Section title
            session_id: Session ID
            user_id: User ID
            language: Language code

        Returns:
            Aggregated SectionQuality
        """
        # Chunk the content
        chunks = self.content_chunker.chunk_content(content)
        logger.info(f"Evaluating {len(chunks)} chunks separately")

        # Evaluate each chunk
        chunk_qualities = []
        for chunk in chunks:
            # Evaluate this chunk using standard evaluation
            # (We recursively call evaluate_section_quality, but the chunk
            # is now short enough to not trigger chunking again)
            chunk_quality = await self.evaluate_section_quality(
                content=chunk.content,
                section_title=f"{section_title} (chunk {chunk.chunk_index + 1}/{len(chunks)})",
                session_id=session_id,
                user_id=user_id,
                language=language,
            )
            chunk_qualities.append((chunk, chunk_quality))

        # Aggregate chunk qualities
        aggregated_quality = aggregate_chunk_qualities(chunk_qualities)

        logger.info(
            f"Chunked evaluation complete: {len(chunks)} chunks → "
            f"aggregated quality={aggregated_quality.overall_score():.2f}"
        )

        return aggregated_quality

    async def _quick_quality_check(
        self,
        content: str,
        section_title: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> float:
        """Quick quality check to determine if refinement can be skipped.

        This is a lightweight evaluation that only checks critical metrics:
        - Citation coverage (automated)
        - Basic coherence (heuristic-based)

        Args:
            content: Section content
            section_title: Section title
            session_id: Session ID
            user_id: User ID
            language: Language code

        Returns:
            Estimated quality score (0-1)
        """
        # Automated citation check (fast)
        citation_contexts = self.citation_tracker.parse_citations_from_text(
            content, section_title
        )
        total_claims = max(len(citation_contexts), 1)
        cited_claims = len([c for c in citation_contexts if c.source_numbers])
        citation_coverage = cited_claims / total_claims if total_claims > 0 else 0.0

        # Heuristic coherence check (no LLM call needed)
        # Check for basic markers of coherence:
        # - Multiple paragraphs (structure)
        # - Reasonable length
        # - No extremely short paragraphs (incomplete thoughts)
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]

        coherence_heuristic = 0.7  # Default neutral score

        if len(paragraphs) >= 2:
            coherence_heuristic += 0.1  # Multiple paragraphs = good structure

        if len(content) >= 500:
            coherence_heuristic += 0.1  # Sufficient length

        # Check for very short paragraphs (< 50 chars)
        short_paragraphs = [p for p in paragraphs if len(p) < 50]
        if len(short_paragraphs) / max(len(paragraphs), 1) > 0.5:
            coherence_heuristic -= 0.2  # Too many short paragraphs = fragmented

        coherence_heuristic = max(0.0, min(1.0, coherence_heuristic))  # Clamp to [0, 1]

        # Simplified quality score (citation 50%, coherence 50%)
        # This is more conservative than full evaluation to avoid false positives
        quick_score = (citation_coverage * 0.5 + coherence_heuristic * 0.5)

        logger.debug(
            f"Quick quality check: {quick_score:.2f} "
            f"(citations: {citation_coverage:.2f}, coherence: {coherence_heuristic:.2f})"
        )

        return quick_score

    async def _evaluate_with_llm(
        self,
        content: str,
        section_title: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> Dict[str, float]:
        """Use LLM to evaluate coherence, completeness, and clarity.

        Args:
            content: Section content
            section_title: Section title
            session_id: Session ID
            user_id: User ID
            language: Language code

        Returns:
            Dictionary with coherence, completeness, clarity scores (0-1)
        """
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=2000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["section_quality_evaluation"],
            )

            # ★ NEW (G): Use language-specific prompt from evaluation_prompts module
            prompt = EvaluationPrompts.get_quality_evaluation_prompt(
                section_title=section_title,
                content=content,
                language=language,
            )

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            result_text = extract_text_from_response(response).strip()

            # Parse scores
            scores = {}
            for line in result_text.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip().lower()
                    try:
                        score = float(value.strip())
                        scores[key] = max(0.0, min(1.0, score))  # Clamp to [0, 1]
                    except ValueError:
                        continue

            return {
                "coherence": scores.get("coherence", 0.7),
                "completeness": scores.get("completeness", 0.7),
                "clarity": scores.get("clarity", 0.7),
            }

        except Exception as e:
            logger.warning(f"LLM quality evaluation failed: {e}")
            return {"coherence": 0.7, "completeness": 0.7, "clarity": 0.7}

    @retry_on_llm_error(max_retries=3, base_delay=2.0)
    async def rewrite_section_with_improvements(
        self,
        section_title: str,
        section_purpose: str,
        current_content: str,
        improvements: List[str],
        citation_suggestions: Dict[str, Any],
        context: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str,
    ) -> str:
        """Rewrite section incorporating improvements.

        This is the self-referential improvement step, analogous to Ralph Loop
        seeing its previous output and improving it.

        Args:
            section_title: Section title
            section_purpose: Section purpose
            current_content: Current section content (previous iteration)
            improvements: List of needed improvements
            citation_suggestions: Suggested citations to add
            context: Research context
            session_id: Session ID
            user_id: User ID
            language: Language code

        Returns:
            Improved section content
        """
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=16000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["section_rewrite", "iteration_improvement"],
            )

            # Build improvement instructions
            improvements_text = "\n".join([f"- {imp}" for imp in improvements])

            # Citation suggestions
            citation_text = ""
            if citation_suggestions.get("suggestions"):
                citation_text = "\n\nCitation Recommendations:\n"
                for claim, recs in list(citation_suggestions["suggestions"].items())[:5]:
                    citation_text += f"\nFor claim: \"{claim[:100]}...\"\n"
                    for rec in recs[:2]:
                        citation_text += f"  - [{rec.source_number}] {rec.reason}\n"

            # Source list
            source_list = self.citation_tracker.get_source_list_for_prompt(max_sources=100)

            prompt = f"""You are refining a section of a research report. Below is the current version and areas for improvement.

Section Title: {section_title}
Purpose: {section_purpose}

Current Content:
{current_content}

Required Improvements:
{improvements_text}
{citation_text}

{source_list}

Instructions:
1. Rewrite the section to address ALL improvement points
2. Add inline citations [1,2,3] from the source list for factual claims
3. Maintain the core message but improve quality
4. Keep the same section structure
5. Write in {language} language

Improved Section:"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            improved_content = extract_text_from_response(response).strip()

            return improved_content

        except Exception as e:
            logger.error(f"Section rewrite failed: {e}")
            return current_content  # Return original if rewrite fails


# ============================================================================
# Abstract Generator
# ============================================================================

class AbstractGenerator:
    """Generate and refine Abstract from section summaries.

    Process:
    1. Generate initial abstract from section summaries
    2. After sections are refined, re-evaluate abstract
    3. Refine abstract if needed for consistency
    """

    def __init__(self, agent_name: str = "hyper_deep_research"):
        """Initialize abstract generator.

        Args:
            agent_name: Agent name for tracking
        """
        self.agent_name = agent_name

    async def generate_abstract_from_summaries(
        self,
        section_summaries: List[Dict[str, str]],
        query: str,
        session_id: str,
        user_id: str,
        language: str = "ko",
    ) -> str:
        """Generate comprehensive abstract from section summaries.

        Args:
            section_summaries: List of {"title": ..., "summary": ...}
            query: Original research query
            session_id: Session ID
            user_id: User ID
            language: Language code

        Returns:
            Generated abstract
        """
        logger.info("Generating abstract from section summaries...")

        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=4000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["abstract_generation"],
            )

            summaries_text = "\n\n".join([
                f"**{s['title']}**\n{s['summary']}"
                for s in section_summaries
            ])

            prompt = f"""Based on the following section summaries, write a comprehensive Abstract that captures the essence of the entire research.

Research Query: {query}

Section Summaries:
{summaries_text}

Write a well-structured Abstract (300-500 words) in {language} that:
1. Clearly states the research topic and objectives
2. Summarizes key findings from all sections
3. Highlights the most important insights
4. Provides a cohesive overview of the research

Abstract:"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            abstract = extract_text_from_response(response).strip()

            logger.info(f"Abstract generated ({len(abstract)} characters)")
            return abstract

        except Exception as e:
            logger.error(f"Abstract generation failed: {e}")
            return f"# Abstract\n\nResearch on: {query}\n\n(Abstract pending)"

    async def refine_abstract_if_needed(
        self,
        current_abstract: str,
        refined_sections: List[Dict[str, Any]],
        query: str,
        session_id: str,
        user_id: str,
        language: str = "ko",
        quality_threshold: float = 0.8,
    ) -> Dict[str, Any]:
        """Re-evaluate and refine abstract based on refined sections.

        Args:
            current_abstract: Current abstract
            refined_sections: List of refined section data
            query: Original query
            session_id: Session ID
            user_id: User ID
            language: Language code
            quality_threshold: Quality threshold for refinement

        Returns:
            Dictionary with refined_abstract and refinement_needed flag
        """
        logger.info("Evaluating abstract quality...")

        # Check if abstract aligns with refined sections
        needs_refinement = await self._check_abstract_alignment(
            current_abstract, refined_sections, session_id, user_id, language
        )

        if not needs_refinement:
            logger.info("Abstract is well-aligned with sections - no refinement needed")
            return {
                "refined_abstract": current_abstract,
                "refinement_needed": False,
                "reason": "Abstract aligns well with refined sections"
            }

        # Refine abstract
        logger.info("Abstract needs refinement - generating improved version...")

        # Generate new summaries from refined sections
        section_summaries = []
        for section_data in refined_sections:
            summary = await self._summarize_section(
                section_data["final_content"],
                section_data["section_title"],
                session_id,
                user_id,
                language
            )
            section_summaries.append({
                "title": section_data["section_title"],
                "summary": summary
            })

        # Generate refined abstract
        refined_abstract = await self.generate_abstract_from_summaries(
            section_summaries, query, session_id, user_id, language
        )

        return {
            "refined_abstract": refined_abstract,
            "refinement_needed": True,
            "reason": "Abstract was updated to better reflect refined sections"
        }

    async def _check_abstract_alignment(
        self,
        abstract: str,
        refined_sections: List[Dict[str, Any]],
        session_id: str,
        user_id: str,
        language: str,
    ) -> bool:
        """Check if abstract aligns well with refined sections.

        Returns:
            True if refinement is needed, False otherwise
        """
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=1000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["abstract_alignment_check"],
            )

            sections_preview = "\n".join([
                f"- {s['section_title']}: {s['final_content'][:200]}..."
                for s in refined_sections[:5]
            ])

            prompt = f"""Evaluate if the Abstract accurately reflects the refined sections.

Abstract:
{abstract}

Refined Sections (preview):
{sections_preview}

Does the abstract need refinement? Answer with ONLY one word:
YES (if abstract is outdated or inconsistent with sections)
NO (if abstract accurately reflects the sections)

Answer:"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            answer = extract_text_from_response(response).strip().upper()

            return "YES" in answer

        except Exception as e:
            logger.warning(f"Abstract alignment check failed: {e}")
            return False  # Default: don't refine on error

    async def _summarize_section(
        self,
        content: str,
        title: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> str:
        """Generate summary of a section.

        Args:
            content: Section content
            title: Section title
            session_id: Session ID
            user_id: User ID
            language: Language code

        Returns:
            Section summary (2-3 sentences)
        """
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=1000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["section_summarization"],
            )

            prompt = f"""Summarize this section in 2-3 concise sentences in {language}.

Section: {title}

Content:
{content[:1500]}

Summary:"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return extract_text_from_response(response).strip()

        except Exception as e:
            logger.warning(f"Section summarization failed: {e}")
            return f"Summary of {title}"


# ============================================================================
# Consistency Aligner
# ============================================================================

class ConsistencyAligner:
    """Align sections with abstract for consistency.

    After abstract is generated/refined, this class ensures all sections
    are consistent with the abstract's narrative and key points.
    """

    def __init__(
        self,
        agent_name: str = "hyper_deep_research",
        citation_tracker: Optional[CitationTracker] = None,
    ):
        """Initialize consistency aligner.

        Args:
            agent_name: Agent name for tracking
            citation_tracker: Citation tracking system
        """
        self.agent_name = agent_name
        self.citation_tracker = citation_tracker or CitationTracker()

    async def align_section_with_abstract(
        self,
        section_title: str,
        section_content: str,
        abstract: str,
        query: str,
        session_id: str,
        user_id: str,
        language: str = "ko",
    ) -> Dict[str, Any]:
        """Align a section with the abstract.

        Args:
            section_title: Section title
            section_content: Current section content
            abstract: Abstract to align with
            query: Original query
            session_id: Session ID
            user_id: User ID
            language: Language code

        Returns:
            Dictionary with aligned_content and consistency_score
        """
        logger.info(f"Aligning section '{section_title}' with abstract...")

        # Check current consistency
        consistency_issues = await self._identify_consistency_issues(
            section_content, abstract, section_title, session_id, user_id, language
        )

        if not consistency_issues:
            logger.info(f"  Section '{section_title}' is already consistent")
            return {
                "aligned_content": section_content,
                "consistency_score": 1.0,
                "changes_made": False,
                "issues_found": []
            }

        # Realign section
        logger.info(f"  Found {len(consistency_issues)} consistency issues - realigning...")
        aligned_content = await self._realign_section(
            section_title,
            section_content,
            abstract,
            consistency_issues,
            query,
            session_id,
            user_id,
            language,
        )

        # Validate citations still valid after realignment
        citation_validation = self.citation_tracker.validate_citations(aligned_content)
        if not citation_validation["valid"]:
            logger.warning(
                f"  Realignment introduced invalid citations: {citation_validation['invalid_citations']}"
            )
            # Auto-fix invalid citations
            aligned_content = await self._fix_invalid_citations(
                aligned_content,
                citation_validation["invalid_citations"],
                section_title,
                session_id,
                user_id,
                language,
            )

        return {
            "aligned_content": aligned_content,
            "consistency_score": 0.9,  # Assume high consistency after alignment
            "changes_made": True,
            "issues_found": consistency_issues,
        }

    async def _identify_consistency_issues(
        self,
        section_content: str,
        abstract: str,
        section_title: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> List[str]:
        """Identify consistency issues between section and abstract.

        Returns:
            List of consistency issues (empty if consistent)
        """
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=2000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["consistency_check"],
            )

            prompt = f"""Check if this section is consistent with the abstract.

Abstract:
{abstract}

Section: {section_title}
{section_content[:1500]}

List any consistency issues (contradictions, misalignments, missing key points).
If consistent, respond with "CONSISTENT".

Issues:"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            result = extract_text_from_response(response).strip()

            if "CONSISTENT" in result.upper():
                return []

            # Parse issues
            issues = [
                line.strip()
                for line in result.split('\n')
                if line.strip() and not line.strip().startswith('#')
            ]

            return issues[:5]  # Limit to 5 issues

        except Exception as e:
            logger.warning(f"Consistency check failed: {e}")
            return []

    @retry_on_llm_error(max_retries=3, base_delay=2.0)
    async def _realign_section(
        self,
        section_title: str,
        section_content: str,
        abstract: str,
        consistency_issues: List[str],
        query: str,
        session_id: str,
        user_id: str,
        language: str,
    ) -> str:
        """Realign section to be consistent with abstract.

        Args:
            section_title: Section title
            section_content: Current content
            abstract: Abstract to align with
            consistency_issues: List of identified issues
            query: Original query
            session_id: Session ID
            user_id: User ID
            language: Language code

        Returns:
            Realigned section content
        """
        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.3, max_tokens=16000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["section_realignment"],
            )

            issues_text = "\n".join([f"- {issue}" for issue in consistency_issues])
            source_list = self.citation_tracker.get_source_list_for_prompt(max_sources=100)

            prompt = f"""Revise this section to align with the Abstract and fix consistency issues.

Research Query: {query}

Abstract:
{abstract}

Current Section: {section_title}
{section_content}

Consistency Issues to Fix:
{issues_text}

{source_list}

Instructions:
1. Revise the section to align with the Abstract's narrative
2. Fix all consistency issues
3. Maintain factual accuracy and citations [1,2,3]
4. Keep the core content but improve alignment
5. Write in {language} language

Revised Section:"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return extract_text_from_response(response).strip()

        except Exception as e:
            logger.error(f"Section realignment failed: {e}")
            return section_content

    @retry_on_llm_error(max_retries=3, base_delay=2.0)
    async def _fix_invalid_citations(
        self,
        content: str,
        invalid_citations: List[int],
        section_title: str,
        session_id: str,
        user_id: str,
        language: str = "ko",
    ) -> str:
        """Fix invalid citations by replacing them with valid ones using LLM.

        Args:
            content: Section content with invalid citations
            invalid_citations: List of invalid citation numbers
            section_title: Section title for context
            session_id: Session ID
            user_id: User ID
            language: Language code

        Returns:
            Fixed section content with valid citations
        """
        logger.info(f"Fixing {len(invalid_citations)} invalid citations...")

        try:
            llm = create_tracked_llm(
                llm=create_llm(temperature=0.2, max_tokens=16000),
                session_id=session_id,
                user_id=user_id,
                workflow_step="hyper_deep_research",
                agent_name=self.agent_name,
                tags=["citation_fix"],
            )

            invalid_nums_str = ", ".join([f"[{num}]" for num in invalid_citations])
            source_list = self.citation_tracker.get_source_list_for_prompt(max_sources=100)

            prompt = f"""Fix invalid citations in this section by replacing them with valid source numbers.

Section: {section_title}

Content with invalid citations:
{content}

INVALID citation numbers to fix: {invalid_nums_str}

{source_list}

Instructions:
1. Find sentences/claims with invalid citation numbers ({invalid_nums_str})
2. Replace them with VALID citation numbers from the source list above
3. Choose sources that best support the claim
4. If no appropriate source exists, remove the citation (but keep the text)
5. Maintain all other content exactly as-is
6. Write in {language} language

Fixed Content:"""

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            fixed_content = extract_text_from_response(response).strip()

            # Verify the fix
            validation = self.citation_tracker.validate_citations(fixed_content)
            if validation["valid"]:
                logger.info("  ✓ Citations fixed successfully")
            else:
                logger.warning(
                    f"  ⚠ Some citations still invalid after fix: {validation['invalid_citations']}"
                )

            return fixed_content

        except Exception as e:
            logger.error(f"Citation fix failed: {e}")
            return content  # Return original if fix fails


# ============================================================================
# Main Orchestrator
# ============================================================================

class IterativeReportRefiner:
    """Main orchestrator for iterative report refinement.

    This class coordinates the entire iterative refinement process:
    1. Refine each section iteratively
    2. Generate abstract from section summaries
    3. Refine abstract based on improved sections
    4. Align all sections with refined abstract

    Inspired by Ralph Wiggum Loop's philosophy of iterative self-improvement.
    """

    def __init__(
        self,
        agent_name: str = "hyper_deep_research",
        citation_tracker: Optional[CitationTracker] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize iterative report refiner.

        Args:
            agent_name: Agent name for tracking
            citation_tracker: Citation tracking system
            config: Configuration dictionary
        """
        self.agent_name = agent_name
        self.citation_tracker = citation_tracker or CitationTracker()

        # Load config
        self.config = config or {}
        self.max_iterations = self.config.get("max_iterations_per_section", 3)
        self.quality_threshold = self.config.get("section_quality_threshold", 0.8)

        # ★ NEW: Initialize metrics collector first (needed by components)
        self.metrics_enabled = self.config.get("collect_metrics", True)
        self.metrics_collector: Optional[QualityMetricsCollector] = None
        if self.metrics_enabled:
            report_id = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            # 이 리파이너는 create_llm()을 model= 없이 호출하므로 실제 모델은
            # provider × everyday 역할 기본값이다. 비용 추정 요율을 그 모델의
            # 카탈로그 가격에서 끌어오도록 이름을 넘긴다.
            from neos.utils.llm_factory import get_default_model

            try:
                metrics_model = get_default_model()
            except Exception as exc:  # 설정 문제로 메트릭이 죽지 않게 한다
                logger.warning("Could not resolve model for cost metrics: %s", exc)
                metrics_model = None

            self.metrics_collector = QualityMetricsCollector(
                report_id=report_id,
                enabled=True,
                model=metrics_model,
            )
            logger.info(f"Metrics collection enabled (report_id={report_id})")

        # ★ NEW (B): Load adaptive threshold config
        from .config import AdaptiveThresholdConfig
        adaptive_config = None
        if self.config.get("adaptive_thresholds_enabled"):
            adaptive_config = self.config.get("adaptive_threshold_config")
            if adaptive_config is None:
                # Create default config if not provided
                adaptive_config = AdaptiveThresholdConfig(enabled=True)
            logger.info("Adaptive thresholds enabled")

        # ★ NEW (C): Initialize learning system (improvement tracker)
        from .learning_feedback import create_improvement_tracker
        self.learning_enabled = self.config.get("enable_learning_feedback", True)
        self.improvement_tracker: Optional[ImprovementTracker] = None
        if self.learning_enabled:
            storage_path = self.config.get("learning_storage_path")
            self.improvement_tracker = create_improvement_tracker(
                enable_learning=True,
                storage_path=storage_path,
            )
            logger.info(f"Learning from Feedback enabled (storage={storage_path or 'default'})")

        # Initialize components
        # ★ NEW (E): Conditional refinement settings
        conditional_enabled = self.config.get("enable_conditional_refinement", True)
        skip_multiplier = self.config.get("skip_threshold_multiplier", 0.95)

        # ★ NEW (F): Extract and normalize quality weights from config
        quality_weights = None
        if self.config.get("quality_metric_weights"):
            from .config import ResearchConfig
            temp_config = ResearchConfig(quality_metric_weights=self.config["quality_metric_weights"])
            quality_weights = temp_config.get_normalized_quality_weights()
            logger.info(f"Using custom quality weights: {quality_weights}")

        self.section_iterator = SectionIterator(
            agent_name=agent_name,
            citation_tracker=self.citation_tracker,
            max_iterations=self.max_iterations,
            quality_threshold=self.quality_threshold,
            metrics_collector=self.metrics_collector,
            adaptive_threshold_config=adaptive_config,  # ★ NEW (B)
            improvement_tracker=self.improvement_tracker,  # ★ NEW (C): Learning from Feedback
            conditional_refinement_enabled=conditional_enabled,  # ★ NEW (E)
            skip_threshold_multiplier=skip_multiplier,  # ★ NEW (E)
            quality_weights=quality_weights,  # ★ NEW (F): Pass custom quality weights
        )

        self.abstract_generator = AbstractGenerator(agent_name=agent_name)

        self.consistency_aligner = ConsistencyAligner(
            agent_name=agent_name,
            citation_tracker=self.citation_tracker,
        )

        logger.info(
            f"IterativeReportRefiner initialized with "
            f"max_iterations={self.max_iterations}, "
            f"quality_threshold={self.quality_threshold}"
        )

    async def generate_coherent_report(
        self,
        sections_data: List[Dict[str, Any]],
        query: str,
        context: Dict[str, Any],
        session_id: str,
        user_id: str,
        language: str = "ko",
    ) -> Dict[str, Any]:
        """Generate a coherent report through iterative refinement.

        Full Process:
        Phase 1: Section-level iteration
        Phase 2: Abstract generation from summaries
        Phase 3: Abstract refinement (if needed)
        Phase 4: Section-abstract consistency alignment

        Args:
            sections_data: List of initial section data
                           Each: {"title": ..., "purpose": ..., "content": ...}
            query: Original research query
            context: Research context
            session_id: Session ID
            user_id: User ID
            language: Language code

        Returns:
            Dictionary with:
            - final_abstract: Refined abstract
            - final_sections: List of refined sections
            - refinement_metadata: Metadata about the process
        """
        logger.info("=" * 80)
        logger.info("Starting Iterative Report Refinement (Ralph Loop-inspired)")
        logger.info("=" * 80)

        start_time = datetime.now()

        # ★ NEW: Start metrics collection
        if self.metrics_collector:
            self.metrics_collector.start_collection()

        # ==================================================
        # Phase 1: Refine Each Section Iteratively (Parallel)
        # ==================================================
        logger.info("\n[Phase 1] Section-Level Iterative Refinement (Parallel)")
        logger.info("-" * 80)

        # Use semaphore to limit concurrent refinements (avoid API rate limits)
        max_concurrent_refinements = self.config.get("max_concurrent_refinements", 4)
        semaphore = asyncio.Semaphore(max_concurrent_refinements)
        logger.info(f"Max concurrent refinements: {max_concurrent_refinements}")

        async def refine_section_with_limit(idx: int, section_data: Dict[str, Any]):
            """Refine a single section with semaphore limit."""
            async with semaphore:
                logger.info(f"\nRefining section {idx}/{len(sections_data)}: {section_data['title']}")

                # Iteratively improve section
                refinement_result = await self.section_iterator.refine_section_iteratively(
                    section_title=section_data["title"],
                    section_purpose=section_data.get("purpose", ""),
                    initial_content=section_data["content"],
                    context=context,
                    session_id=session_id,
                    user_id=user_id,
                    language=language,
                )

                # Generate summary for this section
                summary = await self.abstract_generator._summarize_section(
                    refinement_result["final_content"],
                    section_data["title"],
                    session_id,
                    user_id,
                    language,
                )

                return refinement_result, {
                    "title": section_data["title"],
                    "summary": summary,
                }

        # Refine all sections in parallel (with concurrency limit)
        tasks = [
            refine_section_with_limit(idx, section_data)
            for idx, section_data in enumerate(sections_data, 1)
        ]
        results = await asyncio.gather(*tasks)

        # Unpack results
        refined_sections = [r[0] for r in results]
        section_summaries = [r[1] for r in results]

        # ==================================================
        # Phase 2: Generate Abstract from Summaries
        # ==================================================
        logger.info("\n[Phase 2] Abstract Generation from Section Summaries")
        logger.info("-" * 80)

        initial_abstract = await self.abstract_generator.generate_abstract_from_summaries(
            section_summaries=section_summaries,
            query=query,
            session_id=session_id,
            user_id=user_id,
            language=language,
        )

        # ==================================================
        # Phase 3: Abstract Refinement (if needed)
        # ==================================================
        logger.info("\n[Phase 3] Abstract Refinement Check")
        logger.info("-" * 80)

        abstract_refinement = await self.abstract_generator.refine_abstract_if_needed(
            current_abstract=initial_abstract,
            refined_sections=refined_sections,
            query=query,
            session_id=session_id,
            user_id=user_id,
            language=language,
            quality_threshold=self.quality_threshold,
        )

        final_abstract = abstract_refinement["refined_abstract"]
        logger.info(f"Abstract refinement: {abstract_refinement['reason']}")

        # ==================================================
        # Phase 4: Consistency Alignment
        # ==================================================
        logger.info("\n[Phase 4] Section-Abstract Consistency Alignment")
        logger.info("-" * 80)

        aligned_sections = []

        for idx, section_data in enumerate(refined_sections, 1):
            logger.info(f"\nAligning section {idx}/{len(refined_sections)}: {section_data['section_title']}")

            alignment_result = await self.consistency_aligner.align_section_with_abstract(
                section_title=section_data["section_title"],
                section_content=section_data["final_content"],
                abstract=final_abstract,
                query=query,
                session_id=session_id,
                user_id=user_id,
                language=language,
            )

            aligned_sections.append({
                **section_data,
                "final_content": alignment_result["aligned_content"],
                "consistency_score": alignment_result["consistency_score"],
                "alignment_changes": alignment_result["changes_made"],
            })

        # ==================================================
        # Completion
        # ==================================================
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        logger.info("\n" + "=" * 80)
        logger.info("Iterative Report Refinement Complete")
        logger.info("=" * 80)
        logger.info(f"Total sections refined: {len(aligned_sections)}")
        logger.info(f"Abstract refinement: {abstract_refinement['refinement_needed']}")
        logger.info(f"Duration: {duration:.1f} seconds")
        logger.info("=" * 80 + "\n")

        # Metadata
        refinement_metadata = {
            "total_sections": len(aligned_sections),
            "total_iterations": sum(s["iterations_performed"] for s in refined_sections),
            "abstract_refined": abstract_refinement["refinement_needed"],
            "sections_aligned": sum(1 for s in aligned_sections if s["alignment_changes"]),
            "average_final_quality": sum(
                s["final_quality"].overall_score() for s in refined_sections
            ) / len(refined_sections) if refined_sections else 0.0,
            "duration_seconds": duration,
            "timestamp": end_time.isoformat(),
        }

        # ★ NEW: Generate and display metrics report
        metrics_report = None
        if self.metrics_collector:
            self.metrics_collector.finalize_collection()
            metrics_report = self.metrics_collector.generate_report()

            # Display dashboard to console
            logger.info("\n")
            self.metrics_collector.display_dashboard()

            # Optional: Export to JSON
            if self.config.get("export_metrics_json"):
                export_path = f"metrics_{metrics_report.report_id}.json"
                self.metrics_collector.export_to_json(export_path)
                logger.info(f"Metrics exported to: {export_path}")

        return {
            "final_abstract": final_abstract,
            "final_sections": aligned_sections,
            "refinement_metadata": refinement_metadata,
            "metrics": metrics_report.to_dict() if metrics_report else None,  # ★ NEW
        }

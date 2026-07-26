"""Unit tests for IterativeReportRefiner and related components.

This test suite covers:
1. SectionIterator - iterative section refinement
2. AbstractGenerator - abstract generation and refinement
3. ConsistencyAligner - section-abstract alignment
4. IterativeReportRefiner - full orchestration

Test Philosophy:
- Mock external dependencies (LLM calls)
- Test edge cases (empty content, max iterations, etc.)
- Verify error handling and retry logic
- Validate quality metrics calculation
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from dataclasses import dataclass

# ★ Circular import resolved! Now using normal imports
from neos.agents.search_agents.hyper_deep_research.iterative_refiner import (
    SectionIterator,
    AbstractGenerator,
    ConsistencyAligner,
    IterativeReportRefiner,
    SectionQuality,
    IterationHistory,
    retry_on_llm_error,
)
from neos.agents.search_agents.hyper_deep_research.utils import CitationTracker


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def mock_citation_tracker():
    """Create a mock CitationTracker."""
    tracker = Mock(spec=CitationTracker)
    tracker.validate_citations.return_value = {
        "valid": True,
        "invalid_citations": [],
        "total_citations": 5
    }
    tracker.get_citation_suggestions_for_section.return_value = {
        "total_claims": 3,
        "suggestions": {}
    }
    tracker.get_source_list_for_prompt.return_value = "Sources: [1] Source A, [2] Source B"
    # _quick_quality_check()가 len()을 취하므로 실제 계약(List[CitationContext])을
    # 지켜야 한다. Mock을 그대로 두면 TypeError로 터진다.
    tracker.parse_citations_from_text.return_value = []
    return tracker


@pytest.fixture
def section_iterator(mock_citation_tracker):
    """Create SectionIterator instance for testing."""
    return SectionIterator(
        agent_name="test_agent",
        citation_tracker=mock_citation_tracker,
        max_iterations=3,
        quality_threshold=0.8,
    )


@pytest.fixture
def abstract_generator():
    """Create AbstractGenerator instance for testing."""
    return AbstractGenerator(agent_name="test_agent")


@pytest.fixture
def consistency_aligner(mock_citation_tracker):
    """Create ConsistencyAligner instance for testing."""
    return ConsistencyAligner(
        agent_name="test_agent",
        citation_tracker=mock_citation_tracker,
    )


@pytest.fixture
def iterative_refiner(mock_citation_tracker):
    """Create IterativeReportRefiner instance for testing."""
    config = {
        "max_iterations_per_section": 3,
        "section_quality_threshold": 0.8,
        "max_concurrent_refinements": 4,
    }
    return IterativeReportRefiner(
        agent_name="test_agent",
        citation_tracker=mock_citation_tracker,
        config=config,
    )


# ============================================================================
# SectionQuality Tests
# ============================================================================

class TestSectionQuality:
    """Test SectionQuality metrics and calculations."""

    def test_overall_score_calculation(self):
        """Test weighted overall score calculation."""
        quality = SectionQuality(
            citation_coverage=0.8,
            citation_quality=0.7,
            coherence_score=0.9,
            completeness=0.8,
            clarity_score=0.85,
        )

        # Weighted: 0.8*0.3 + 0.7*0.25 + 0.9*0.2 + 0.8*0.15 + 0.85*0.1
        expected = 0.8 * 0.3 + 0.7 * 0.25 + 0.9 * 0.2 + 0.8 * 0.15 + 0.85 * 0.1
        assert abs(quality.overall_score() - expected) < 0.001

    def test_to_dict_conversion(self):
        """Test conversion to dictionary."""
        quality = SectionQuality(
            citation_coverage=0.8,
            citation_quality=0.7,
            total_claims=10,
            cited_claims=8,
        )

        result = quality.to_dict()
        assert result["citation_coverage"] == 0.8
        assert result["citation_quality"] == 0.7
        assert result["total_claims"] == 10
        assert result["cited_claims"] == 8
        assert "overall_score" in result

    def test_improvement_suggestions_low_citations(self):
        """Test improvement suggestions for low citation coverage."""
        quality = SectionQuality(
            citation_coverage=0.5,  # Below 0.7 threshold
            citation_quality=0.8,
            coherence_score=0.9,
            completeness=0.9,
            clarity_score=0.9,
            total_claims=10,
            cited_claims=5,
        )

        suggestions = quality.get_improvement_suggestions()
        assert len(suggestions) > 0
        assert any("citation" in s.lower() for s in suggestions)

    def test_improvement_suggestions_low_coherence(self):
        """Test improvement suggestions for low coherence."""
        quality = SectionQuality(
            citation_coverage=0.9,
            citation_quality=0.9,
            coherence_score=0.5,  # Below 0.7 threshold
            completeness=0.9,
            clarity_score=0.9,
        )

        suggestions = quality.get_improvement_suggestions()
        assert any("coherence" in s.lower() or "flow" in s.lower() for s in suggestions)

    def test_improvement_suggestions_multiple_issues(self):
        """Test improvement suggestions when multiple metrics are low."""
        quality = SectionQuality(
            citation_coverage=0.5,
            citation_quality=0.5,
            coherence_score=0.5,
            completeness=0.5,
            clarity_score=0.5,
        )

        suggestions = quality.get_improvement_suggestions()
        assert len(suggestions) >= 3  # Multiple improvements needed

    # ============================================================================
    # Custom Quality Weights Tests (NEW - P3 Enhancement)
    # ============================================================================

    def test_overall_score_with_custom_weights(self):
        """Test overall score calculation with custom weights."""
        # Equal weights for all metrics
        custom_weights = {
            "citation_coverage": 0.2,
            "citation_quality": 0.2,
            "coherence": 0.2,
            "completeness": 0.2,
            "clarity": 0.2,
        }

        quality = SectionQuality(
            citation_coverage=0.8,
            citation_quality=0.7,
            coherence_score=0.9,
            completeness=0.6,
            clarity_score=0.85,
            custom_weights=custom_weights,
        )

        # With equal weights: (0.8 + 0.7 + 0.9 + 0.6 + 0.85) * 0.2 = 0.77
        expected = (0.8 + 0.7 + 0.9 + 0.6 + 0.85) * 0.2
        assert abs(quality.overall_score() - expected) < 0.001

    def test_overall_score_emphasize_citations(self):
        """Test custom weights emphasizing citations (academic papers)."""
        # Academic paper weights: emphasize citations
        custom_weights = {
            "citation_coverage": 0.4,
            "citation_quality": 0.3,
            "coherence": 0.15,
            "completeness": 0.10,
            "clarity": 0.05,
        }

        quality = SectionQuality(
            citation_coverage=0.9,
            citation_quality=0.85,
            coherence_score=0.7,
            completeness=0.7,
            clarity_score=0.7,
            custom_weights=custom_weights,
        )

        # Weighted: 0.9*0.4 + 0.85*0.3 + 0.7*0.15 + 0.7*0.1 + 0.7*0.05
        expected = 0.9 * 0.4 + 0.85 * 0.3 + 0.7 * 0.15 + 0.7 * 0.1 + 0.7 * 0.05
        assert abs(quality.overall_score() - expected) < 0.001

    def test_overall_score_emphasize_clarity(self):
        """Test custom weights emphasizing clarity (blog posts)."""
        # Blog post weights: emphasize clarity and coherence
        custom_weights = {
            "citation_coverage": 0.15,
            "citation_quality": 0.15,
            "coherence": 0.25,
            "completeness": 0.20,
            "clarity": 0.25,
        }

        quality = SectionQuality(
            citation_coverage=0.6,
            citation_quality=0.6,
            coherence_score=0.9,
            completeness=0.8,
            clarity_score=0.95,
            custom_weights=custom_weights,
        )

        # Weighted: 0.6*0.15 + 0.6*0.15 + 0.9*0.25 + 0.8*0.2 + 0.95*0.25
        expected = 0.6 * 0.15 + 0.6 * 0.15 + 0.9 * 0.25 + 0.8 * 0.2 + 0.95 * 0.25
        assert abs(quality.overall_score() - expected) < 0.001

    def test_overall_score_default_weights_when_none(self):
        """Test that default weights are used when custom_weights is None."""
        quality = SectionQuality(
            citation_coverage=0.8,
            citation_quality=0.7,
            coherence_score=0.9,
            completeness=0.8,
            clarity_score=0.85,
            custom_weights=None,  # Explicitly None
        )

        # Should use default weights: 0.8*0.3 + 0.7*0.25 + 0.9*0.2 + 0.8*0.15 + 0.85*0.1
        expected = 0.8 * 0.3 + 0.7 * 0.25 + 0.9 * 0.2 + 0.8 * 0.15 + 0.85 * 0.1
        assert abs(quality.overall_score() - expected) < 0.001

    def test_custom_weights_with_missing_keys(self):
        """Test custom weights with missing keys (should use defaults)."""
        # Partial custom weights (missing some keys)
        custom_weights = {
            "citation_coverage": 0.5,
            "citation_quality": 0.3,
            # Missing: coherence, completeness, clarity
        }

        quality = SectionQuality(
            citation_coverage=0.8,
            citation_quality=0.7,
            coherence_score=0.9,
            completeness=0.8,
            clarity_score=0.85,
            custom_weights=custom_weights,
        )

        # Should use custom for provided, defaults for missing
        # 0.8*0.5 + 0.7*0.3 + 0.9*0.2 + 0.8*0.15 + 0.85*0.1
        expected = 0.8 * 0.5 + 0.7 * 0.3 + 0.9 * 0.2 + 0.8 * 0.15 + 0.85 * 0.1
        assert abs(quality.overall_score() - expected) < 0.001


# ============================================================================
# SectionIterator Tests
# ============================================================================

class TestSectionIterator:
    """Test SectionIterator for iterative section refinement."""

    @pytest.mark.asyncio
    async def test_refine_section_meets_threshold_first_iteration(
        self, section_iterator, mock_citation_tracker
    ):
        """Test section that meets quality threshold on first iteration."""
        # Mock high quality from the start
        with patch.object(
            section_iterator, "evaluate_section_quality", new=AsyncMock()
        ) as mock_eval:
            mock_eval.return_value = SectionQuality(
                citation_coverage=0.9,
                citation_quality=0.9,
                coherence_score=0.9,
                completeness=0.9,
                clarity_score=0.9,
            )

            result = await section_iterator.refine_section_iteratively(
                section_title="Test Section",
                section_purpose="Test purpose",
                initial_content="High quality content with citations [1,2,3].",
                context={},
                session_id="test_session",
                user_id="test_user",
                language="ko",
            )

            assert result["iterations_performed"] == 1
            assert result["final_quality"].overall_score() >= 0.8
            assert result["final_content"] == "High quality content with citations [1,2,3]."

    @pytest.mark.asyncio
    async def test_refine_section_max_iterations_reached(
        self, section_iterator, mock_citation_tracker
    ):
        """Test section that never meets threshold - max iterations."""
        # Mock consistently low quality
        with patch.object(
            section_iterator, "evaluate_section_quality", new=AsyncMock()
        ) as mock_eval, patch.object(
            section_iterator, "rewrite_section_with_improvements", new=AsyncMock()
        ) as mock_rewrite:
            mock_eval.return_value = SectionQuality(
                citation_coverage=0.5,
                citation_quality=0.5,
                coherence_score=0.5,
                completeness=0.5,
                clarity_score=0.5,
            )
            mock_rewrite.return_value = "Improved content iteration"

            result = await section_iterator.refine_section_iteratively(
                section_title="Test Section",
                section_purpose="Test purpose",
                initial_content="Low quality content.",
                context={},
                session_id="test_session",
                user_id="test_user",
                language="ko",
            )

            # Should stop at max_iterations (3)
            assert result["iterations_performed"] == 3
            assert len(result["quality_history"]) == 3

    @pytest.mark.asyncio
    async def test_refine_section_empty_content(
        self, section_iterator, mock_citation_tracker
    ):
        """Test refinement with empty initial content (edge case)."""
        with patch.object(
            section_iterator, "evaluate_section_quality", new=AsyncMock()
        ) as mock_eval:
            mock_eval.return_value = SectionQuality(
                citation_coverage=0.0,
                citation_quality=0.0,
                coherence_score=0.0,
                completeness=0.0,
                clarity_score=0.0,
                total_claims=0,
            )

            result = await section_iterator.refine_section_iteratively(
                section_title="Test Section",
                section_purpose="Test purpose",
                initial_content="",  # Empty content
                context={},
                session_id="test_session",
                user_id="test_user",
                language="ko",
            )

            # Should still execute iterations
            assert result["iterations_performed"] >= 1
            assert result["final_content"] is not None

    @pytest.mark.asyncio
    async def test_refine_section_very_long_content(
        self, section_iterator, mock_citation_tracker
    ):
        """Test refinement with very long content (>10,000 words)."""
        # Generate long content
        long_content = " ".join(["Word"] * 15000)  # 15,000 words

        with patch.object(
            section_iterator, "evaluate_section_quality", new=AsyncMock()
        ) as mock_eval, patch.object(
            section_iterator, "rewrite_section_with_improvements", new=AsyncMock()
        ) as mock_rewrite:
            mock_eval.return_value = SectionQuality(
                citation_coverage=0.9,
                citation_quality=0.9,
                coherence_score=0.9,
                completeness=0.9,
                clarity_score=0.9,
            )

            result = await section_iterator.refine_section_iteratively(
                section_title="Test Section",
                section_purpose="Test purpose",
                initial_content=long_content,
                context={},
                session_id="test_session",
                user_id="test_user",
                language="ko",
            )

            # Should handle long content without error
            assert result["iterations_performed"] >= 1
            assert len(result["final_content"]) > 0

    @pytest.mark.asyncio
    async def test_refine_section_without_citations(
        self, section_iterator, mock_citation_tracker
    ):
        """Test refinement of section without any citations."""
        # Mock low citation coverage
        with patch.object(
            section_iterator, "evaluate_section_quality", new=AsyncMock()
        ) as mock_eval:
            mock_eval.return_value = SectionQuality(
                citation_coverage=0.0,  # No citations
                citation_quality=0.0,
                coherence_score=0.8,
                completeness=0.8,
                clarity_score=0.8,
                total_claims=5,
                cited_claims=0,
            )

            result = await section_iterator.refine_section_iteratively(
                section_title="Test Section",
                section_purpose="Test purpose",
                initial_content="Content without citations.",
                context={},
                session_id="test_session",
                user_id="test_user",
                language="ko",
            )

            # Should identify need for citations
            quality_history = result["quality_history"]
            assert quality_history[0].quality.citation_coverage == 0.0


# ============================================================================
# AbstractGenerator Tests
# ============================================================================

class TestAbstractGenerator:
    """Test AbstractGenerator for abstract creation and refinement."""

    @pytest.mark.asyncio
    async def test_generate_abstract_from_summaries(self, abstract_generator):
        """Test abstract generation from section summaries."""
        section_summaries = [
            {"title": "Introduction", "summary": "Summary of introduction"},
            {"title": "Methods", "summary": "Summary of methods"},
            {"title": "Results", "summary": "Summary of results"},
        ]

        # agent_name is a plain str, so the old patch.object(..., "__str__") on it
        # raised TypeError before the test could run. Only the LLM needs patching.
        with patch(
            "neos.agents.search_agents.hyper_deep_research.iterative_refiner.create_tracked_llm"
        ) as mock_llm_factory:
            mock_llm = AsyncMock()
            mock_llm.ainvoke.return_value = MagicMock(
                content="Generated abstract based on summaries."
            )
            mock_llm_factory.return_value = mock_llm

            abstract = await abstract_generator.generate_abstract_from_summaries(
                section_summaries=section_summaries,
                query="Test query",
                session_id="test_session",
                user_id="test_user",
                language="ko",
            )

            assert len(abstract) > 0
            assert isinstance(abstract, str)

    @pytest.mark.asyncio
    async def test_refine_abstract_not_needed(self, abstract_generator):
        """Test abstract refinement when no refinement is needed."""
        current_abstract = "Current abstract."
        refined_sections = [
            {"section_title": "Introduction", "final_content": "Content"}
        ]

        with patch.object(
            abstract_generator, "_check_abstract_alignment", new=AsyncMock()
        ) as mock_check:
            mock_check.return_value = False  # No refinement needed

            result = await abstract_generator.refine_abstract_if_needed(
                current_abstract=current_abstract,
                refined_sections=refined_sections,
                query="Test query",
                session_id="test_session",
                user_id="test_user",
                language="ko",
            )

            assert result["refinement_needed"] is False
            assert result["refined_abstract"] == current_abstract

    @pytest.mark.asyncio
    async def test_refine_abstract_needed(self, abstract_generator):
        """Test abstract refinement when refinement is needed."""
        current_abstract = "Outdated abstract."
        refined_sections = [
            {"section_title": "Introduction", "final_content": "New content"}
        ]

        with patch.object(
            abstract_generator, "_check_abstract_alignment", new=AsyncMock()
        ) as mock_check, patch.object(
            abstract_generator, "_summarize_section", new=AsyncMock()
        ) as mock_summarize, patch.object(
            abstract_generator, "generate_abstract_from_summaries", new=AsyncMock()
        ) as mock_generate:
            mock_check.return_value = True  # Refinement needed
            mock_summarize.return_value = "Section summary"
            mock_generate.return_value = "Refined abstract"

            result = await abstract_generator.refine_abstract_if_needed(
                current_abstract=current_abstract,
                refined_sections=refined_sections,
                query="Test query",
                session_id="test_session",
                user_id="test_user",
                language="ko",
            )

            assert result["refinement_needed"] is True
            assert result["refined_abstract"] == "Refined abstract"


# ============================================================================
# ConsistencyAligner Tests
# ============================================================================

class TestConsistencyAligner:
    """Test ConsistencyAligner for section-abstract consistency."""

    @pytest.mark.asyncio
    async def test_align_section_already_consistent(
        self, consistency_aligner, mock_citation_tracker
    ):
        """Test alignment when section is already consistent."""
        with patch.object(
            consistency_aligner, "_identify_consistency_issues", new=AsyncMock()
        ) as mock_identify:
            mock_identify.return_value = []  # No issues

            result = await consistency_aligner.align_section_with_abstract(
                section_title="Introduction",
                section_content="Consistent content with abstract.",
                abstract="Abstract content.",
                query="Test query",
                session_id="test_session",
                user_id="test_user",
                language="ko",
            )

            assert result["consistency_score"] == 1.0
            assert result["changes_made"] is False
            assert result["aligned_content"] == "Consistent content with abstract."

    @pytest.mark.asyncio
    async def test_align_section_with_issues(
        self, consistency_aligner, mock_citation_tracker
    ):
        """Test alignment when consistency issues are found."""
        with patch.object(
            consistency_aligner, "_identify_consistency_issues", new=AsyncMock()
        ) as mock_identify, patch.object(
            consistency_aligner, "_realign_section", new=AsyncMock()
        ) as mock_realign:
            mock_identify.return_value = ["Issue 1", "Issue 2"]
            mock_realign.return_value = "Realigned content."

            result = await consistency_aligner.align_section_with_abstract(
                section_title="Introduction",
                section_content="Inconsistent content.",
                abstract="Abstract content.",
                query="Test query",
                session_id="test_session",
                user_id="test_user",
                language="ko",
            )

            assert result["changes_made"] is True
            assert result["aligned_content"] == "Realigned content."
            assert len(result["issues_found"]) == 2

    @pytest.mark.asyncio
    async def test_align_section_with_invalid_citations_auto_fix(
        self, consistency_aligner, mock_citation_tracker
    ):
        """Test auto-fix of invalid citations during alignment."""
        # Mock invalid citations
        mock_citation_tracker.validate_citations.return_value = {
            "valid": False,
            "invalid_citations": [99],
        }

        with patch.object(
            consistency_aligner, "_identify_consistency_issues", new=AsyncMock()
        ) as mock_identify, patch.object(
            consistency_aligner, "_realign_section", new=AsyncMock()
        ) as mock_realign, patch.object(
            consistency_aligner, "_fix_invalid_citations", new=AsyncMock()
        ) as mock_fix:
            # Must be non-empty: align_section_with_abstract returns early when
            # there are no consistency issues, so realign/fix would never run.
            mock_identify.return_value = ["Tone mismatch with abstract"]
            mock_realign.return_value = "Content with [99]"
            mock_fix.return_value = "Content with [1,2]"  # Fixed

            result = await consistency_aligner.align_section_with_abstract(
                section_title="Introduction",
                section_content="Original content.",
                abstract="Abstract.",
                query="Test",
                session_id="test_session",
                user_id="test_user",
                language="ko",
            )

            # Should have called fix
            mock_fix.assert_called_once()
            assert result["aligned_content"] == "Content with [1,2]"


# ============================================================================
# Retry Decorator Tests
# ============================================================================

class TestRetryDecorator:
    """Test retry_on_llm_error decorator."""

    @pytest.mark.asyncio
    async def test_retry_success_on_first_attempt(self):
        """Test function succeeds on first attempt."""
        @retry_on_llm_error(max_retries=3, base_delay=0.01)
        async def successful_function():
            return "success"

        result = await successful_function()
        assert result == "success"

    @pytest.mark.asyncio
    async def test_retry_success_after_transient_error(self):
        """Test retry after transient error."""
        call_count = 0

        @retry_on_llm_error(max_retries=3, base_delay=0.01)
        async def function_with_transient_error():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("Rate limit exceeded (429)")
            return "success"

        result = await function_with_transient_error()
        assert result == "success"
        assert call_count == 2  # Failed once, succeeded on retry

    @pytest.mark.asyncio
    async def test_retry_failure_after_max_attempts(self):
        """Test failure after max retry attempts."""
        @retry_on_llm_error(max_retries=3, base_delay=0.01)
        async def always_failing_function():
            raise Exception("Rate limit exceeded (429)")

        with pytest.raises(Exception, match="Rate limit"):
            await always_failing_function()

    @pytest.mark.asyncio
    async def test_retry_non_transient_error_no_retry(self):
        """Test that non-transient errors are not retried."""
        call_count = 0

        @retry_on_llm_error(max_retries=3, base_delay=0.01)
        async def function_with_non_transient_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("Invalid input")  # Non-transient

        with pytest.raises(ValueError, match="Invalid input"):
            await function_with_non_transient_error()

        assert call_count == 1  # Should not retry

    @pytest.mark.asyncio
    async def test_retry_timeout_error(self):
        """Test retry on TimeoutError."""
        call_count = 0

        @retry_on_llm_error(max_retries=3, base_delay=0.01)
        async def function_with_timeout():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise asyncio.TimeoutError()
            return "success"

        result = await function_with_timeout()
        assert result == "success"
        assert call_count == 2


# ============================================================================
# Integration Tests (Light)
# ============================================================================

class TestIterativeReportRefinerBasic:
    """Basic tests for IterativeReportRefiner orchestration."""

    def test_initialization(self, iterative_refiner):
        """Test proper initialization of refiner."""
        assert iterative_refiner.agent_name == "test_agent"
        assert iterative_refiner.max_iterations == 3
        assert iterative_refiner.quality_threshold == 0.8
        assert iterative_refiner.section_iterator is not None
        assert iterative_refiner.abstract_generator is not None
        assert iterative_refiner.consistency_aligner is not None

    def test_config_loading(self):
        """Test config loading and defaults."""
        config = {
            "max_iterations_per_section": 5,
            "section_quality_threshold": 0.9,
            "max_concurrent_refinements": 8,
        }
        refiner = IterativeReportRefiner(
            agent_name="test", citation_tracker=Mock(), config=config
        )

        assert refiner.max_iterations == 5
        assert refiner.quality_threshold == 0.9
        assert refiner.config.get("max_concurrent_refinements") == 8


# ============================================================================
# ResearchConfig Tests (NEW - P3 Enhancement)
# ============================================================================

class TestResearchConfigWeights:
    """Test ResearchConfig quality weights normalization and validation."""

    def test_get_normalized_weights_with_none(self):
        """Test that default weights are returned when quality_metric_weights is None."""
        from neos.agents.search_agents.hyper_deep_research.config import ResearchConfig

        config = ResearchConfig(quality_metric_weights=None)
        weights = config.get_normalized_quality_weights()

        # Should return default weights
        assert weights["citation_coverage"] == 0.30
        assert weights["citation_quality"] == 0.25
        assert weights["coherence"] == 0.20
        assert weights["completeness"] == 0.15
        assert weights["clarity"] == 0.10

        # Should sum to 1.0
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_get_normalized_weights_already_normalized(self):
        """Test weights that already sum to 1.0."""
        from neos.agents.search_agents.hyper_deep_research.config import ResearchConfig

        custom_weights = {
            "citation_coverage": 0.3,
            "citation_quality": 0.3,
            "coherence": 0.2,
            "completeness": 0.1,
            "clarity": 0.1,
        }

        config = ResearchConfig(quality_metric_weights=custom_weights)
        weights = config.get_normalized_quality_weights()

        # Should return unchanged (already sum to 1.0)
        assert weights["citation_coverage"] == 0.3
        assert weights["citation_quality"] == 0.3
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_get_normalized_weights_needs_normalization(self):
        """Test weights that need normalization (sum != 1.0)."""
        from neos.agents.search_agents.hyper_deep_research.config import ResearchConfig

        # Weights sum to 10 (not 1.0)
        custom_weights = {
            "citation_coverage": 4,
            "citation_quality": 3,
            "coherence": 2,
            "completeness": 1,
            "clarity": 0,
        }

        config = ResearchConfig(quality_metric_weights=custom_weights)
        weights = config.get_normalized_quality_weights()

        # Should be normalized to sum to 1.0
        assert abs(weights["citation_coverage"] - 0.4) < 0.001  # 4/10
        assert abs(weights["citation_quality"] - 0.3) < 0.001   # 3/10
        assert abs(weights["coherence"] - 0.2) < 0.001          # 2/10
        assert abs(weights["completeness"] - 0.1) < 0.001       # 1/10
        assert abs(weights["clarity"] - 0.0) < 0.001            # 0/10
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_get_normalized_weights_invalid_negative(self):
        """Test that negative weights raise ValueError."""
        from neos.agents.search_agents.hyper_deep_research.config import ResearchConfig

        custom_weights = {
            "citation_coverage": -0.1,  # Negative!
            "citation_quality": 0.3,
            "coherence": 0.2,
            "completeness": 0.1,
            "clarity": 0.1,
        }

        config = ResearchConfig(quality_metric_weights=custom_weights)

        with pytest.raises(ValueError, match="non-negative"):
            config.get_normalized_quality_weights()

    def test_get_normalized_weights_invalid_zero_sum(self):
        """Test that weights summing to zero raise ValueError."""
        from neos.agents.search_agents.hyper_deep_research.config import ResearchConfig

        custom_weights = {
            "citation_coverage": 0.0,
            "citation_quality": 0.0,
            "coherence": 0.0,
            "completeness": 0.0,
            "clarity": 0.0,
        }

        config = ResearchConfig(quality_metric_weights=custom_weights)

        with pytest.raises(ValueError, match="cannot be zero"):
            config.get_normalized_quality_weights()

    def test_get_normalized_weights_partial_keys(self):
        """Test normalization with partial keys (only some metrics)."""
        from neos.agents.search_agents.hyper_deep_research.config import ResearchConfig

        # Only provide 2 metrics
        custom_weights = {
            "citation_coverage": 3,
            "citation_quality": 2,
        }

        config = ResearchConfig(quality_metric_weights=custom_weights)
        weights = config.get_normalized_quality_weights()

        # Should normalize provided keys
        assert abs(weights["citation_coverage"] - 0.6) < 0.001  # 3/5
        assert abs(weights["citation_quality"] - 0.4) < 0.001   # 2/5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

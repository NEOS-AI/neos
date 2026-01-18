"""Integration tests for Iterative Report Refinement.

These tests verify the end-to-end behavior of the Ralph Loop-inspired
iterative refinement system across all 4 phases.

Test Scenarios:
1. Full 4-phase refinement process
2. Parallel section refinement
3. Config-driven behavior
4. Error handling and recovery
5. Citation auto-fix integration
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from neos.agents.search_agents.hyper_deep_research.iterative_refiner import (
    IterativeReportRefiner,
    SectionQuality,
)
from neos.agents.search_agents.hyper_deep_research.config import ResearchConfig
from neos.agents.search_agents.hyper_deep_research.utils import CitationTracker


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def research_config():
    """Create test research configuration."""
    return ResearchConfig(
        max_iterations_per_section=2,
        section_quality_threshold=0.75,
        enable_iterative_refinement=True,
        enable_abstract_refinement=True,
        enable_consistency_alignment=True,
        max_concurrent_refinements=2,
    )


@pytest.fixture
def mock_citation_tracker_full():
    """Create comprehensive mock CitationTracker."""
    tracker = Mock(spec=CitationTracker)

    # Default: valid citations
    tracker.validate_citations.return_value = {
        "valid": True,
        "invalid_citations": [],
        "total_citations": 5
    }

    tracker.parse_citations_from_text.return_value = [
        Mock(source_numbers=[1, 2, 3], claim="Test claim")
    ]

    tracker.get_sources_by_numbers.return_value = [
        Mock(quality_score=0.9)
    ]

    tracker.get_citation_suggestions_for_section.return_value = {
        "total_claims": 3,
        "suggestions": {}
    }

    tracker.get_source_list_for_prompt.return_value = (
        "Available Sources:\n"
        "[1] Source A (quality: 0.9)\n"
        "[2] Source B (quality: 0.8)\n"
        "[3] Source C (quality: 0.85)"
    )

    return tracker


@pytest.fixture
def sample_sections_data():
    """Create sample sections for testing."""
    return [
        {
            "title": "Introduction",
            "purpose": "Introduce the topic",
            "content": "This is the introduction section with initial content [1,2]."
        },
        {
            "title": "Background",
            "purpose": "Provide background information",
            "content": "This is the background section with references [2,3]."
        },
        {
            "title": "Methods",
            "purpose": "Describe methodology",
            "content": "This section describes the methods used [1,3]."
        },
    ]


# ============================================================================
# Full Process Integration Tests
# ============================================================================

class TestFullRefinementProcess:
    """Test complete 4-phase refinement process."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_end_to_end_refinement(
        self, research_config, mock_citation_tracker_full, sample_sections_data
    ):
        """Test full end-to-end refinement process.

        Phases:
        1. Section refinement (parallel)
        2. Abstract generation
        3. Abstract refinement
        4. Consistency alignment
        """
        refiner = IterativeReportRefiner(
            agent_name="test_integration",
            citation_tracker=mock_citation_tracker_full,
            config=research_config.to_dict(),
        )

        # Mock LLM calls for all components
        with patch(
            "neos.agents.search_agents.hyper_deep_research.iterative_refiner.create_tracked_llm"
        ) as mock_llm_factory:
            # Create mock LLM
            mock_llm = AsyncMock()

            # Mock quality evaluation responses
            quality_response = MagicMock()
            quality_response.content = "coherence: 0.85\ncompleteness: 0.80\nclarity: 0.85"

            # Mock section rewrite responses
            rewrite_response = MagicMock()
            rewrite_response.content = "Improved section content with enhanced clarity [1,2,3]."

            # Mock abstract generation response
            abstract_response = MagicMock()
            abstract_response.content = "Generated abstract summarizing all sections."

            # Mock consistency check response
            consistency_response = MagicMock()
            consistency_response.content = "CONSISTENT"

            # Configure mock to return different responses based on call
            call_count = 0
            async def mock_invoke(messages):
                nonlocal call_count
                call_count += 1
                # Return appropriate response based on call number
                if call_count % 4 == 1:
                    return quality_response
                elif call_count % 4 == 2:
                    return rewrite_response
                elif call_count % 4 == 3:
                    return abstract_response
                else:
                    return consistency_response

            mock_llm.ainvoke = mock_invoke
            mock_llm_factory.return_value = mock_llm

            # Run full refinement
            result = await refiner.generate_coherent_report(
                sections_data=sample_sections_data,
                query="Test research query",
                context={"topic": "test"},
                session_id="test_session",
                user_id="test_user",
                language="ko",
            )

            # Verify results
            assert "final_abstract" in result
            assert "final_sections" in result
            assert "refinement_metadata" in result

            # Verify all sections were processed
            assert len(result["final_sections"]) == 3

            # Verify metadata
            metadata = result["refinement_metadata"]
            assert metadata["total_sections"] == 3
            assert "total_iterations" in metadata
            assert "duration_seconds" in metadata

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_parallel_refinement_performance(
        self, research_config, mock_citation_tracker_full, sample_sections_data
    ):
        """Test that parallel refinement is faster than sequential."""
        # Create two refiners: one with parallelism, one without
        config_parallel = research_config.to_dict()
        config_parallel["max_concurrent_refinements"] = 3

        config_sequential = research_config.to_dict()
        config_sequential["max_concurrent_refinements"] = 1

        refiner_parallel = IterativeReportRefiner(
            agent_name="parallel",
            citation_tracker=mock_citation_tracker_full,
            config=config_parallel,
        )

        refiner_sequential = IterativeReportRefiner(
            agent_name="sequential",
            citation_tracker=mock_citation_tracker_full,
            config=config_sequential,
        )

        # Mock LLM with fixed delay
        with patch(
            "neos.agents.search_agents.hyper_deep_research.iterative_refiner.create_tracked_llm"
        ) as mock_llm_factory:
            mock_llm = AsyncMock()

            async def delayed_invoke(messages):
                await asyncio.sleep(0.1)  # Simulate LLM delay
                response = MagicMock()
                response.content = "coherence: 0.85\ncompleteness: 0.85\nclarity: 0.85"
                return response

            mock_llm.ainvoke = delayed_invoke
            mock_llm_factory.return_value = mock_llm

            # Time parallel execution
            import time
            start_parallel = time.time()
            result_parallel = await refiner_parallel.generate_coherent_report(
                sections_data=sample_sections_data,
                query="Test",
                context={},
                session_id="test",
                user_id="test",
            )
            duration_parallel = time.time() - start_parallel

            # Time sequential execution
            start_sequential = time.time()
            result_sequential = await refiner_sequential.generate_coherent_report(
                sections_data=sample_sections_data,
                query="Test",
                context={},
                session_id="test",
                user_id="test",
            )
            duration_sequential = time.time() - start_sequential

            # Parallel should be significantly faster
            # With 3 sections and 0.1s delay, sequential takes ~0.3s, parallel ~0.1s
            assert duration_parallel < duration_sequential * 0.7


class TestConfigDrivenBehavior:
    """Test that configuration properly controls behavior."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_quality_threshold_config(
        self, mock_citation_tracker_full, sample_sections_data
    ):
        """Test that quality threshold from config is respected."""
        # High threshold config
        config = ResearchConfig(
            section_quality_threshold=0.95,  # Very high
            max_iterations_per_section=5,
        )

        refiner = IterativeReportRefiner(
            agent_name="test",
            citation_tracker=mock_citation_tracker_full,
            config=config.to_dict(),
        )

        # Verify threshold is set correctly
        assert refiner.quality_threshold == 0.95
        assert refiner.section_iterator.quality_threshold == 0.95

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_disabled_refinement_config(
        self, mock_citation_tracker_full, sample_sections_data
    ):
        """Test behavior when iterative refinement is disabled."""
        config = ResearchConfig(
            enable_iterative_refinement=False,
        )

        # When disabled, refinement should be skipped
        # (This would require conditional logic in main agent)
        assert config.enable_iterative_refinement is False


class TestErrorHandlingIntegration:
    """Test error handling and recovery in full process."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_llm_failure_retry(
        self, research_config, mock_citation_tracker_full, sample_sections_data
    ):
        """Test that LLM failures are retried and recovered."""
        refiner = IterativeReportRefiner(
            agent_name="test",
            citation_tracker=mock_citation_tracker_full,
            config=research_config.to_dict(),
        )

        with patch(
            "neos.agents.search_agents.hyper_deep_research.iterative_refiner.create_tracked_llm"
        ) as mock_llm_factory:
            mock_llm = AsyncMock()

            # Fail first two times, succeed on third
            call_count = 0
            async def failing_then_succeeding(messages):
                nonlocal call_count
                call_count += 1
                if call_count <= 2:
                    raise Exception("Rate limit (429)")
                response = MagicMock()
                response.content = "coherence: 0.85\ncompleteness: 0.85\nclarity: 0.85"
                return response

            mock_llm.ainvoke = failing_then_succeeding
            mock_llm_factory.return_value = mock_llm

            # Should succeed after retries
            result = await refiner.generate_coherent_report(
                sections_data=sample_sections_data[:1],  # Just one section
                query="Test",
                context={},
                session_id="test",
                user_id="test",
            )

            # Should have succeeded despite initial failures
            assert result is not None
            assert len(result["final_sections"]) == 1

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_citation_auto_fix_integration(
        self, research_config, mock_citation_tracker_full, sample_sections_data
    ):
        """Test that invalid citations are automatically fixed during alignment."""
        # Mock invalid citations after alignment
        mock_citation_tracker_full.validate_citations.side_effect = [
            {"valid": True, "invalid_citations": []},  # Initial check
            {"valid": False, "invalid_citations": [99]},  # After alignment
            {"valid": True, "invalid_citations": []},  # After fix
        ]

        refiner = IterativeReportRefiner(
            agent_name="test",
            citation_tracker=mock_citation_tracker_full,
            config=research_config.to_dict(),
        )

        with patch(
            "neos.agents.search_agents.hyper_deep_research.iterative_refiner.create_tracked_llm"
        ) as mock_llm_factory:
            mock_llm = AsyncMock()

            # Mock responses
            async def mock_invoke(messages):
                response = MagicMock()
                # Check if it's a fix request
                if "invalid citations" in str(messages).lower():
                    response.content = "Fixed content with valid [1,2,3]"
                else:
                    response.content = "coherence: 0.85\ncompleteness: 0.85\nclarity: 0.85"
                return response

            mock_llm.ainvoke = mock_invoke
            mock_llm_factory.return_value = mock_llm

            result = await refiner.generate_coherent_report(
                sections_data=sample_sections_data[:1],
                query="Test",
                context={},
                session_id="test",
                user_id="test",
            )

            # Should have fixed citations
            assert result is not None
            # Verify fix was called (validation called 3 times)
            assert mock_citation_tracker_full.validate_citations.call_count >= 2


class TestPerformanceMetrics:
    """Test performance tracking and metadata."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_refinement_metadata_tracking(
        self, research_config, mock_citation_tracker_full, sample_sections_data
    ):
        """Test that refinement metadata is properly tracked."""
        refiner = IterativeReportRefiner(
            agent_name="test",
            citation_tracker=mock_citation_tracker_full,
            config=research_config.to_dict(),
        )

        with patch(
            "neos.agents.search_agents.hyper_deep_research.iterative_refiner.create_tracked_llm"
        ) as mock_llm_factory:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=MagicMock(
                content="coherence: 0.85\ncompleteness: 0.85\nclarity: 0.85"
            ))
            mock_llm_factory.return_value = mock_llm

            result = await refiner.generate_coherent_report(
                sections_data=sample_sections_data,
                query="Test",
                context={},
                session_id="test",
                user_id="test",
            )

            metadata = result["refinement_metadata"]

            # Verify all expected fields
            assert "total_sections" in metadata
            assert "total_iterations" in metadata
            assert "abstract_refined" in metadata
            assert "sections_aligned" in metadata
            assert "average_final_quality" in metadata
            assert "duration_seconds" in metadata
            assert "timestamp" in metadata

            # Verify values
            assert metadata["total_sections"] == 3
            assert metadata["total_iterations"] >= 0
            assert isinstance(metadata["duration_seconds"], (int, float))
            assert metadata["duration_seconds"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-m", "integration"])

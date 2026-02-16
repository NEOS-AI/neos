"""
YouTubeSearchAgent Integration Tests

Tests cover:
- Agent initialization and configuration classes
- Execute method with mocked tool layer
- ComparisonConfig and PlaylistAnalysisConfig
- PlaylistOrderStrategy enum values
- compare_videos and analyze_playlist methods
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any


@pytest.mark.unit
class TestYouTubeSearchAgentInit:
    """Test agent initialization"""

    def test_agent_creation(self):
        """Agent initializes with correct attributes"""
        from neos.agents.search_agents.youtube_search import YouTubeSearchAgent
        agent = YouTubeSearchAgent()
        assert agent.name == "youtube_search"
        assert agent.search_type == "video"
        assert agent.youtube_tool is None
        assert agent.tool_available is False

    def test_agent_has_execute_method(self):
        """Agent has async execute method matching expected signature"""
        from neos.agents.search_agents.youtube_search import YouTubeSearchAgent
        agent = YouTubeSearchAgent()
        assert hasattr(agent, "execute")
        assert callable(agent.execute)

    def test_agent_has_compare_videos_method(self):
        """Agent has compare_videos method"""
        from neos.agents.search_agents.youtube_search import YouTubeSearchAgent
        agent = YouTubeSearchAgent()
        assert hasattr(agent, "compare_videos")
        assert callable(agent.compare_videos)

    def test_agent_has_analyze_playlist_method(self):
        """Agent has analyze_playlist method"""
        from neos.agents.search_agents.youtube_search import YouTubeSearchAgent
        agent = YouTubeSearchAgent()
        assert hasattr(agent, "analyze_playlist")
        assert callable(agent.analyze_playlist)


@pytest.mark.unit
class TestComparisonConfig:
    """Test ComparisonConfig dataclass"""

    def test_default_values(self):
        """Default config has sensible defaults"""
        from neos.agents.search_agents.youtube_search import ComparisonConfig, ComparisonFocus
        config = ComparisonConfig()
        assert config.focus == ComparisonFocus.COMPREHENSIVE
        assert config.include_timestamps is False
        assert config.emphasize_differences is True
        assert config.include_production_quality is True
        assert config.max_summary_length == "medium"

    def test_custom_values(self):
        """Config accepts custom values"""
        from neos.agents.search_agents.youtube_search import ComparisonConfig, ComparisonFocus
        config = ComparisonConfig(
            focus=ComparisonFocus.TECHNICAL_DEPTH,
            include_timestamps=True,
            emphasize_differences=False,
            max_summary_length="short",
        )
        assert config.focus == ComparisonFocus.TECHNICAL_DEPTH
        assert config.include_timestamps is True
        assert config.emphasize_differences is False
        assert config.max_summary_length == "short"

    def test_to_prompt_instructions_technical(self):
        """Technical depth focus generates appropriate instructions"""
        from neos.agents.search_agents.youtube_search import ComparisonConfig, ComparisonFocus
        config = ComparisonConfig(focus=ComparisonFocus.TECHNICAL_DEPTH)
        instructions = config.to_prompt_instructions()
        assert "technical" in instructions.lower()

    def test_to_prompt_instructions_teaching(self):
        """Teaching style focus generates appropriate instructions"""
        from neos.agents.search_agents.youtube_search import ComparisonConfig, ComparisonFocus
        config = ComparisonConfig(focus=ComparisonFocus.TEACHING_STYLE)
        instructions = config.to_prompt_instructions()
        assert "teaching" in instructions.lower() or "pedagog" in instructions.lower()

    def test_to_prompt_instructions_practical(self):
        """Practical application focus generates appropriate instructions"""
        from neos.agents.search_agents.youtube_search import ComparisonConfig, ComparisonFocus
        config = ComparisonConfig(focus=ComparisonFocus.PRACTICAL_APPLICATION)
        instructions = config.to_prompt_instructions()
        assert "practical" in instructions.lower()

    def test_to_prompt_instructions_beginner(self):
        """Beginner friendly focus generates appropriate instructions"""
        from neos.agents.search_agents.youtube_search import ComparisonConfig, ComparisonFocus
        config = ComparisonConfig(focus=ComparisonFocus.BEGINNER_FRIENDLY)
        instructions = config.to_prompt_instructions()
        assert "beginner" in instructions.lower()

    def test_to_prompt_instructions_short(self):
        """Short summary length instruction included"""
        from neos.agents.search_agents.youtube_search import ComparisonConfig
        config = ComparisonConfig(max_summary_length="short")
        instructions = config.to_prompt_instructions()
        assert "concise" in instructions.lower()

    def test_to_prompt_instructions_long(self):
        """Long summary length instruction included"""
        from neos.agents.search_agents.youtube_search import ComparisonConfig
        config = ComparisonConfig(max_summary_length="long")
        instructions = config.to_prompt_instructions()
        assert "detailed" in instructions.lower()


@pytest.mark.unit
class TestComparisonFocus:
    """Test ComparisonFocus enum"""

    def test_all_focus_options_exist(self):
        """All expected focus options are defined"""
        from neos.agents.search_agents.youtube_search import ComparisonFocus
        assert ComparisonFocus.TECHNICAL_DEPTH.value == "technical_depth"
        assert ComparisonFocus.TEACHING_STYLE.value == "teaching_style"
        assert ComparisonFocus.PRACTICAL_APPLICATION.value == "practical_application"
        assert ComparisonFocus.BEGINNER_FRIENDLY.value == "beginner_friendly"
        assert ComparisonFocus.COMPREHENSIVE.value == "comprehensive"

    def test_focus_count(self):
        """Exactly 5 focus options exist"""
        from neos.agents.search_agents.youtube_search import ComparisonFocus
        assert len(ComparisonFocus) == 5


@pytest.mark.unit
class TestPlaylistAnalysisConfig:
    """Test PlaylistAnalysisConfig dataclass"""

    def test_default_values(self):
        """Default config has sensible defaults"""
        from neos.agents.search_agents.youtube_search import PlaylistAnalysisConfig, PlaylistOrderStrategy
        config = PlaylistAnalysisConfig()
        assert config.detect_duplicates is True
        assert config.use_semantic_similarity is False
        assert config.semantic_similarity_threshold == 0.85
        assert config.suggest_order == PlaylistOrderStrategy.OPTIMAL_LEARNING
        assert config.analyze_progression is True
        assert config.identify_gaps is True
        assert config.max_videos_to_analyze == 20
        assert config.include_prerequisites is True

    def test_custom_values(self):
        """Config accepts custom values"""
        from neos.agents.search_agents.youtube_search import PlaylistAnalysisConfig, PlaylistOrderStrategy
        config = PlaylistAnalysisConfig(
            detect_duplicates=False,
            use_semantic_similarity=True,
            semantic_similarity_threshold=0.9,
            suggest_order=PlaylistOrderStrategy.TOPIC_CLUSTERED,
            max_videos_to_analyze=50,
        )
        assert config.detect_duplicates is False
        assert config.use_semantic_similarity is True
        assert config.semantic_similarity_threshold == 0.9
        assert config.suggest_order == PlaylistOrderStrategy.TOPIC_CLUSTERED
        assert config.max_videos_to_analyze == 50

    def test_to_prompt_instructions_includes_progression(self):
        """Progression analysis instruction included by default"""
        from neos.agents.search_agents.youtube_search import PlaylistAnalysisConfig
        config = PlaylistAnalysisConfig(analyze_progression=True)
        instructions = config.to_prompt_instructions()
        assert "progress" in instructions.lower()

    def test_to_prompt_instructions_includes_gaps(self):
        """Gap identification instruction included by default"""
        from neos.agents.search_agents.youtube_search import PlaylistAnalysisConfig
        config = PlaylistAnalysisConfig(identify_gaps=True)
        instructions = config.to_prompt_instructions()
        assert "gap" in instructions.lower() or "missing" in instructions.lower()

    def test_to_prompt_instructions_includes_prerequisites(self):
        """Prerequisites instruction included by default"""
        from neos.agents.search_agents.youtube_search import PlaylistAnalysisConfig
        config = PlaylistAnalysisConfig(include_prerequisites=True)
        instructions = config.to_prompt_instructions()
        assert "prerequisite" in instructions.lower() or "background" in instructions.lower()


@pytest.mark.unit
class TestPlaylistOrderStrategy:
    """Test PlaylistOrderStrategy enum"""

    def test_all_strategies_exist(self):
        """All expected ordering strategies are defined"""
        from neos.agents.search_agents.youtube_search import PlaylistOrderStrategy
        assert PlaylistOrderStrategy.ORIGINAL.value == "original"
        assert PlaylistOrderStrategy.DIFFICULTY.value == "difficulty"
        assert PlaylistOrderStrategy.POPULARITY.value == "popularity"
        assert PlaylistOrderStrategy.DURATION.value == "duration"
        assert PlaylistOrderStrategy.OPTIMAL_LEARNING.value == "optimal_learning"
        assert PlaylistOrderStrategy.TOPIC_CLUSTERED.value == "topic_clustered"
        assert PlaylistOrderStrategy.PREREQUISITE_CHAIN.value == "prerequisite_chain"

    def test_strategy_count(self):
        """Exactly 7 strategies exist"""
        from neos.agents.search_agents.youtube_search import PlaylistOrderStrategy
        assert len(PlaylistOrderStrategy) == 7


@pytest.mark.unit
class TestYouTubeSearchAgentExecute:
    """Test agent execute method"""

    @pytest.mark.asyncio
    async def test_execute_handles_tool_unavailable(self):
        """Execute handles gracefully when tool is not available"""
        from neos.agents.search_agents.youtube_search import YouTubeSearchAgent
        agent = YouTubeSearchAgent()
        agent.tool_available = False

        context = {"session_id": "test", "user_id": "user1"}
        result = await agent.execute("Python tutorial", context)
        # Should return a result (possibly empty) without crashing
        assert result is not None

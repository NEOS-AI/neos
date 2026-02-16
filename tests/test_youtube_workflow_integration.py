"""
YouTube Workflow Integration Tests

Tests cover:
- QueryClassifier YouTube intent detection (keywords and URLs)
- Agent routing for YouTube queries
- SEARCH_AGENTS configuration includes youtube_search
- graph.py agents dict includes youtube_search
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neos.workflow.enums import IntentType
from neos.workflow.state import WorkflowConfig


@pytest.mark.unit
class TestIntentTypeYouTube:
    """Test IntentType enum includes YouTube"""

    def test_youtube_search_intent_exists(self):
        """YOUTUBE_SEARCH intent is defined"""
        assert hasattr(IntentType, "YOUTUBE_SEARCH")
        assert IntentType.YOUTUBE_SEARCH.value == "youtube_search"


@pytest.mark.unit
class TestWorkflowConfigYouTube:
    """Test WorkflowConfig includes YouTube agent"""

    def test_search_agents_includes_youtube(self):
        """youtube_search is in SEARCH_AGENTS list"""
        config = WorkflowConfig()
        assert "youtube_search" in config.SEARCH_AGENTS

    def test_query_intents_includes_youtube(self):
        """youtube_search is in QUERY_INTENTS list"""
        config = WorkflowConfig()
        assert "youtube_search" in config.QUERY_INTENTS


@pytest.mark.unit
class TestQueryClassifierYouTube:
    """Test QueryClassifier YouTube intent detection"""

    @pytest.fixture
    def classifier(self):
        """Create a QueryClassifier instance"""
        from neos.workflow.utils.query_classifier import QueryClassifier
        config = WorkflowConfig()
        return QueryClassifier(config)

    def test_youtube_keywords_registered(self, classifier):
        """YouTube keywords are in intent_keywords dict"""
        assert IntentType.YOUTUBE_SEARCH.value in classifier.intent_keywords
        keywords = classifier.intent_keywords[IntentType.YOUTUBE_SEARCH.value]
        assert "youtube" in keywords
        assert "유튜브" in keywords
        assert "video" in keywords
        assert "영상" in keywords

    @pytest.mark.asyncio
    async def test_classify_youtube_keyword_query(self, classifier):
        """Query with 'youtube' keyword classifies as youtube_search"""
        intent = await classifier._classify_intent("youtube에서 파이썬 강좌 검색해줘")
        assert intent == IntentType.YOUTUBE_SEARCH.value

    @pytest.mark.asyncio
    async def test_classify_korean_youtube_query(self, classifier):
        """Korean YouTube query classifies correctly"""
        intent = await classifier._classify_intent("유튜브 파이썬 튜토리얼 찾아줘")
        assert intent == IntentType.YOUTUBE_SEARCH.value

    @pytest.mark.asyncio
    async def test_classify_video_keyword_query(self, classifier):
        """Query with 'video' or '영상' classifies as youtube_search"""
        intent = await classifier._classify_intent("파이썬 관련 영상 추천해줘")
        assert intent == IntentType.YOUTUBE_SEARCH.value

    def test_determine_agents_youtube_intent(self, classifier):
        """YouTube intent selects youtube_search agent"""
        agents = classifier._determine_required_agents(
            query="유튜브에서 파이썬 강좌 찾기",
            intent=IntentType.YOUTUBE_SEARCH.value,
            complexity_score=0.2,
        )
        assert "youtube_search" in agents

    def test_youtube_url_routes_to_youtube_agent(self, classifier):
        """YouTube URL routes to youtube_search instead of web_lookup"""
        agents = classifier._determine_required_agents(
            query="이 영상 요약해줘 https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            intent="information_seeking",
            complexity_score=0.1,
        )
        assert "youtube_search" in agents
        assert "web_lookup" not in agents

    def test_youtu_be_url_routes_to_youtube_agent(self, classifier):
        """Short YouTube URL (youtu.be) routes to youtube_search"""
        agents = classifier._determine_required_agents(
            query="https://youtu.be/dQw4w9WgXcQ 이 비디오 분석해줘",
            intent="information_seeking",
            complexity_score=0.1,
        )
        assert "youtube_search" in agents
        assert "web_lookup" not in agents

    def test_non_youtube_url_routes_to_web_lookup(self, classifier):
        """Non-YouTube URL still routes to web_lookup"""
        agents = classifier._determine_required_agents(
            query="https://docs.python.org/3/ 이 문서 내용 알려줘",
            intent="information_seeking",
            complexity_score=0.1,
        )
        assert "web_lookup" in agents
        assert "youtube_search" not in agents


@pytest.mark.unit
class TestGraphAgentsYouTube:
    """Test graph.py includes YouTubeSearchAgent"""

    def test_graph_agents_dict_has_youtube_search(self):
        """graph.py _initialize_agents includes youtube_search key"""
        from neos.workflow.graph import MultiAgentWorkflow
        workflow = MultiAgentWorkflow()
        assert "youtube_search" in workflow.agents

    def test_youtube_agent_has_execute_method(self):
        """youtube_search agent in graph has callable execute"""
        from neos.workflow.graph import MultiAgentWorkflow
        workflow = MultiAgentWorkflow()
        agent = workflow.agents["youtube_search"]
        assert hasattr(agent, "execute")
        assert callable(agent.execute)

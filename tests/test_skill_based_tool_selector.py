"""
Tests for SkillBasedToolSelector
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from neos.agents.skill_based_tool_selector import SkillBasedToolSelector, SkillToolSelection


class TestSkillBasedToolSelector:
    """Test SkillBasedToolSelector functionality"""

    @pytest.fixture
    def selector(self):
        """Create SkillBasedToolSelector instance"""
        return SkillBasedToolSelector()

    @pytest.fixture
    def mock_skills(self):
        """Mock available skills"""
        return [
            {
                "name": "pdf_skill",
                "type": "document",
                "description": "Process PDF documents",
                "capabilities": ["extract_text", "extract_tables"],
                "version": "1.0.0"
            },
            {
                "name": "bigquery_skill",
                "type": "database",
                "description": "Query BigQuery databases",
                "capabilities": ["sql_query", "data_export"],
                "version": "1.0.0"
            }
        ]

    @pytest.fixture
    def mock_tools(self):
        """Mock available tools"""
        return [
            {
                "name": "web_search",
                "type": "search",
                "description": "Search the web",
                "capabilities": ["search"]
            },
            {
                "name": "data_analysis",
                "type": "analysis",
                "description": "Analyze data",
                "capabilities": ["analysis"]
            }
        ]

    def test_initialization(self, selector):
        """Test SkillBasedToolSelector initialization"""
        assert selector.name == "skill_based_tool_selector"
        assert selector._skill_registry is None
        assert selector._tool_selector is None

    def test_format_skills_list(self, selector, mock_skills):
        """Test skills list formatting"""
        formatted = selector._format_skills_list(mock_skills)
        assert "pdf_skill" in formatted
        assert "bigquery_skill" in formatted
        assert "document" in formatted
        assert "database" in formatted

    def test_format_tools_list(self, selector, mock_tools):
        """Test tools list formatting"""
        formatted = selector._format_tools_list(mock_tools)
        assert "web_search" in formatted
        assert "data_analysis" in formatted
        assert "search" in formatted
        assert "analysis" in formatted

    def test_format_empty_lists(self, selector):
        """Test formatting of empty lists"""
        assert selector._format_skills_list([]) == "None available"
        assert selector._format_tools_list([]) == "None available"

    def test_parse_selection_valid_json(self, selector, mock_skills, mock_tools):
        """Test parsing valid JSON selection"""
        selection_text = """
        ```json
        {
            "selected_skills": ["pdf_skill"],
            "selected_tools": ["web_search"],
            "reasoning": "Need PDF processing and web search",
            "priority_order": [
                {"type": "tool", "name": "web_search", "reason": "search first"},
                {"type": "skill", "name": "pdf_skill", "reason": "process results"}
            ]
        }
        ```
        """
        selection = selector._parse_selection(selection_text, mock_skills, mock_tools)
        assert "pdf_skill" in selection.selected_skills
        assert "web_search" in selection.selected_tools
        assert "Need PDF processing and web search" in selection.reasoning

    def test_parse_selection_invalid_skill(self, selector, mock_skills, mock_tools):
        """Test parsing with invalid skill name"""
        selection_text = """
        {
            "selected_skills": ["invalid_skill", "pdf_skill"],
            "selected_tools": ["web_search"],
            "reasoning": "Test",
            "priority_order": []
        }
        """
        selection = selector._parse_selection(selection_text, mock_skills, mock_tools)
        # invalid_skill should be filtered out
        assert "invalid_skill" not in selection.selected_skills
        assert "pdf_skill" in selection.selected_skills

    def test_create_fallback_selection(self, selector):
        """Test fallback selection creation"""
        context = {
            "intent": "research",
            "query_type": "search"
        }
        selection = selector._create_fallback_selection(context)
        assert isinstance(selection, SkillToolSelection)
        assert "web_search" in selection.selected_tools
        assert "Fallback" in selection.reasoning

    def test_create_fallback_selection_data_analysis(self, selector):
        """Test fallback selection for data analysis"""
        context = {
            "intent": "data analysis",
            "query_type": "analysis"
        }
        selection = selector._create_fallback_selection(context)
        assert "data_analysis" in selection.selected_tools
        assert "bigquery_skill" in selection.selected_skills

    @pytest.mark.asyncio
    async def test_select_skills_and_tools_basic(self, selector, mock_skills, mock_tools):
        """Test basic skill/tool selection (with mocked LLM)"""
        with patch.object(selector, '_get_available_skills', return_value=mock_skills), \
             patch.object(selector, '_get_available_tools', return_value=mock_tools), \
             patch('neos.agents.skill_based_tool_selector.create_llm') as mock_create_llm, \
             patch('neos.agents.skill_based_tool_selector.create_tracked_llm') as mock_create_tracked:

            # Mock LLM response
            mock_response = MagicMock()
            mock_response.content = """
            {
                "selected_skills": ["pdf_skill"],
                "selected_tools": ["web_search"],
                "reasoning": "Test reasoning",
                "priority_order": []
            }
            """

            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_create_tracked.return_value = mock_llm

            selection = await selector.select_skills_and_tools(
                query="Test query",
                context={"intent": "research"},
                session_id="test_session",
                user_id="test_user"
            )

            assert isinstance(selection, SkillToolSelection)
            assert "pdf_skill" in selection.selected_skills
            assert "web_search" in selection.selected_tools

    @pytest.mark.asyncio
    async def test_select_skills_and_tools_error_handling(self, selector):
        """Test error handling in skill/tool selection"""
        with patch.object(selector, '_get_available_skills', side_effect=Exception("Test error")):
            selection = await selector.select_skills_and_tools(
                query="Test query",
                context={"intent": "research"},
                session_id="test_session",
                user_id="test_user"
            )

            # Should return fallback selection
            assert isinstance(selection, SkillToolSelection)

    def test_skill_tool_selection_to_dict(self):
        """Test SkillToolSelection to_dict method"""
        selection = SkillToolSelection(
            selected_skills=["skill1"],
            selected_tools=["tool1"],
            reasoning="Test reasoning",
            priority_order=[{"type": "skill", "name": "skill1", "reason": "test"}]
        )

        result = selection.to_dict()
        assert result["selected_skills"] == ["skill1"]
        assert result["selected_tools"] == ["tool1"]
        assert result["reasoning"] == "Test reasoning"
        assert len(result["priority_order"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

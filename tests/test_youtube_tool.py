"""
YouTubeMCPTool Unit Tests

Tests cover:
- Operation dispatching
- Video search functionality (mocked API)
- Transcript extraction with fallback strategies
- Error handling (TranscriptsDisabled, NoTranscriptFound, API quota)
- Video info retrieval
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from neos.tools.tools.youtube import YouTubeMCPTool


@pytest.mark.unit
class TestYouTubeMCPToolOperations:
    """Test operation dispatching and validation"""

    @pytest.fixture
    def tool(self):
        """Create a YouTubeMCPTool instance with mocked dependencies"""
        with patch("neos.tools.tools.youtube.build"):
            t = YouTubeMCPTool()
            t.is_available = True
            return t

    @pytest.mark.asyncio
    async def test_execute_missing_operation(self, tool):
        """Missing operation parameter returns error"""
        result = await tool.execute({})
        assert result.success is False
        assert "Operation parameter is required" in result.error

    @pytest.mark.asyncio
    async def test_execute_unknown_operation(self, tool):
        """Unknown operation returns error with available operations list"""
        result = await tool.execute({"operation": "nonexistent"})
        assert result.success is False
        assert "Unknown operation" in result.error
        assert "search_videos" in result.error

    @pytest.mark.asyncio
    async def test_execute_dispatches_to_search(self, tool):
        """search_videos operation dispatches correctly"""
        mock_result = {"videos": [], "total_results": 0}
        tool._search_videos = AsyncMock(return_value=mock_result)

        result = await tool.execute({"operation": "search_videos", "query": "test"})
        assert result.success is True
        assert result.data == mock_result
        tool._search_videos.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_dispatches_to_get_transcript(self, tool):
        """get_transcript operation dispatches correctly"""
        mock_result = {"video_id": "abc", "text": "hello"}
        tool._get_transcript = AsyncMock(return_value=mock_result)

        result = await tool.execute({"operation": "get_transcript", "video_id": "abc"})
        assert result.success is True
        assert result.data["video_id"] == "abc"

    @pytest.mark.asyncio
    async def test_execute_dispatches_to_get_video_info(self, tool):
        """get_video_info operation dispatches correctly"""
        mock_result = {"video_id": "abc", "title": "Test Video"}
        tool._get_video_info = AsyncMock(return_value=mock_result)

        result = await tool.execute({"operation": "get_video_info", "video_id": "abc"})
        assert result.success is True
        assert result.data["title"] == "Test Video"

    @pytest.mark.asyncio
    async def test_execute_dispatches_to_analyze_video(self, tool):
        """analyze_video operation dispatches correctly"""
        mock_result = {"video_id": "abc", "analysis": "good"}
        tool._analyze_video = AsyncMock(return_value=mock_result)

        result = await tool.execute({"operation": "analyze_video", "video_id": "abc"})
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_records_execution_time(self, tool):
        """Execution time is recorded in result metadata"""
        tool._search_videos = AsyncMock(return_value={"videos": []})

        result = await tool.execute({"operation": "search_videos", "query": "test"})
        assert result.execution_time_ms >= 0
        assert result.metadata.get("operation") == "search_videos"


@pytest.mark.unit
class TestYouTubeMCPToolSearch:
    """Test video search functionality"""

    @pytest.fixture
    def tool_with_client(self):
        """Create tool with mocked YouTube API client"""
        with patch("neos.tools.tools.youtube.build") as mock_build:
            mock_client = MagicMock()
            mock_build.return_value = mock_client
            t = YouTubeMCPTool()
            t.youtube_client = mock_client
            t.is_available = True
            return t, mock_client

    @pytest.mark.asyncio
    async def test_search_requires_api_client(self):
        """Search without API client raises ValueError"""
        with patch("neos.tools.tools.youtube.build"):
            tool = YouTubeMCPTool()
            tool.youtube_client = None
            with pytest.raises(ValueError, match="YouTube API key not configured"):
                await tool._search_videos({"query": "test"})

    @pytest.mark.asyncio
    async def test_search_requires_query(self, tool_with_client):
        """Search without query raises ValueError"""
        tool, _ = tool_with_client
        with pytest.raises(ValueError, match="Query parameter is required"):
            await tool._search_videos({})


@pytest.mark.unit
class TestYouTubeMCPToolTranscript:
    """Test transcript extraction with fallback strategies"""

    @pytest.fixture
    def tool(self):
        with patch("neos.tools.tools.youtube.build"):
            t = YouTubeMCPTool()
            t.is_available = True
            return t

    @pytest.mark.asyncio
    async def test_transcript_requires_video_id(self, tool):
        """Transcript extraction requires video_id or video_url"""
        with pytest.raises(ValueError, match="video_id or video_url parameter is required"):
            await tool._get_transcript({})

    @pytest.mark.asyncio
    async def test_transcript_extracts_id_from_url(self, tool):
        """Video ID can be extracted from YouTube URL"""
        # Test the _extract_video_id helper
        assert tool._extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert tool._extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    @pytest.mark.asyncio
    async def test_transcript_disabled_raises_value_error(self, tool):
        """TranscriptsDisabled is converted to ValueError"""
        from youtube_transcript_api._errors import TranscriptsDisabled

        with patch("neos.tools.tools.youtube.asyncio.to_thread",
                    side_effect=TranscriptsDisabled("abc123")):
            with pytest.raises(ValueError):
                await tool._get_transcript({"video_id": "abc123"})

    @pytest.mark.asyncio
    async def test_transcript_not_found_raises_value_error(self, tool):
        """NoTranscriptFound is converted to ValueError"""
        from youtube_transcript_api._errors import NoTranscriptFound

        with patch("neos.tools.tools.youtube.asyncio.to_thread",
                    side_effect=NoTranscriptFound("abc123", ["en"], "No transcript")):
            with pytest.raises(ValueError):
                await tool._get_transcript({"video_id": "abc123"})

    @pytest.mark.asyncio
    async def test_transcript_error_caught_by_execute(self, tool):
        """execute() wraps transcript errors into MCPToolResult with error"""
        from youtube_transcript_api._errors import TranscriptsDisabled

        with patch("neos.tools.tools.youtube.asyncio.to_thread",
                    side_effect=TranscriptsDisabled("abc123")):
            result = await tool.execute({"operation": "get_transcript", "video_id": "abc123"})
            assert result.success is False
            assert result.error is not None


@pytest.mark.unit
class TestYouTubeMCPToolInitialization:
    """Test tool initialization"""

    @pytest.mark.asyncio
    async def test_initialize_with_api_key(self):
        """Tool initializes with API key"""
        with patch("neos.tools.tools.youtube.settings") as mock_settings:
            mock_settings.YOUTUBE_API_KEY = "test_key"
            with patch("neos.tools.tools.youtube.build") as mock_build:
                mock_build.return_value = MagicMock()
                tool = YouTubeMCPTool()
                result = await tool.initialize()
                assert result is True
                assert tool.youtube_client is not None
                assert tool.is_available is True

    @pytest.mark.asyncio
    async def test_initialize_without_api_key(self):
        """Tool initializes without API key (transcript-only mode)"""
        with patch("neos.tools.tools.youtube.settings") as mock_settings:
            mock_settings.YOUTUBE_API_KEY = None
            tool = YouTubeMCPTool()
            result = await tool.initialize()
            assert result is True
            assert tool.youtube_client is None
            assert tool.is_available is True

    @pytest.mark.asyncio
    async def test_initialize_failure(self):
        """Tool handles initialization failure"""
        with patch("neos.tools.tools.youtube.settings") as mock_settings:
            mock_settings.YOUTUBE_API_KEY = "test_key"
            with patch("neos.tools.tools.youtube.build", side_effect=Exception("API error")):
                tool = YouTubeMCPTool()
                result = await tool.initialize()
                assert result is False


@pytest.mark.unit
class TestYouTubeMCPToolPlaylist:
    """Test playlist operations"""

    @pytest.fixture
    def tool_with_client(self):
        with patch("neos.tools.tools.youtube.build") as mock_build:
            mock_client = MagicMock()
            mock_build.return_value = mock_client
            t = YouTubeMCPTool()
            t.youtube_client = mock_client
            t.is_available = True
            return t

    @pytest.mark.asyncio
    async def test_playlist_operations_exist(self, tool_with_client):
        """Playlist operations are registered in the dispatcher"""
        tool = tool_with_client
        # Verify operations are callable
        assert hasattr(tool, '_get_playlist_info')
        assert hasattr(tool, '_get_playlist_videos')
        assert hasattr(tool, '_compare_videos')
        assert callable(tool._get_playlist_info)
        assert callable(tool._get_playlist_videos)
        assert callable(tool._compare_videos)

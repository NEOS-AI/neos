from langchain_community.tools import YouTubeSearchTool

from neos.tools.decorators import create_logged_tool
from neos.tools.youtube import YoutubeTranscriptTool, GoogleYoutubeTranscriptTool


LoggedYoutubeSearchTool = create_logged_tool(YouTubeSearchTool)
LoggedYoutubeTranscriptTool = create_logged_tool(YoutubeTranscriptTool)
LoggedGoogleYoutubeTranscriptTool = create_logged_tool(GoogleYoutubeTranscriptTool)


def get_youtube_search_tool():
    """
    Get the YouTube search tool with the specified maximum number of results.
    <https://python.langchain.com/docs/integrations/tools/youtube/>

    Returns:
        LoggedYoutubeSearchTool: An instance of the YouTube search tool with logging.
    """
    return LoggedYoutubeSearchTool()


def get_youtube_transcript_tool():
    """
    Get the YouTube transcript tool.
    <https://python.langchain.com/docs/integrations/document_loaders/youtube_transcript/>

    Returns:
        LoggedYoutubeTranscriptTool: An instance of the YouTube transcript tool with logging.
    """
    return LoggedYoutubeTranscriptTool()


def get_google_youtube_transcript_tool():
    """
    Get the Google YouTube transcript tool.
    <https://python.langchain.com/docs/integrations/document_loaders/youtube_transcript/>

    Returns:
        LoggedGoogleYoutubeTranscriptTool: An instance of the Google YouTube transcript tool with logging.
    """
    return LoggedGoogleYoutubeTranscriptTool()

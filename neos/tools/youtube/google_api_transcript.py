from pathlib import Path
import os
from langchain_community.document_loaders import GoogleApiClient, GoogleApiYoutubeLoader
from langchain_core.tools import BaseTool


class GoogleYoutubeTranscriptTool(BaseTool):
    """Tool that retrieves YouTube video transcripts."""

    name: str = "youtube_transcript"
    description: str = (
        "Retrieve the transcript of a YouTube video. "
        "Input should be the list of YouTube video_ids."
        "Example video_ids: ['TrdevFK_am4']"
    )

    def _run(self, video_ids: list) -> str:
        """Use the tool."""
        # Initialize the Google API client
        credential_path = os.getenv("GOOGLE_API_CREDENTIAL_PATH")
        if not credential_path or not Path(credential_path).exists():
            raise ValueError("GOOGLE_API_CREDENTIAL_PATH environment variable is not set or the file does not exist.")

        google_api_client = GoogleApiClient(credentials_path=Path(credential_path))
        youtube_loader = GoogleApiYoutubeLoader(
            google_api_client=google_api_client, video_ids=["TrdevFK_am4"], add_video_info=True
        )

        transcript = youtube_loader.load()
        return "\n\n".join(map(repr, transcript))


    async def _arun(self, video_ids: list) -> str:
        """Use the tool asynchronously."""
        # Initialize the Google API client
        credential_path = os.getenv("GOOGLE_API_CREDENTIAL_PATH")
        if not credential_path or not Path(credential_path).exists():
            raise ValueError("GOOGLE_API_CREDENTIAL_PATH environment variable is not set or the file does not exist.")

        google_api_client = GoogleApiClient(credentials_path=Path(credential_path))
        youtube_loader = GoogleApiYoutubeLoader(
            google_api_client=google_api_client, video_ids=["TrdevFK_am4"], add_video_info=True
        )

        transcript = await youtube_loader.aload()
        return "\n\n".join(map(repr, transcript))

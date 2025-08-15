from langchain_community.document_loaders import YoutubeLoader
from langchain_core.tools import BaseTool


class YoutubeTranscriptTool(BaseTool):
    """Tool that retrieves YouTube video transcripts."""

    name: str = "youtube_transcript"
    description: str = (
        "Retrieve the transcript of a YouTube video. "
        "Input should be the YouTube video URL and the language code (i.e. en)."
        "Example URL: https://www.youtube.com/watch?v=QsYGlZkevEg, "
        "Example language code: en"
    )

    def _run(self, url: str, language: str) -> str:
        """Use the tool."""
        loader = YoutubeLoader.from_youtube_url(url)
        transcript = loader.load()
        return "\n\n".join(map(repr, transcript))

    async def _arun(self, url: str, language: str) -> str:
        """Use the tool asynchronously."""
        # return self._run(url, language)
        loader = YoutubeLoader.from_youtube_url(url)
        transcript = await loader.aload()
        return "\n\n".join(map(repr, transcript))

import unicodedata

import pytest

from neos.workflow.deep_analysis.cassette import Cassette
from neos.workflow.deep_analysis.fetch import fetch_url, html_to_text


pytestmark = pytest.mark.no_db


def test_html_to_text_removes_script_style_and_decodes_entities():
    html = """
    <html>
      <style>.hidden { display: none }</style>
      <script>ignoreInstruction()</script>
      <p>Hello&nbsp;<b>world</b> &amp; café</p>
    </html>
    """

    text = html_to_text(html)

    assert text == "Hello world & café"
    assert unicodedata.is_normalized("NFC", text)


class FakeHttpClient:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body
        self.calls = 0

    async def get(self, url):
        self.calls += 1

        class Response:
            status_code = self.status_code
            text = self.body

        return Response()


@pytest.mark.asyncio
async def test_fetch_returns_content_addressed_blob_proposal():
    client = FakeHttpClient(200, "<p>quick brown fox</p>")

    blob = await fetch_url("https://example.com", client=client)

    assert blob.source_url == "https://example.com"
    assert blob.http_status == 200
    assert blob.raw_text == "quick brown fox"
    assert len(blob.content_hash) == 16


@pytest.mark.asyncio
async def test_fetch_replay_avoids_http_client(tmp_path):
    path = tmp_path / "fetch.json"
    record_client = FakeHttpClient(200, "<p>cached body</p>")
    record = Cassette(path, "record")
    expected = await fetch_url(
        "https://example.com",
        client=record_client,
        cassette=record,
    )
    record.save()

    replay_client = FakeHttpClient(500, "must not be used")
    replay = Cassette(path, "replay")
    actual = await fetch_url(
        "https://example.com",
        client=replay_client,
        cassette=replay,
    )

    assert actual == expected
    assert replay_client.calls == 0

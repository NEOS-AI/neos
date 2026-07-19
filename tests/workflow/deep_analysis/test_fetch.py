import unicodedata
from unittest.mock import Mock

import pytest

from neos.workflow.deep_analysis.cassette import Cassette
from neos.workflow.deep_analysis import fetch as fetch_module
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
    def __init__(self, status_code, body, headers=None):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
        self.calls = 0

    async def get(self, url):
        self.calls += 1

        class Response:
            status_code = self.status_code
            headers = self.headers
            content = (
                self.body
                if isinstance(self.body, bytes)
                else self.body.encode("utf-8")
            )
            text = (
                self.body.decode("utf-8", errors="replace")
                if isinstance(self.body, bytes)
                else self.body
            )

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


@pytest.mark.asyncio
async def test_empty_body_blobs_do_not_collide_across_sources():
    # 본문 추출이 빈 서로 다른 소스(죽은 404, 200-빈 페이지 등)는
    # 서로 다른 content_hash를 가져야 한다. 예전엔 모두 sha256("")로
    # 뭉개져 Ledger._store_blob이 첫 blob만 남기고 status를 오염시켰다.
    dead = await fetch_url("https://dead.example", client=FakeHttpClient(404, "x"))
    empty_ok = await fetch_url(
        "https://live.example", client=FakeHttpClient(200, "<script>x()</script>")
    )

    assert dead.raw_text == ""
    assert empty_ok.raw_text == ""
    # 죽은 소스와 유효-빈 소스가 다른 blob으로 유지되어야 한다.
    assert dead.content_hash != empty_ok.content_hash
    # 서로 다른 URL의 두 죽은 소스도 구분된다.
    dead2 = await fetch_url("https://dead2.example", client=FakeHttpClient(404, "y"))
    assert dead.content_hash != dead2.content_hash


@pytest.mark.asyncio
async def test_identical_body_still_dedups_by_content():
    # 동일 본문은 여전히 같은 content_hash로 병합되어야 한다(교차 검증).
    a = await fetch_url("https://a.example", client=FakeHttpClient(200, "<p>same text</p>"))
    b = await fetch_url("https://b.example", client=FakeHttpClient(200, "<p>same text</p>"))
    assert a.content_hash == b.content_hash


@pytest.mark.asyncio
async def test_fetch_uses_pdf_parser_for_pdf_content_type(monkeypatch):
    parse = Mock(return_value="PDF evidence text")
    monkeypatch.setattr(fetch_module, "pdf_bytes_to_text", parse)
    client = FakeHttpClient(
        200,
        b"%PDF-body",
        {"content-type": "application/pdf; charset=binary"},
    )

    blob = await fetch_url("https://example.com/paper", client=client)

    assert blob.raw_text == "PDF evidence text"
    parse.assert_called_once_with(b"%PDF-body")


@pytest.mark.asyncio
async def test_fetch_detects_pdf_magic_when_header_is_wrong(monkeypatch):
    parse = Mock(return_value="Magic PDF")
    monkeypatch.setattr(fetch_module, "pdf_bytes_to_text", parse)
    client = FakeHttpClient(
        200,
        b"  \n%PDF-body",
        {"content-type": "application/octet-stream"},
    )

    blob = await fetch_url("https://example.com/paper", client=client)

    assert blob.raw_text == "Magic PDF"
    parse.assert_called_once_with(b"  \n%PDF-body")


@pytest.mark.asyncio
async def test_fetch_does_not_parse_non_success_pdf(monkeypatch):
    parse = Mock(return_value="must not be used")
    monkeypatch.setattr(fetch_module, "pdf_bytes_to_text", parse)

    blob = await fetch_url(
        "https://example.com/missing.pdf",
        client=FakeHttpClient(
            404,
            b"%PDF-body",
            {"content-type": "application/pdf"},
        ),
    )

    assert blob.raw_text == ""
    parse.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_keeps_legacy_text_only_response_compatible():
    class LegacyClient:
        async def get(self, url):
            return type(
                "LegacyResponse",
                (),
                {"status_code": 200, "text": "<p>legacy html</p>"},
            )()

    blob = await fetch_url("https://example.com/legacy", client=LegacyClient())

    assert blob.raw_text == "legacy html"

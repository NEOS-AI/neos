import unicodedata
from unittest.mock import Mock

import pytest

from neos.workflow.deep_analysis.cassette import Cassette
from neos.workflow.deep_analysis import fetch as fetch_module
from neos.workflow.deep_analysis.fetch import (
    extract_article_text,
    fetch_url,
    html_to_text,
)


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


def test_html_to_text_removes_nul_before_normalizing():
    text = html_to_text("<p>A\x00B cafe\u0301</p>")

    assert text == "AB café"
    assert "\x00" not in text


_NAV_PAGE = """
<html><body>
  <nav><ul><li>Home</li><li>About</li><li>Contact</li><li>Privacy Policy</li></ul></nav>
  <header>Cookie banner: we value your privacy</header>
  <article>
    <h1>Article 55: Obligations of providers</h1>
    <p>Providers of general-purpose AI models with systemic risk shall perform
    model evaluation in accordance with standardised protocols and document the
    results, and shall assess and mitigate possible systemic risks at Union level.</p>
  </article>
  <footer>Copyright 2026. All rights reserved. Terms of service.</footer>
</body></html>
"""


def test_extract_article_text_drops_navigation_and_keeps_body():
    text = extract_article_text(_NAV_PAGE)

    assert "systemic risk" in text
    assert "Obligations of providers" in text
    # boilerplate must not survive into evidence
    assert "Privacy Policy" not in text
    assert "Terms of service" not in text
    assert "Cookie banner" not in text


def test_extract_article_text_falls_back_when_trafilatura_finds_nothing():
    # trafilatura returns None for this (no article content in <body>), but
    # html_to_text still picks up the <title> text node, so this fixture
    # actually distinguishes the fallback from an empty result rather than
    # passing by coincidence.
    html = "<html><head><title>Untitled placeholder page</title></head><body></body></html>"

    text = extract_article_text(html)

    assert text == html_to_text(html)
    assert text == "Untitled placeholder page"


def test_extract_article_text_normalizes_the_trafilatura_path():
    # trafilatura joins paragraphs with newlines; normalize_evidence_text is
    # what collapses them. Without that call this assertion fails.
    html = (
        "<html><body><article>"
        "<p>First paragraph about systemic risk obligations for providers.</p>"
        "<p>Second paragraph covering model evaluation and documentation duties.</p>"
        "</article></body></html>"
    )

    text = extract_article_text(html)

    assert "systemic risk" in text
    assert "\n" not in text
    assert "  " not in text


_COMMENTED_PAGE = """
<html><body>
  <article>
    <h1>Study Finds Treatment Reduces Incidence</h1>
    <p>Researchers published new findings this week describing a large randomized
    controlled trial conducted across twelve clinical sites over a period of eighteen
    months, enrolling more than four thousand participants who met strict eligibility
    criteria for chronic condition management.</p>
    <p>The treatment reduced measured incidence by thirty-one percent compared to the
    placebo control group, according to the peer reviewed study published in a leading
    medical journal this month, drawing attention from clinicians and public health
    officials alike.</p>
  </article>
  <div id="comments" class="comments-section">
    <h3>42 Comments</h3>
    <div class="comment"><p>Total nonsense. It actually increases incidence by fifty
    percent and the authors are lying about their methodology here.</p></div>
  </div>
</body></html>
"""


def test_extract_article_text_drops_reader_comments():
    # include_comments defaults to True in trafilatura, so a bare
    # trafilatura.extract(html) call lets a commenter's counter-claim ride
    # along as if it were article prose. Once normalize_evidence_text
    # collapses newlines, "the authors are lying" is indistinguishable from
    # body text in raw_text, and DeterministicGrader would score a worker's
    # quote of it 1.0. Prove the comment does not survive extraction.
    text = extract_article_text(_COMMENTED_PAGE)

    assert "thirty-one percent" in text
    assert "Total nonsense" not in text
    assert "authors are lying" not in text


def test_extract_article_text_drops_comments_break_check():
    # Break-check: with the bare (include_comments defaults to True) call,
    # this must fail. This proves the assertions above are only true because
    # of the explicit include_comments=False, not by fixture coincidence.
    import trafilatura

    bare = trafilatura.extract(_COMMENTED_PAGE)
    assert bare is not None
    assert "authors are lying" in bare  # documents the pre-fix behavior


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
async def test_fetch_url_stores_article_text_not_navigation():
    client = FakeHttpClient(200, _NAV_PAGE)

    blob = await fetch_url("https://example.com/article-55", client=client)

    assert "systemic risk" in blob.raw_text
    assert "Privacy Policy" not in blob.raw_text
    assert "Terms of service" not in blob.raw_text
    assert blob.http_status == 200


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
async def test_nul_and_sanitized_html_share_canonical_hash():
    nul = await fetch_url(
        "https://nul.example",
        client=FakeHttpClient(200, "<p>A\x00B</p>"),
    )
    clean = await fetch_url(
        "https://clean.example",
        client=FakeHttpClient(200, "<p>AB</p>"),
    )

    assert nul.raw_text == clean.raw_text == "AB"
    assert nul.content_hash == clean.content_hash


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

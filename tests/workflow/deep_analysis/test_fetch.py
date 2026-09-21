import unicodedata
from unittest.mock import Mock

import pytest

from neos.config.settings import settings
from neos.workflow.deep_analysis.cassette import Cassette
from neos.workflow.deep_analysis import fetch as fetch_module
from neos.workflow.deep_analysis.fetch import (
    _build_fetch_client,
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


def test_build_fetch_client_sends_a_descriptive_user_agent():
    client = _build_fetch_client()
    ua = client.headers.get("user-agent", "")

    assert ua == settings.config.deep_analysis.fetch_user_agent
    assert ua  # must not be empty
    # A descriptive bot string, not a browser impersonation.
    assert "Mozilla" not in ua
    assert "Chrome" not in ua
    assert "Safari" not in ua
    # Identifiable, with a contact URL.
    assert "NEOS" in ua
    assert "http" in ua


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
async def test_fetch_url_does_not_override_an_injected_client():
    # An injected client owns its own configuration; fetch_url must not
    # rewrite its headers.
    client = FakeHttpClient(200, "<html><body><article><p>Body text here that "
                                 "is long enough to extract.</p></article></body></html>")

    blob = await fetch_url("https://example.com/a", client=client)

    assert blob.http_status == 200
    assert client.calls == 1
    assert client.headers == {}  # fetch_url must not stamp its UA on a caller's client


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


# --- 트랙 A D2: retrieval 회복과 그 회계 -------------------------------------
#
# 이 기능 이전에는 재시도가 한 줄도 없었다. 429 한 번이면 그 출처를 **영구히**
# 잃고, 잃었다는 사실조차 남지 않았다 -- 실패한 fetch 는 `raw_text=""` 인
# blob 이 되고 그것은 정말로 빈 페이지와 구별되지 않는다.


class ScriptedHttpClient:
    """호출 순서대로 다른 응답을 낸다. 재시도를 관찰하려면 필요하다."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def get(self, url):
        self.calls += 1
        status, body, hdrs = self._responses[
            min(self.calls - 1, len(self._responses) - 1)
        ]

        class Response:
            # `hdrs` 로 받는 이유: 클래스 본문에서 같은 이름에 대입하면
            # 그 이름은 바깥 함수 스코프를 닫지 않아 NameError 가 난다.
            status_code = status
            headers = hdrs or {}
            content = body.encode("utf-8")
            text = body

        return Response()


def _recorder():
    seen = []

    def on_attempt(status, outcome):
        seen.append((status, outcome))

    return seen, on_attempt


@pytest.mark.asyncio
async def test_a_429_is_retried_and_the_second_attempt_is_kept():
    client = ScriptedHttpClient(
        [(429, "", None), (200, "<p>rate limit lifted</p>", None)]
    )
    seen, on_attempt = _recorder()
    slept = []

    blob = await fetch_url(
        "https://example.com",
        client=client,
        on_attempt=on_attempt,
        sleep=lambda d: slept.append(d) or _noop(),
    )

    assert client.calls == 2
    assert blob.http_status == 200
    assert blob.raw_text == "rate limit lifted"
    assert seen == [(429, "retrying"), (200, "ok")]
    assert slept and slept[0] > 0


async def _noop():
    return None


@pytest.mark.asyncio
async def test_a_403_is_counted_but_never_retried():
    """403 은 "이 클라이언트에게는 안 준다" 이므로 다시 물어도 같은 답이다.

    재시도는 답을 바꾸지 못하면서 상대에게는 봇이 우기는 것으로 보인다 --
    `fetch_user_agent` 가 브라우저를 흉내내지 않기로 한 것과 같은 판단이다.
    세는 것은 별개다: D2 가 묻는 것이 "403 이 얼마나 남았나" 이고, 세지
    않으면 답할 수 없다.
    """
    client = ScriptedHttpClient([(403, "", None)])
    seen, on_attempt = _recorder()

    blob = await fetch_url(
        "https://example.com", client=client, on_attempt=on_attempt
    )

    assert client.calls == 1
    assert blob.http_status == 403
    assert seen == [(403, "refused")]


@pytest.mark.asyncio
async def test_a_retry_after_header_beats_the_exponential_guess():
    """서버가 말했으면 추측보다 낫다."""
    client = ScriptedHttpClient(
        [(429, "", {"Retry-After": "2.5"}), (200, "<p>ok</p>", None)]
    )
    slept = []

    await fetch_url(
        "https://example.com",
        client=client,
        sleep=lambda d: slept.append(d) or _noop(),
    )

    assert slept == [2.5]


@pytest.mark.asyncio
async def test_a_huge_retry_after_is_capped_so_one_url_cannot_own_the_worker():
    client = ScriptedHttpClient(
        [(429, "", {"Retry-After": "600"}), (200, "<p>ok</p>", None)]
    )
    slept = []

    await fetch_url(
        "https://example.com",
        client=client,
        sleep=lambda d: slept.append(d) or _noop(),
    )

    cap = settings.config.deep_analysis.fetch_retry_max_sleep_seconds
    assert slept == [cap]


@pytest.mark.asyncio
async def test_an_unparseable_retry_after_falls_back_rather_than_crashing():
    """RFC 7231 은 날짜 형식도 허용한다. 파싱하지 않고 지수 백오프로 떨어진다."""
    client = ScriptedHttpClient(
        [
            (429, "", {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
            (200, "<p>ok</p>", None),
        ]
    )
    slept = []

    blob = await fetch_url(
        "https://example.com",
        client=client,
        sleep=lambda d: slept.append(d) or _noop(),
    )

    assert blob.http_status == 200
    assert slept == [settings.config.deep_analysis.fetch_retry_base_seconds]


@pytest.mark.asyncio
async def test_exhausting_the_retries_reports_exhausted_not_ok():
    """마지막 시도까지 429 면 그렇게 말해야 한다.

    `retrying` 으로 끝나면 원장은 "재시도했다" 만 알고 "그래서 실패했다" 를
    모른다 -- 그 둘의 차이가 D2 가 재려는 것 전부다.
    """
    client = ScriptedHttpClient([(429, "", None)])
    seen, on_attempt = _recorder()

    blob = await fetch_url(
        "https://example.com",
        client=client,
        on_attempt=on_attempt,
        sleep=lambda d: _noop(),
    )

    attempts = settings.config.deep_analysis.fetch_max_attempts
    assert client.calls == attempts
    assert blob.http_status == 429
    assert seen[-1] == (429, "exhausted")
    assert sum(1 for _s, o in seen if o == "retrying") == attempts - 1


@pytest.mark.asyncio
async def test_a_transport_error_is_retried_and_then_raised_not_swallowed():
    """마지막까지 실패하면 던진다.

    삼켜서 빈 blob 을 만들면 "가져왔는데 비었다" 와 "못 가져왔다" 가 원장에서
    같은 모양이 되고, 그것이 §3.2 가 이 저장소의 관통 주제로 적은 실패다.
    호출자(`Worker`)는 이 예외를 이미 다룬다.
    """
    import httpx

    class FailingClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url):
            self.calls += 1
            raise httpx.ConnectError("connection reset")

    client = FailingClient()
    seen, on_attempt = _recorder()

    with pytest.raises(httpx.HTTPError):
        await fetch_url(
            "https://example.com",
            client=client,
            on_attempt=on_attempt,
            sleep=lambda d: _noop(),
        )

    assert client.calls == settings.config.deep_analysis.fetch_max_attempts
    assert all(outcome == "transport_error" for _s, outcome in seen)


@pytest.mark.asyncio
async def test_a_replayed_fetch_reports_no_attempts(tmp_path):
    """재생된 fetch 는 HTTP 요청을 한 적이 없다.

    거기서 재시도 수를 보고하면 원장이 일어나지 않은 일을 적는다.
    """
    path = tmp_path / "fetch.json"
    record = Cassette(path, "record")
    await fetch_url(
        "https://example.com",
        client=ScriptedHttpClient([(429, "", None), (200, "<p>ok</p>", None)]),
        cassette=record,
        sleep=lambda d: _noop(),
    )
    record.save()

    seen, on_attempt = _recorder()
    blob = await fetch_url(
        "https://example.com",
        client=ScriptedHttpClient([(500, "", None)]),
        cassette=Cassette(path, "replay"),
        on_attempt=on_attempt,
    )

    assert blob.http_status == 200
    assert seen == []


def test_a_blob_ref_fits_the_column_that_stores_it():
    """blob 주소의 폭은 **두 곳에 각각** 적혀 있다.

    `_content_hash` 가 sha256 을 16자로 자르고, `deep_analysis_blobs.
    content_hash` 가 VARCHAR(16) 이며, `deep_analysis_evidence.raw_ref` 가
    거기에 FK 로 걸린다. 한쪽만 바뀌면 조용히 깨지지 않는다 -- 넓히면 INSERT
    가 죽고, 좁히면 **주소가 충돌해 서로 다른 본문이 한 blob 이 된다.**

    트랙 J 가 이것을 밟았다: 계약 §4 가 `script_ref` 를 "sha256" 이라고 적어
    테스트가 64자를 썼는데, 그 폭은 원장이 만들 수 없는 값이라 프로덕션에서는
    `get_blob` 이 영원히 None 을 돌려줬을 것이다. 픽스처가 만들어 낼 수 없는
    값을 쓰면 테스트는 초록인데 코드는 닿지 않는다.
    """
    from neos.database.deep_analysis_models import DABlob
    from neos.workflow.deep_analysis.fetch import _content_hash

    assert len(_content_hash("어떤 본문")) == DABlob.content_hash.type.length

"""오프라인 섀도의 fetch: 네트워크 대신 **저장된 blob** (로드맵 J3).

`open_research_session` 이 `fetch_fn` 을 주입으로 받는 이유가 여기다 --
`research_session.py` 의 주석이 이미 "카세트 재생(J3 오프라인 섀도)이 같은
자리를 갈아끼운다" 고 적어 뒀다.

## 보관소에 없는 URL

조사 워커는 옛 워커와 **다르게** 탐색한다. 그것이 비교의 요점이므로, 기록된
run 이 가져온 적 없는 URL 을 요구하는 것은 드문 일이 아니라 **기대되는**
일이다. 그때 무엇을 할 것인가가 이 모듈의 설계다.

죽은 출처처럼 꾸미지 않는다. `http_status=404` 짜리 blob 을 지어내면 워커도
채점기도 그것을 **진짜 죽은 출처**로 읽고(`E_SOURCE_DEAD`), 섀도의 한계가
그 출처에 대한 사실로 둔갑한다. "우리 보관소에 없다" 와 "그 페이지는
죽었다" 는 다른 말이다.

그래서 `FetchUnavailable` 을 던지고 도구가 그것을 **거절**로 바꾼다 --
한도 초과(`evidence_cap_reached`)와 같은 모양이다. 워커는 다음 수를 두고,
빗나간 횟수는 비교 보고서의 재료가 된다.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_db

URL = "https://example.com/a"
OTHER = "https://example.com/b"


def _archive(**pages):
    """보관소는 **원장이 저장한 blob 그대로**를 담는다.

    본문에서 주소를 다시 계산하지 않는다 -- 비어 있는 본문의 주소는 상태와
    URL 을 섞어 만들어지므로(`fetch._blob_hash`), 본문만으로 되짚으면 404
    blob 들이 전부 한 주소로 뭉친다.
    """
    from neos.workflow.deep_analysis.fetch import _blob_hash
    from neos.workflow.deep_analysis.models import ProposedBlob
    from neos.workflow.deep_analysis.shadow import BlobArchive

    return BlobArchive(
        {
            url: ProposedBlob(
                content_hash=_blob_hash(text, url, 200),
                source_url=url,
                http_status=200,
                raw_text=text,
            )
            for url, text in pages.items()
        }
    )


@pytest.mark.asyncio
async def test_an_archived_url_comes_back_as_a_blob() -> None:
    archive = _archive(**{URL: "본문 42.5"})

    blob = await archive.fetch(URL)

    assert blob.source_url == URL
    assert blob.raw_text == "본문 42.5"
    assert blob.http_status == 200


@pytest.mark.asyncio
async def test_the_replayed_blob_keeps_the_address_the_run_stored() -> None:
    """주소가 달라지면 재생이 아니다.

    `raw_ref` 는 원장의 blob 을 가리키고, 채점기는 그 주소로 원문을 다시
    읽는다. 여기서 새 주소를 만들면 그 클레임은 채점에서
    `E_COMPUTE_INPUT_UNFETCHED` 로 죽는다 -- 증거는 멀쩡한데 가리키는 곳이
    없어서.
    """
    from neos.workflow.deep_analysis.fetch import _content_hash

    archive = _archive(**{URL: "본문 42.5"})

    blob = await archive.fetch(URL)

    assert blob.content_hash == _content_hash("본문 42.5")


@pytest.mark.asyncio
async def test_a_url_the_run_never_fetched_is_refused_not_faked() -> None:
    from neos.workflow.deep_analysis.shadow import FetchUnavailable

    archive = _archive(**{URL: "본문"})

    with pytest.raises(FetchUnavailable, match=OTHER):
        await archive.fetch(OTHER)


@pytest.mark.asyncio
async def test_the_archive_counts_what_it_could_not_serve() -> None:
    """빗나간 횟수가 비교 보고서의 재료다.

    섀도가 프로덕션보다 적은 증거로 돌았다면 제안이 빈약한 것은 워커 탓이
    아니다. 그 사실이 남지 않으면 비교가 워커를 잘못 나무란다.
    """
    from neos.workflow.deep_analysis.shadow import FetchUnavailable

    archive = _archive(**{URL: "본문"})

    await archive.fetch(URL)
    for url in (OTHER, OTHER, "https://example.com/c"):
        with pytest.raises(FetchUnavailable):
            await archive.fetch(url)

    assert archive.served == [URL]
    assert archive.missed == [OTHER, OTHER, "https://example.com/c"]


# ---- 도구가 빗나감을 거절로 바꾼다 -----------------------------------------------


def _port(fetch_fn):
    from neos.workflow.deep_analysis.research_tools import ResearchToolPort

    class _Store:
        async def spent_bytes(self):
            return 0

        async def is_stored(self, content_hash):
            return False

        async def commit(self, blob, *, bytes_charged):
            raise AssertionError("빗나간 fetch 는 커밋에 닿지 않아야 한다")

        async def record_fetched(self, raw_ref, path):
            raise AssertionError("빗나간 fetch 는 샌드박스에 닿지 않아야 한다")

    class _Sandbox:
        async def materialize_evidence(self, raw_ref, text):
            raise AssertionError("빗나간 fetch 는 샌드박스에 닿지 않아야 한다")

    return ResearchToolPort(
        fetch_fn=fetch_fn,
        store=_Store(),
        sandbox=_Sandbox(),
        cap_bytes=1024,
    )


@pytest.mark.asyncio
async def test_a_miss_becomes_a_tool_refusal_not_an_exception() -> None:
    """한도 초과와 같은 모양이다 -- 턴을 죽이지 않고 워커에게 알린다."""
    archive = _archive(**{URL: "본문"})

    result = await _port(archive.fetch).execute("fetch.v1", {"url": OTHER})

    assert result["error"]
    assert "unavailable" in result["error"]


@pytest.mark.asyncio
async def test_a_live_fetch_error_is_still_not_swallowed() -> None:
    """빗나감만 거절로 바꾼다.

    아무 예외나 삼키면 진짜 장애가 "그 URL 은 없었다" 로 보고되고, 섀도가
    아닌 라이브 경로에서도 같은 일이 일어난다.
    """

    async def boom(url):
        raise RuntimeError("소켓이 터졌다")

    with pytest.raises(RuntimeError, match="소켓"):
        await _port(boom).execute("fetch.v1", {"url": URL})

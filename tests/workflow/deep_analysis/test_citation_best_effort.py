"""조립 재시도 캡이 소진됐을 때 무엇을 배달하는가 (ORPHAN1).

표본 #17 의 run `9d9daa8b` 가 **각주 0개·원본 마커 32개**로 배달됐다. 경로는
`E_ORPHAN_CITE`(`orphan_claim_id=66cd381e`)로 시도 0·1 이 모두 반려 → 캡 소진 →
`_finalize` 가 **렌더 전 draft** 를 반환. 그 id 는 DB 어디에도 없었다 -- 조립기가
지어냈다.

`render()` 는 첫 orphan 에서 전체를 포기한다. 마커 32개 중 31개가 유효했더라도
하나 때문에 전부 렌더되지 않는다. 이 파일은 **최후 배달 전용** 경로를 고정한다:
유효한 것은 각주로 살리고, orphan 은 남긴다.

⚠️ **D10 이 한 길을 막아 놨다.** `[미검증]` 치환은 "원시 마커만 제거해 AC 를
겉보기로 통과시키면서 실제 인용 무결성 실패를 보고서 안에 숨긴다" 는 이유로
기각됐다. 그래서 orphan 마커는 **지우지 않는다** -- 남기고, 호출자가 사유를
적는다.
"""

import pytest

from neos.workflow.deep_analysis.citation import (
    CitationRenderer,
    OrphanCitationError,
)


class _FakeClaim:
    def __init__(self, claim_id: str, status: str = "verified") -> None:
        self.id = claim_id
        self.status = status
        self.question_id = "q1"


class _FakeEvidence:
    def __init__(self, url: str) -> None:
        self.source_url = url


class _FakeLedger:
    """claim id 로 조회되는 최소 원장. 없는 id 는 `None` 을 돌려준다."""

    def __init__(self, known: dict[str, str]) -> None:
        self._known = known

    async def get_claim(self, claim_id: str):
        if claim_id not in self._known:
            return None
        return _FakeClaim(claim_id)

    async def verified_claims(self, question_id: str):
        return [
            (_FakeClaim(cid), [_FakeEvidence(url)])
            for cid, url in self._known.items()
        ]


_KNOWN = {"aaaaaaaa": "https://example.org/a", "bbbbbbbb": "https://example.org/b"}


@pytest.mark.asyncio
async def test_the_normal_renderer_still_refuses_an_orphan():
    """🔴 이 테스트가 D10 의 회귀 가드다.

    최후 배달용 부분 렌더를 **평상 경로에 잘못 배선하면** orphan 이 조용히
    통과하고, 그 순간 재시도가 사라지며 인용 무결성 실패가 리포트 안에
    숨는다. 평상시 `render()` 는 여전히 던져야 한다.
    """
    renderer = CitationRenderer(_FakeLedger(_KNOWN))

    with pytest.raises(OrphanCitationError):
        await renderer.render("본문 [C:aaaaaaaa] 그리고 [C:66cd381e] 끝.")


@pytest.mark.asyncio
async def test_best_effort_keeps_the_valid_citations():
    """유효한 마커는 각주가 된다 -- 지금은 orphan 하나 때문에 전부 잃는다.

    표본 #17 은 마커 32개를 들고 각주 0개로 배달됐다. 그중 몇 개가
    유효했는지는 그 표본으로 알 수 없지만, **하나의 orphan 이 나머지를
    버리게 만드는 구조**는 그 자체로 결함이다.
    """
    renderer = CitationRenderer(_FakeLedger(_KNOWN))

    rendered, orphans = await renderer.render_best_effort(
        "본문 [C:aaaaaaaa] 그리고 [C:66cd381e] 끝."
    )

    assert "[1]" in rendered
    assert "## 출처" in rendered
    assert "https://example.org/a" in rendered
    assert orphans == ["66cd381e"]


@pytest.mark.asyncio
async def test_best_effort_leaves_the_orphan_marker_visible():
    """orphan 마커는 **지우지 않는다** (D10).

    지우면 "인용이 없는 문장" 과 "인용이 깨진 문장" 이 구별되지 않는다.
    D10 이 `[미검증]` 치환을 기각한 이유가 그것이다 -- 원시 마커 제거는
    실패를 숨기면서 겉보기로 통과시킨다.
    """
    renderer = CitationRenderer(_FakeLedger(_KNOWN))

    rendered, orphans = await renderer.render_best_effort(
        "본문 [C:66cd381e] 끝."
    )

    assert "[C:66cd381e]" in rendered
    assert orphans == ["66cd381e"]


@pytest.mark.asyncio
async def test_best_effort_reports_each_orphan_once():
    """같은 orphan 이 여러 번 나와도 사유 문구가 그만큼 길어지지 않는다."""
    renderer = CitationRenderer(_FakeLedger(_KNOWN))

    _, orphans = await renderer.render_best_effort(
        "[C:66cd381e] 그리고 다시 [C:66cd381e] 또 [C:99999999]."
    )

    assert orphans == ["66cd381e", "99999999"]


@pytest.mark.asyncio
async def test_best_effort_matches_render_when_nothing_is_orphaned():
    """orphan 이 없으면 두 경로의 산출물이 같아야 한다.

    갈라지면 최후 배달이 평상 배달과 다른 서식을 내고, 원장의
    `uncited_ratio` 가 서술하는 대상이 둘로 갈린다(W3-a 가 고친 문제).
    """
    renderer = CitationRenderer(_FakeLedger(_KNOWN))
    draft = "본문 [C:aaaaaaaa] 그리고 [C:bbbbbbbb] 끝."

    expected = await renderer.render(draft)
    rendered, orphans = await renderer.render_best_effort(draft)

    assert rendered == expected
    assert orphans == []


@pytest.mark.asyncio
async def test_an_unverified_claim_counts_as_an_orphan():
    """`render()` 는 verified 가 아닌 클레임도 orphan 으로 친다.
    최후 배달 경로가 그 판정을 느슨하게 하면 미검증 클레임이 각주를 얻는다."""

    class _UnverifiedLedger(_FakeLedger):
        async def get_claim(self, claim_id: str):
            return _FakeClaim(claim_id, status="rejected")

    renderer = CitationRenderer(_UnverifiedLedger(_KNOWN))

    rendered, orphans = await renderer.render_best_effort("본문 [C:aaaaaaaa] 끝.")

    assert orphans == ["aaaaaaaa"]
    assert "[C:aaaaaaaa]" in rendered

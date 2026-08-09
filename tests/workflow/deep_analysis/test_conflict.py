import pytest
from types import SimpleNamespace

from neos.workflow.deep_analysis.conflict import source_tier, resolve_conflicts
from neos.workflow.deep_analysis.models import NodeSummary, ConflictNote

pytestmark = pytest.mark.no_db

TIERS = {"tier1": ["arxiv.org", ".gov", ".edu", "github.com"], "tier2": ["*"]}


def test_source_tier_suffix_match():
    assert source_tier("https://arxiv.org/abs/1", TIERS) == 1
    assert source_tier("https://x.edu/p", TIERS) == 1
    assert source_tier("https://blog.example.com/p", TIERS) == 2


def test_source_tier_bare_domain_no_prefix_false_positive():
    # "notarxiv.org" must not match the "arxiv.org" tier1 entry via naive
    # string-suffix matching -- suffix match must be domain-label anchored.
    assert source_tier("https://notarxiv.org/x", TIERS) == 2


def test_source_tier_raw_url_fallback_not_spoofed_by_query_param():
    # "https://evil.com/redirect?to=fake.arxiv.org" must not match tier1 via
    # a naive raw-URL endswith check -- the raw-URL fallback should only
    # apply when host extraction genuinely fails, not when the host (evil.com)
    # is untrusted but the full URL string happens to end in a tier1 domain.
    assert source_tier("https://evil.com/redirect?to=fake.arxiv.org", TIERS) == 2


def test_source_tier_subdomain_matches_dotted_suffix():
    assert source_tier("https://sub.example.gov/p", TIERS) == 1
    assert source_tier("https://raw.githubusercontent.com", TIERS) == 2
    assert source_tier("https://github.com/org/repo", TIERS) == 1


def test_source_tier_accepts_design_glob_form():
    # 설계 §8 config는 tier1을 glob 형식("*.gov", "*.edu")으로 명시한다.
    # 파서는 그 문서 형식과 dotted-suffix 형식(".gov") 양쪽을 지원해야 한다.
    glob_tiers = {
        "tier1": ["arxiv.org", "*.gov", "*.edu", "github.com"],
        "tier2": ["*"],
    }
    assert source_tier("https://nasa.gov/mission", glob_tiers) == 1
    assert source_tier("https://sub.example.edu/p", glob_tiers) == 1
    assert source_tier("https://arxiv.org/abs/1", glob_tiers) == 1
    assert source_tier("https://blog.example.com/p", glob_tiers) == 2


class FakeLedger:
    def __init__(self, urls):
        self._urls = urls  # {claim_id: [url]}

    async def claim_source_urls(self, claim_id):
        return self._urls.get(claim_id, [])

    async def get_claim(self, cid):
        return SimpleNamespace(id=cid, value_est=0.5)


async def test_equal_tier_conflict_produces_both_sides():
    s = NodeSummary(
        question_id="n1",
        answer="주장 [C:aaaaaaaa]",
        key_claim_ids=["aaaaaaaa"],
        confidence=0.7,
        caveats=[],
        conflicts=[ConflictNote("aaaaaaaa", "bbbbbbbb", "상반")],
    )
    led = FakeLedger(
        {"aaaaaaaa": ["http://blog1.com"], "bbbbbbbb": ["http://blog2.com"]}
    )  # 둘 다 tier2
    out, reinv = await resolve_conflicts(led, s, TIERS)
    assert "양론" in out.answer
    assert "[C:aaaaaaaa]" in out.answer
    assert "[C:bbbbbbbb]" in out.answer
    assert "상반" in out.answer


async def test_tier_difference_adopts_higher():
    s = NodeSummary(
        question_id="n1",
        answer="주장 [C:aaaaaaaa]",
        key_claim_ids=["aaaaaaaa"],
        confidence=0.7,
        caveats=[],
        conflicts=[ConflictNote("aaaaaaaa", "bbbbbbbb", "상반")],
    )
    led = FakeLedger(
        {"aaaaaaaa": ["https://arxiv.org/x"], "bbbbbbbb": ["http://blog.com"]}
    )  # a=tier1
    out, reinv = await resolve_conflicts(led, s, TIERS)
    assert "양론" not in out.answer  # 상위 채택, 양론 병기 아님
    assert any("[C:bbbbbbbb]" in c for c in out.caveats)  # 하위 출처 각주


async def test_reinvestigation_ids_use_conflict_value_threshold():
    s = NodeSummary(
        question_id="n1",
        answer="주장",
        key_claim_ids=["aaaaaaaa"],
        confidence=0.7,
        caveats=[],
        conflicts=[ConflictNote("aaaaaaaa", "bbbbbbbb", "상반")],
    )
    led = FakeLedger(
        {"aaaaaaaa": ["http://blog1.com"], "bbbbbbbb": ["http://blog2.com"]}
    )
    # FakeLedger.get_claim always returns value_est=0.5; default
    # conflict_value_threshold is 0.6, so no reinvestigation is triggered.
    _, reinv = await resolve_conflicts(led, s, TIERS)
    assert reinv == []


async def test_no_conflicts_is_a_noop():
    s = NodeSummary(
        question_id="n1",
        answer="주장",
        key_claim_ids=[],
        confidence=0.7,
        caveats=[],
        conflicts=[],
    )
    led = FakeLedger({})
    out, reinv = await resolve_conflicts(led, s, TIERS)
    assert out.answer == "주장"
    assert reinv == []


def test_tier1_is_not_only_american():
    """실제 배포 목록은 `.gov`/`.edu` 로 미국 중심이라 유럽·영국·한국의
    1차 기관 출처가 블로그와 같은 등급이었다.

    표본 #7 에서 판정자가 반려한 사유가 정확히 이것이다 -- "질문이 요구한
    '공식 EU 출처' 를 전혀 사용하지 못하고 2차 블로그성 출처에 의존".
    """
    from neos.config.settings import settings

    tiers = settings.config.deep_analysis.source_tiers

    # 1차 기관: 규칙을 만든 곳, 데이터를 낸 곳.
    assert source_tier("https://eur-lex.europa.eu/eli/reg/2024/1689", tiers) == 1
    assert source_tier("https://digital-strategy.ec.europa.eu/en/news/x", tiers) == 1
    assert source_tier("https://www.iarc.who.int/news/x", tiers) == 1
    assert source_tier("https://www.gov.uk/guidance/x", tiers) == 1
    assert source_tier("https://www.birmingham.ac.uk/research/x", tiers) == 1
    assert source_tier("https://www.data.go.kr/x", tiers) == 1

    # 신뢰할 만해도 2차인 것들 -- 신뢰도가 아니라 원본성이 기준이다.
    assert source_tier("https://www.bbc.com/news/x", tiers) == 2
    assert source_tier("https://dev.to/p/x", tiers) == 2
    assert source_tier("https://blog.example.tistory.com/1", tiers) == 2

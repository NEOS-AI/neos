from __future__ import annotations

from pathlib import Path

import pytest

from neos.skills.markdown_catalog import (
    K_SKILL_EXCLUDED,
    default_catalog,
    fsi_catalog,
    k_skill_catalog,
    univer_catalog,
)

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK = REPO_ROOT / "skills" / "k-skill"

PORT_SET = frozenset(
    {
        "animal-pharmacy-search",
        "assembly-bill-vote-search",
        "bccard-eatpl-search",
        "biz-health-check",
        "bok-ecos-stats",
        "building-register-search",
        "bunjang-search",
        "cheap-gas-nearby",
        "consumer-price-safety-search",
        "corporate-registration-consulting",
        "coupang-product-search",
        "court-auction-notice-search",
        "court-payment-order-assistant",
        "d2b-notice-search",
        "daangn-cars-search",
        "daangn-jobs-search",
        "daangn-realty-search",
        "daangn-used-goods-search",
        "daishin-report-search",
        "daiso-product-search",
        "danawa-price-search",
        "delivery-tracking",
        "donation-place-search",
        "emergency-room-beds",
        "ev-charger-nearby",
        "ev-subsidy-status",
        "express-bus-booking",
        "fine-dust-location",
        "flight-ticket-search",
        "foresttrip-vacancy",
        "fsc-corporate-info",
        "g2b-order-plan-search",
        "g2b-sanctioned-supplier",
        "geeknews-search",
        "gongsijiga-search",
        "gov-overseas-trip-report",
        "government-support-survey",
        "han-river-water-level",
        "hankookilbo-news",
        "highway-traffic-status",
        "hola-poke-yeoksam",
        "household-waste-info",
        "housing-official-price",
        "hwp",
        "intercity-bus-booking",
        "iros-registry-automation",
        "job-posting-match",
        "jobkorea-talent-search",
        "joseon-sillok-search",
        "k-dart",
        "k-schoollunch-menu",
        "kakao-bar-nearby",
        "kakao-map",
        "kakaotalk-mac",
        "kamis-food-price",
        "kbl-results",
        "kbo-results",
        "keris-academic-search",
        "kleague-results",
        "komsa-ferry-info",
        "kopis-performance-search",
        "korea-weather",
        "korean-character-count",
        "korean-cinema-search",
        "korean-heritage-search",
        "korean-holiday-calendar",
        "korean-humanizer",
        "korean-jangbu-for",
        "korean-law-search",
        "korean-marathon-schedule",
        "korean-middle-korean",
        "korean-patent-search",
        "korean-privacy-terms",
        "korean-scholarship-search",
        "korean-slang-writing",
        "korean-spell-check",
        "korean-stock-search",
        "korean-transit-route",
        "kosis-stats",
        "kr-whois-lookup",
        "kstartup-search",
        "lck-analytics",
        "lh-notice-search",
        "library-book-search",
        "localdata-business-status",
        "lotto-results",
        "market-kurly-search",
        "mfds-drug-safety",
        "mfds-food-safety",
        "mofa-travel-safety",
        "multi-asset-morning-briefing",
        "myrealtrip-search",
        "naming-house",
        "national-pension-workplace",
        "naver-ad-performance",
        "naver-blog-research",
        "naver-news-search",
        "naver-shopping-search",
        "nhis-care-checkup-search",
        "nts-business-registration",
        "nts-tax-delinquency",
        "ohou-today-deal",
        "olive-young-search",
        "parking-lot-search",
        "popbill",
        "public-restroom-nearby",
        "railway-timetable",
        "real-estate-search",
        "religious-facility-search",
        "rhwp-advanced",
        "rhwp-edit",
        "s2b-notice-search",
        "saju-fortune",
        "saramin-talent-search",
        "seoul-bike",
        "seoul-density",
        "seoul-subway-arrival",
        "seoul-weather-risk",
        "sh-notice-search",
        "sharenuri-facility-search",
        "store-longevity-radar",
        "subway-lost-property",
        "ticket-availability",
        "toss-investment",
        "zipcode-search",
    }
)


def test_port_set_has_one_hundred_twenty_five_names() -> None:
    assert len(PORT_SET) == 125
    assert K_SKILL_EXCLUDED.isdisjoint(PORT_SET)


def test_k_skill_catalog_indexes_the_port_set() -> None:
    names = {skill.name for skill in k_skill_catalog().list_skills()}
    assert names == PORT_SET


def test_excluded_meta_skills_are_absent() -> None:
    catalog = k_skill_catalog()
    for name in K_SKILL_EXCLUDED:
        assert catalog.get(name) is None
        assert not (PACK / name).exists()


def test_directory_name_matches_frontmatter_name() -> None:
    for skill in k_skill_catalog().list_skills():
        assert skill.path.parent.name == skill.name
        assert skill.path == (PACK / skill.name / "SKILL.md").resolve()


def test_korea_weather_body_is_instruction_not_cli_stub() -> None:
    body = k_skill_catalog().load_markdown("korea-weather")
    assert body is not None
    assert "k-skill:cli-stub" not in body
    assert "npx -y @nomadamas/k-skill@0 instruct korea-weather" not in body
    assert "k-skill-proxy" in body
    assert "When to use" in body or "When to Use" in body


def test_every_pack_skill_body_is_instruction_not_cli_stub() -> None:
    catalog = k_skill_catalog()
    for skill in catalog.list_skills():
        body = catalog.load_markdown(skill.name)
        assert body is not None, skill.name
        assert "k-skill:cli-stub" not in body, skill.name
        assert f"npx -y @nomadamas/k-skill@0 instruct {skill.name}" not in body, skill.name


def test_source_md_uses_sibling_path_not_machine_local() -> None:
    text = (PACK / "SOURCE.md").read_text(encoding="utf-8")
    assert "`../k-skill`" in text
    assert "/Users/" not in text
    assert "scripts/vendor_k_skill.py" in text


def test_foreign_packs_do_not_index_k_skill_names() -> None:
    assert default_catalog().get("korea-weather") is None
    assert fsi_catalog().get("korea-weather") is None
    assert univer_catalog().get("korea-weather") is None
    assert k_skill_catalog().get("xlsx-author") is None
    assert k_skill_catalog().get("univer-sheets-headless") is None

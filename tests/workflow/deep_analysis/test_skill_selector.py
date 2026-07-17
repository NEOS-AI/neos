import pytest

from neos.workflow.deep_analysis.models import Effort
from neos.workflow.deep_analysis.skill_selector import SkillSelector


pytestmark = pytest.mark.no_db


class FakeSkill:
    def __init__(self, name):
        self.name = name


class FakeRegistry:
    def __init__(self, names):
        self._skills = {n: FakeSkill(n) for n in names}

    def get_skill(self, name):
        return self._skills.get(name)


def test_scout_gets_no_skills():
    # scout의 token_cap은 2000이라 도구 스키마 + 멀티턴이 들어가지 않는다.
    selector = SkillSelector(
        FakeRegistry(["arxiv", "pubmed"]), allowlist=["arxiv", "pubmed"], cap=3
    )
    assert selector.candidates(Effort.SCOUT) == []


def test_dig_gets_allowlisted_skills_in_allowlist_order():
    selector = SkillSelector(
        FakeRegistry(["arxiv", "pubmed", "openalex"]),
        allowlist=["pubmed", "arxiv"],
        cap=3,
    )
    names = [s.name for s in selector.candidates(Effort.DIG)]
    assert names == ["pubmed", "arxiv"]


def test_unregistered_allowlist_entries_are_skipped():
    selector = SkillSelector(
        FakeRegistry(["arxiv"]), allowlist=["arxiv", "nonexistent"], cap=3
    )
    assert [s.name for s in selector.candidates(Effort.DIG)] == ["arxiv"]


def test_cap_bounds_the_candidate_set():
    # dig의 token_cap(12000)을 도구 스키마가 잠식하지 않도록 상한을 둔다.
    selector = SkillSelector(
        FakeRegistry(["a", "b", "c", "d"]), allowlist=["a", "b", "c", "d"], cap=2
    )
    assert [s.name for s in selector.candidates(Effort.DIG)] == ["a", "b"]


def test_no_registry_yields_no_candidates():
    selector = SkillSelector(None, allowlist=["arxiv"], cap=3)
    assert selector.candidates(Effort.DIG) == []


def test_selector_reads_allowlist_and_cap_from_settings():
    # 기본 설정만으로 구성해도 dig에서 후보가 나온다.
    selector = SkillSelector(
        FakeRegistry(["arxiv", "pubmed", "openalex", "wikipedia"])
    )
    names = [s.name for s in selector.candidates(Effort.DIG)]

    assert len(names) <= 3  # max_discovery_skills 기본값
    assert "arxiv" in names

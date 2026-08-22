import json

import pytest

from neos.config.settings import settings
from neos.workflow.deep_analysis.manifest import MANIFEST_KIND
from neos.workflow.deep_analysis.service import build_orchestrator


class _FakeLedger:
    def __init__(self):
        self.events = []

    async def log(self, kind, qid, payload):
        # 직렬화 가능성까지 확인한다 -- 실제 `Ledger.log` 는
        # `json.dumps(payload, ensure_ascii=False)` 를 통과시킨다.
        json.dumps(payload, ensure_ascii=False)
        self.events.append((kind, qid, payload))


@pytest.fixture
def fake_ledger(monkeypatch):
    ledger = _FakeLedger()
    monkeypatch.setattr(
        "neos.workflow.deep_analysis.service.Ledger",
        lambda session, run_id: ledger,
    )
    return ledger


def _manifest(ledger):
    kinds = [kind for kind, _, _ in ledger.events]
    assert kinds.count(MANIFEST_KIND) == 1
    return next(p for k, _, p in ledger.events if k == MANIFEST_KIND)


@pytest.mark.asyncio
async def test_build_orchestrator_emits_one_manifest(fake_ledger):
    await build_orchestrator(object(), "run0001", profile="dev")

    assert _manifest(fake_ledger)["manifest_version"] == 1


@pytest.mark.asyncio
async def test_manifest_budget_matches_what_the_orchestrator_received(
    fake_ledger,
):
    """§2.1 의 재계산 사고를 기계가 막는다.

    매니페스트의 예산 값과 Orchestrator 가 실제로 받은 값이 같은 표현에서
    나왔는지 확인한다. 갈라지면 매니페스트가 조용히 거짓말한다.
    """
    orchestrator = await build_orchestrator(object(), "run0002", profile="dev")
    budget = _manifest(fake_ledger)["budget"]

    assert budget["global_token_cap"] == orchestrator.global_token_cap
    assert (
        budget["finalization_floor_tokens"]
        == orchestrator.finalization_floor_tokens
    )
    assert budget["report_floor_tokens"] == orchestrator.report_floor_tokens
    assert budget["grading_floor_tokens"] == orchestrator.grading_floor_tokens
    assert (
        budget["min_viable_output_tokens"]
        == orchestrator.min_viable_output_tokens
    )


@pytest.mark.asyncio
async def test_dev_profile_manifest_records_the_dev_cap(fake_ledger):
    """기존 아티팩트가 틀린 바로 그 칸.

    표본 #20 의 manifest.json 은 dev 런 5건에 대해 global_token_cap 300000
    (기본 프로파일)을 적었다. dev 는 dev_profile.global_token_cap 으로 돈다.
    """
    await build_orchestrator(object(), "run0003", profile="dev")
    budget = _manifest(fake_ledger)["budget"]

    assert (
        budget["global_token_cap"]
        == settings.config.deep_analysis.dev_profile.global_token_cap
    )
    assert (
        budget["global_token_cap"]
        != settings.config.deep_analysis.global_token_cap
    )


@pytest.mark.asyncio
async def test_available_for_investigation_is_cap_minus_floor(fake_ledger):
    """D75 -> D77 -> D78 이 세 번 다시 한 뺄셈."""
    await build_orchestrator(object(), "run0004", profile="dev")
    budget = _manifest(fake_ledger)["budget"]

    assert budget["available_for_investigation"] == (
        budget["global_token_cap"] - budget["finalization_floor_tokens"]
    )


@pytest.mark.asyncio
async def test_manifest_records_wired_components(fake_ledger):
    await build_orchestrator(object(), "run0005", profile="dev")
    components = _manifest(fake_ledger)["components"]

    assert components["grader"] == (
        "graders.deterministic:DeterministicGrader"
    )
    assert components["report_grader"] == "graders.report:ReportGrader"
    assert components["cassette"] is False


@pytest.mark.asyncio
async def test_manifest_records_synthesizer_and_citation_renderer(fake_ledger):
    """FIX 1: 이 두 부품은 kwargs 로 넘겨지지 않아도 항상 조립된다.

    `Orchestrator.__init__` 은 `synthesizer`/`citation_renderer` 가 `None`
    이면 각각 `Synthesizer`/`CitationRenderer` 를 무조건 만든다
    (`build_orchestrator` 는 그 kwargs 를 절대 채우지 않는다). 매니페스트가
    이 칸을 `null` 로 적으면 "안 쓰였다" 는 거짓을 말하는 것이다.
    """
    await build_orchestrator(object(), "run0007", profile="dev")
    components = _manifest(fake_ledger)["components"]

    assert components["synthesizer"] == "synthesizer:Synthesizer"
    assert components["citation_renderer"] == "citation:CitationRenderer"


@pytest.mark.asyncio
async def test_manifest_skills_is_none_without_a_registry(fake_ledger):
    await build_orchestrator(object(), "run0006", profile="dev")

    assert _manifest(fake_ledger)["skills"] is None

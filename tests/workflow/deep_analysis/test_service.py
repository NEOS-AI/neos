import pytest

from neos.config.settings import settings
from neos.workflow.deep_analysis.service import (
    build_orchestrator,
    web_search,
)


pytestmark = pytest.mark.no_db


class _FakeLedger:
    """Swallows `Ledger.log` so `build_orchestrator`'s manifest emission
    doesn't need a real session. These tests pass `object()` as the
    session and only care about the values `build_orchestrator` derives
    and wires, not about ledger persistence.
    """

    def __init__(self):
        self.events = []

    async def log(self, kind, qid, payload):
        self.events.append((kind, qid, payload))


def _install_fake_ledger(monkeypatch) -> _FakeLedger:
    ledger = _FakeLedger()
    monkeypatch.setattr(
        "neos.workflow.deep_analysis.service.Ledger",
        lambda session, run_id: ledger,
    )
    return ledger


class FakeSearchResult:
    success = True
    data = [
        {
            "url": "https://example.com",
            "title": "Title",
            "content": "Snippet",
        }
    ]


class FakeSearchTool:
    def __init__(self):
        self.cleaned = False

    async def initialize(self):
        return True

    async def execute(self, params):
        assert params == {"query": "query", "max_results": 2}
        return FakeSearchResult()

    async def cleanup(self):
        self.cleaned = True


@pytest.mark.asyncio
async def test_web_search_adapts_mcp_result_and_cleans_up():
    tools = []

    def factory():
        tool = FakeSearchTool()
        tools.append(tool)
        return tool

    results = await web_search("query", 2, tool_factory=factory)

    assert results == [
        {
            "url": "https://example.com",
            "title": "Title",
            "snippet": "Snippet",
        }
    ]
    assert tools[0].cleaned


@pytest.mark.asyncio
async def test_build_orchestrator_uses_dev_cap_and_pure_worker(monkeypatch):
    """profile="dev" must resolve the DEV profile's cap, not the default's.

    dev.global_token_cap is 140000 (see schema.py), default is 300000 --
    still distinct enough that this assertion fails if build_orchestrator
    ever falls back to the default profile's cap.

    Also guards the service -> budget wiring itself: build_orchestrator
    computes both floor tiers from config and passes `report_floor_tokens`
    into `Orchestrator(...)` (service.py). That kwarg is the only thing
    that makes the inner tier real in production -- drop it and every run
    gets `report_floor_tokens=0`, `report_assembly` competes with
    `node_reduction` for the same pool again, and the original 574-run
    defect (report_assembly never reserved) returns silently, with
    `tests/workflow/deep_analysis` still green apart from this assertion.
    """

    _install_fake_ledger(monkeypatch)

    async def search_fn(query, k):
        return []

    from neos.config.settings import settings

    custom_caps = {1: 0.51, 2: 0.72, 3: 0.93}
    monkeypatch.setattr(settings.config.deep_analysis, "confidence_cap", custom_caps)
    orchestrator = await build_orchestrator(
        object(),
        "run00001",
        profile="dev",
        search_fn=search_fn,
    )
    worker = orchestrator.worker_factory()

    assert orchestrator.global_token_cap == 140000
    # dev profile values (synthesis_max_tokens=2000): report_floor_tokens =
    # grading (5.0*2000+800 = 10,800) * (report_retry_cap + 1) + assembly
    # (2*3.0*2000 + 3*2000 = 18,000, counting call_text's truncation expansion
    # -- D56) * report_floor_funded_attempts (1.2, D78) = 21,600 + 21,600 =
    # 43,200; floor_tokens = report_floor_tokens + reduction_floor (10,400) =
    # 53,600. Both tiers must land on the orchestrator's actual TokenBudget,
    # not just be computed and dropped.
    assert orchestrator.token_budget.report_floor_tokens == 43_200
    assert orchestrator.token_budget.floor_tokens == 53_600
    assert not hasattr(worker, "db")
    assert not hasattr(worker, "run_id")
    assert worker._confidence_cap == custom_caps
    assert worker._confidence_cap is not custom_caps


@pytest.mark.parametrize(
    ("feature_model", "expected_model"),
    [
        (None, "claude-sonnet-5"),
        ("claude-judge-manual", "claude-judge-manual"),
    ],
)
@pytest.mark.asyncio
async def test_build_orchestrator_resolves_judge_at_construction_boundary(
    monkeypatch, feature_model, expected_model
) -> None:
    monkeypatch.setattr(
        settings.config.deep_analysis.models,
        "judge",
        feature_model,
    )
    _install_fake_ledger(monkeypatch)

    orchestrator = await build_orchestrator(
        object(),
        "run00001",
        search_fn=lambda query, k: [],
    )

    assert orchestrator.agentic_grader.judge_model == expected_model
    assert orchestrator.report_grader.judge_model == expected_model


# ---- 트랙 J: 조사 경로 배선 --------------------------------------------------


async def _research_search_fn(query, k):
    return []


@pytest.mark.asyncio
async def test_code_research_off_wires_no_sandbox(monkeypatch):
    """I1. 꺼져 있으면 provider 도 런타임 팩토리도 만들지 않는다."""
    _install_fake_ledger(monkeypatch)
    monkeypatch.setattr(settings.config.deep_analysis, "code_research_enabled", False)

    orchestrator = await build_orchestrator(
        object(), "run00001", profile="dev", search_fn=_research_search_fn
    )

    assert orchestrator.sandbox_provider is None
    assert orchestrator.research_runtime_factory is None


@pytest.mark.asyncio
async def test_code_research_on_wires_a_provider_and_a_runtime_factory(monkeypatch):
    """켜지면 둘 다 붙는다 -- 하나라도 없으면 질문마다 실패한다."""
    import neos.coding.sandbox.factory as factory_module

    _install_fake_ledger(monkeypatch)
    monkeypatch.setattr(settings.config.deep_analysis, "code_research_enabled", True)
    sentinel = object()
    monkeypatch.setattr(
        factory_module, "create_sandbox_provider", lambda config, **kw: sentinel
    )

    orchestrator = await build_orchestrator(
        object(), "run00001", profile="dev", search_fn=_research_search_fn
    )

    assert orchestrator.sandbox_provider is sentinel
    assert callable(orchestrator.research_runtime_factory)


@pytest.mark.asyncio
async def test_a_sandbox_that_cannot_be_built_does_not_break_the_run(monkeypatch):
    """빌드를 터뜨리지 않는다.

    빠진 조각은 `_run_worker` 가 질문 단위로 시끄럽게 보고한다
    (`sandbox_provider_missing`). 여기서 터뜨리면 조사와 무관한 단계까지 같이
    죽고, 그것은 플래그 하나가 런 전체를 못 돌게 만드는 모양이다.
    """
    import neos.coding.sandbox.factory as factory_module

    _install_fake_ledger(monkeypatch)
    monkeypatch.setattr(settings.config.deep_analysis, "code_research_enabled", True)

    def boom(config, **kwargs):
        raise RuntimeError("no docker here")

    monkeypatch.setattr(factory_module, "create_sandbox_provider", boom)

    orchestrator = await build_orchestrator(
        object(), "run00001", profile="dev", search_fn=_research_search_fn
    )

    assert orchestrator.sandbox_provider is None
    assert orchestrator.research_runtime_factory is None

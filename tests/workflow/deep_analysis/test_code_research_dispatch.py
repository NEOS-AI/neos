"""`_run_worker` 의 조사 분기 (계약 §7 · I1).

이 파일이 지키는 것은 **플래그가 꺼져 있을 때 아무 일도 일어나지 않는다**
이다. 분기가 생기는 커밋에서 같이 들어가야 의미가 있다 -- 나중에 쓰면 그때는
이미 플래그 off 경로가 움직였는지 알 수 없다(`test_code_research_invariants`
의 같은 이유).

그리고 **조용한 degrade 를 금지한다.** 플래그가 켜졌는데 샌드박스 provider 가
없으면 기존 경로로 슬쩍 떨어지지 않는다 -- 그러면 "조사 모드로 돌고 있다" 고
믿는 실행이 사실은 옛 워커를 돌리고, 원장에는 그 사실이 남지 않는다.
`subagent_runtime_missing` 과 같은 모양으로 이유를 단 실패를 돌려준다.
"""

from __future__ import annotations

from typing import Any

import pytest

from neos.config.settings import settings
from neos.workflow.deep_analysis import orchestrator as orchestrator_module
from neos.workflow.deep_analysis.models import Assignment, Effort, WorkerResult
from neos.workflow.deep_analysis.orchestrator import Orchestrator

pytestmark = pytest.mark.no_db


class _FakeLedger:
    def __init__(self) -> None:
        self.run_id = "run00001"
        self.events: list[Any] = []

    async def get_question(self, question_id: str):
        return None


class _LegacyWorker:
    """`_run_legacy_worker` 가 쓰는 표면만."""

    def __init__(self, seen: list[str]) -> None:
        self._seen = seen
        self.tokens_spent = 0
        self.model = "legacy-model"

    async def investigate(
        self, brief, effort, question_id, *, repairs=None, question_text=""
    ):
        self._seen.append(question_id)
        # `model` 을 채우는 이유: 결과가 **이 워커에서 왔다**는 것을 부르는
        # 쪽에서 확인할 수 있어야 한다. 비워 두면 옛 경로를 탔는지 아닌지를
        # 호출 기록으로만 판단하게 된다.
        return WorkerResult(
            question_id=question_id, status="completed", model="legacy-model"
        )

    def flush_partial(self, question_id: str) -> WorkerResult:
        return WorkerResult(question_id=question_id, status="partial")


def _assignment() -> Assignment:
    return Assignment(
        question_id="q_1",
        brief="브리프",
        effort=Effort.DIG,
        question_text="질문",
    )


def _orchestrator(*, legacy_seen: list[str], provider=None, runtime_factory=None):
    return Orchestrator(
        object(),
        "run00001",
        worker_factory=lambda: _LegacyWorker(legacy_seen),
        grader=object(),
        ledger=_FakeLedger(),
        sandbox_provider=provider,
        research_runtime_factory=runtime_factory,
    )


@pytest.fixture
def research_spy(monkeypatch):
    """조사 경로가 불렸는지, 무슨 인자로 불렸는지."""
    calls: list[dict[str, Any]] = []

    async def spy(assignment, **kwargs):
        calls.append({"assignment": assignment, **kwargs})
        return WorkerResult(question_id=assignment.question_id, status="completed")

    monkeypatch.setattr(orchestrator_module, "run_research_worker", spy)
    return calls


@pytest.mark.asyncio
async def test_with_the_flag_off_the_research_path_is_never_entered(
    monkeypatch, research_spy
) -> None:
    """I1. provider 가 붙어 있어도 플래그가 꺼져 있으면 옛 경로 그대로다."""
    monkeypatch.setattr(settings.config.deep_analysis, "code_research_enabled", False)
    seen: list[str] = []
    orchestrator = _orchestrator(
        legacy_seen=seen, provider=object(), runtime_factory=lambda port: object()
    )

    result = await orchestrator._run_worker(_assignment())

    assert research_spy == []
    assert seen == ["q_1"]
    assert result.model == "legacy-model"


@pytest.mark.asyncio
async def test_with_the_flag_on_the_research_path_runs(
    monkeypatch, research_spy
) -> None:
    monkeypatch.setattr(settings.config.deep_analysis, "code_research_enabled", True)
    seen: list[str] = []
    provider = object()

    def runtime_factory(port):
        return object()

    orchestrator = _orchestrator(
        legacy_seen=seen, provider=provider, runtime_factory=runtime_factory
    )

    result = await orchestrator._run_worker(_assignment())

    assert seen == []  # 옛 워커는 돌지 않았다
    assert len(research_spy) == 1
    call = research_spy[0]
    assert call["provider"] is provider
    assert call["parent_id"] == "run00001"
    assert (
        call["cap_bytes"]
        == settings.config.deep_analysis.code_research.evidence_bytes_cap
    )
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_the_flag_on_without_a_provider_fails_loudly(
    monkeypatch, research_spy
) -> None:
    """조용히 옛 경로로 떨어지지 않는다."""
    monkeypatch.setattr(settings.config.deep_analysis, "code_research_enabled", True)
    seen: list[str] = []
    orchestrator = _orchestrator(legacy_seen=seen, provider=None)

    result = await orchestrator._run_worker(_assignment())

    assert result.status == "failed"
    assert result.fail_reason == "sandbox_provider_missing"
    assert seen == []
    assert research_spy == []


@pytest.mark.asyncio
async def test_the_flag_on_without_a_runtime_factory_fails_loudly(
    monkeypatch, research_spy
) -> None:
    """provider 는 있는데 런타임을 지을 방법이 없는 경우.

    이유를 provider 쪽과 **다르게** 적는다 -- 둘을 한 이름으로 뭉치면 설정을
    고칠 때 어느 쪽이 빠졌는지 원장이 말해주지 못한다.
    """
    monkeypatch.setattr(settings.config.deep_analysis, "code_research_enabled", True)
    seen: list[str] = []
    orchestrator = _orchestrator(
        legacy_seen=seen, provider=object(), runtime_factory=None
    )

    result = await orchestrator._run_worker(_assignment())

    assert result.status == "failed"
    assert result.fail_reason == "research_runtime_factory_missing"
    assert seen == []
    assert research_spy == []


@pytest.mark.asyncio
async def test_the_child_pointers_reach_the_research_path(
    monkeypatch, research_spy
) -> None:
    """재개는 포인터로 이어진다 -- 기존 서브에이전트 경로와 같은 계약."""
    monkeypatch.setattr(settings.config.deep_analysis, "code_research_enabled", True)
    orchestrator = _orchestrator(
        legacy_seen=[], provider=object(), runtime_factory=lambda port: object()
    )

    await orchestrator._run_worker(
        _assignment(), child_run_id="sa_1", child_checkpoint_id="cp_1"
    )

    call = research_spy[0]
    assert call["run_id"] == "sa_1"
    assert call["expected_checkpoint_id"] == "cp_1"

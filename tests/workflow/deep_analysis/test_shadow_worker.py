"""섀도가 돌리는 워커는 **진짜 조사 워커**여야 한다 (로드맵 J3).

`run_offline_shadow` 는 `worker` 를 주입받는다 -- 섀도의 일은 격리·재생·비교
이지 조사 경로를 다시 조립하는 것이 아니기 때문이다. 그런데 주입만 있고
**진짜를 꽂는 어댑터가 없으면** J3 는 테스트에서만 도는 기계로 남는다.
이 파일이 그 어댑터를 고정한다.

고정하는 것은 둘이다.

1. `run_research_worker` 에 **섀도 원장이 간다.** 진짜 원장이 가면 섀도
   실행이 기록된 run 을 바꾸고, 그러면 그 run 은 더 이상 비교 대상이 아니다.
2. `fetch_fn` 으로 **보관소가 간다.** 라이브 `fetch_url` 이 가면 그것은
   오프라인이 아니라 그냥 또 한 번의 라이브 실행이다.

둘 다 "인자 하나를 잘못 넘기면 조용히 라이브가 된다" 는 모양이라, 조용해지지
않도록 인자를 직접 들여다본다.
"""

from __future__ import annotations

from typing import Any

import pytest

from neos.workflow.deep_analysis.models import Assignment, Effort, WorkerResult

pytestmark = pytest.mark.no_db


class _Ledger:
    run_id = "run00001"

    async def get_blob(self, content_hash: str):
        return None


def _assignment() -> Assignment:
    return Assignment(
        question_id="q_1", brief="브리프", effort=Effort.DIG, question_text="질문"
    )


@pytest.fixture
def research_spy(monkeypatch):
    from neos.workflow.deep_analysis import shadow as shadow_module

    calls: list[dict[str, Any]] = []

    async def spy(assignment, **kwargs):
        calls.append({"assignment": assignment, **kwargs})
        return WorkerResult(question_id=assignment.question_id, status="completed")

    monkeypatch.setattr(shadow_module, "run_research_worker", spy)
    return calls


def _worker(**overrides):
    from neos.workflow.deep_analysis.shadow import build_shadow_worker

    kwargs: dict[str, Any] = {
        "provider": object(),
        "grader": object(),
        "runtime_factory": lambda port: object(),
        "cap_bytes": 1024,
        "limits": object(),
        "parent_id": "run00001",
    }
    kwargs.update(overrides)
    return build_shadow_worker(**kwargs)


@pytest.mark.asyncio
async def test_the_shadow_ledger_is_what_the_worker_gets(research_spy) -> None:
    """인자 하나를 잘못 넘기면 섀도가 조용히 진짜 원장에 쓴다."""
    from neos.workflow.deep_analysis.shadow import ShadowLedger

    shadow = ShadowLedger(_Ledger())

    async def fetch(url):
        raise AssertionError

    await _worker()(_assignment(), ledger=shadow, fetch_fn=fetch)

    assert research_spy[0]["ledger"] is shadow


@pytest.mark.asyncio
async def test_the_archive_is_what_the_worker_fetches_with(research_spy) -> None:
    """라이브 `fetch_url` 이 가면 오프라인이 아니라 또 한 번의 라이브다."""

    async def fetch(url):
        raise AssertionError

    await _worker()(_assignment(), ledger=object(), fetch_fn=fetch)

    assert research_spy[0]["fetch_fn"] is fetch


@pytest.mark.asyncio
async def test_the_assembled_pieces_reach_the_worker(research_spy) -> None:
    """샌드박스·채점기·런타임·한도. 하나라도 빠지면 질문마다 실패한다."""
    provider, grader, limits = object(), object(), object()

    def runtime_factory(port):
        return object()

    await _worker(
        provider=provider,
        grader=grader,
        limits=limits,
        runtime_factory=runtime_factory,
        cap_bytes=4096,
    )(_assignment(), ledger=object(), fetch_fn=object())

    call = research_spy[0]
    assert call["provider"] is provider
    assert call["grader"] is grader
    assert call["limits"] is limits
    assert call["runtime_factory"] is runtime_factory
    assert call["cap_bytes"] == 4096
    assert call["parent_id"] == "run00001"


@pytest.mark.asyncio
async def test_the_worker_result_comes_back_untouched(research_spy) -> None:
    """어댑터는 배선이지 판단이 아니다 -- 제안을 여기서 거르면 비교가 거짓말한다."""
    result = await _worker()(_assignment(), ledger=object(), fetch_fn=object())

    assert result.question_id == "q_1"
    assert result.status == "completed"

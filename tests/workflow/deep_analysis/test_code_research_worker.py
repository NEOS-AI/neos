"""질문 하나를 조사 자식으로 돌린다 (계약 §3.4 · §2).

여기서 고정하는 것 넷:

1. **blob 을 결과에 싣지 않는다.** 기존 경로는 워커가 `blobs` 를 돌려주고
   오케스트레이터가 `commit_blobs(result.blobs)` 로 커밋한다. 조사 경로는
   `fetch.v1` 이 **이미 건별로 커밋했고 바이트도 청구했다.** 결과에 또 실으면
   같은 blob 이 두 경로로 흐른다.

2. **제출 없이 끝난 턴은 `partial` 이고 이유가 남는다.** 계약 §3.4 가
   "조용한 degrade 금지" 라고 적은 자리다.

3. **샌드박스는 무슨 일이 있어도 닫힌다.** 리스가 없어 뒤늦게 회수해 줄 층이
   없다 -- 여기서 안 닫으면 아무도 안 닫는다. 그래서 정상 턴과 터진 턴
   **양쪽**에서 본다.

4. **자식은 `research` 스펙으로 돈다.** explore 가 아니다 -- 스펙이 도구
   목록을 정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from neos.coding.sandbox.base import SandboxLimits, SandboxNotFound
from neos.coding.sandbox.memory import MemorySandboxProvider
from neos.subagent.types import StepKind
from neos.workflow.deep_analysis.models import Assignment, Effort

pytestmark = pytest.mark.no_db


@dataclass
class _Blob:
    content_hash: str = "abc123def456ffff"
    source_url: str = "https://example.com/doc"
    http_status: int = 200
    raw_text: str = "hello evidence"


class _FakeQuestion:
    def __init__(self) -> None:
        self.evidence_bytes = 0


class _FakeDb:
    async def flush(self) -> None:
        return None


class _FakeLedger:
    def __init__(self) -> None:
        self.db = _FakeDb()
        self.question = _FakeQuestion()
        self.committed: list[Any] = []
        self.events: list[tuple[str, str, dict]] = []
        self._stored: set[str] = set()

    async def log(self, kind: str, qid: str, payload: dict) -> None:
        self.events.append((kind, qid, payload))

    async def get_question(self, question_id: str):
        return self.question

    async def get_blob(self, content_hash: str):
        return object() if content_hash in self._stored else None

    async def commit_blobs(self, blobs) -> None:
        self.committed.extend(blobs)
        for blob in blobs:
            self._stored.add(blob.content_hash)


@dataclass
class _Outcome:
    run_id: str = "sa_research_1"
    checkpoint_id: str = "cp_1"
    kind: Any = StepKind.COMPLETED
    tokens_delta: int = 120


class _Runtime:
    """`advance` 안에서 자식이 도구를 부른 것처럼 군다."""

    def __init__(self, port, *, calls=(), outcome: _Outcome | None = None, boom=False):
        self._port = port
        self._calls = list(calls)
        self._outcome = outcome or _Outcome()
        self._boom = boom
        self.advanced: list[Any] = []

    async def advance(self, ticket):
        self.advanced.append(ticket)
        if self._boom:
            raise RuntimeError("child exploded")
        for name, payload in self._calls:
            await self._port.execute(name, payload)
        return self._outcome


def _assignment() -> Assignment:
    return Assignment(
        question_id="q_1",
        brief="조사 브리프",
        effort=Effort.DIG,
        question_text="런던은 2026년에 비가 왔는가",
    )


_SUBMISSION = {
    "status": "completed",
    "claims": [
        {
            "kind": "quote",
            "text": "런던은 2026년에 비가 왔다",
            "confidence": 0.6,
            "evidence": [
                {
                    "source_url": "https://example.com/doc",
                    "excerpt": "it rained",
                    "raw_ref": "abc123def456ffff",
                }
            ],
        }
    ],
    "self_assessment": 0.8,
    "proposed_subquestions": [{"text": "파리는?", "value_est": 0.5}],
    "dead_ends": ["기상청 API 는 2020 년까지"],
    "repairs": [],
}


async def _run(
    tmp_path,
    *,
    ledger: _FakeLedger,
    calls=(),
    outcome: _Outcome | None = None,
    boom: bool = False,
):
    """돌리고, **어떤 샌드박스를 열었는지**까지 돌려준다.

    id 를 잡아 두지 않으면 "닫혔는가" 를 단언할 방법이 없다 -- 세션은 함수
    안에서 태어나고 죽는다.
    """
    from neos.workflow.deep_analysis import research_worker as module

    provider = MemorySandboxProvider(root=tmp_path / "da-sandboxes")
    seen: dict[str, Any] = {}
    real_open = module.open_research_session

    async def spy(**kwargs):
        session = await real_open(**kwargs)
        seen["sandbox_id"] = session.sandbox.sandbox_id
        return session

    async def fetch_fn(url: str):
        return _Blob()

    def runtime_factory(port):
        runtime = _Runtime(port, calls=calls, outcome=outcome, boom=boom)
        seen["runtime"] = runtime
        return runtime

    module.open_research_session = spy  # type: ignore[assignment]
    try:
        result = await module.run_research_worker(
            _assignment(),
            ledger=ledger,
            provider=provider,
            grader=None,
            cap_bytes=1000,
            limits=SandboxLimits.safe_defaults(),
            fetch_fn=fetch_fn,
            runtime_factory=runtime_factory,
            parent_id="run_1",
            # 이 파일은 DA 도구 셋만 본다. 코딩 도구는
            # `test_code_research_coding_tools.py` 가 본다.
            command_limits=None,
        )
    finally:
        module.open_research_session = real_open  # type: ignore[assignment]
    return result, provider, seen


@pytest.mark.asyncio
async def test_a_submitted_turn_becomes_a_worker_result(tmp_path) -> None:
    ledger = _FakeLedger()

    result, _, _ = await _run(
        tmp_path, ledger=ledger, calls=[("submit.v1", _SUBMISSION)]
    )

    assert result.question_id == "q_1"
    assert result.status == "completed"
    assert [claim.text for claim in result.claims] == ["런던은 2026년에 비가 왔다"]
    assert result.self_assessment == 0.8
    assert [s.text for s in result.proposed_subquestions] == ["파리는?"]
    assert result.dead_ends == ["기상청 API 는 2020 년까지"]


@pytest.mark.asyncio
async def test_the_result_carries_no_blobs(tmp_path) -> None:
    """이미 건별로 커밋했다. 또 실으면 같은 blob 이 두 경로로 흐른다."""
    ledger = _FakeLedger()

    result, _, _ = await _run(
        tmp_path,
        ledger=ledger,
        calls=[
            ("fetch.v1", {"url": "https://example.com/doc"}),
            ("submit.v1", _SUBMISSION),
        ],
    )

    # fetch 는 원장에 닿았다...
    assert [b.content_hash for b in ledger.committed] == ["abc123def456ffff"]
    # ...그리고 결과에는 실리지 않는다.
    assert result.blobs == []


@pytest.mark.asyncio
async def test_a_turn_that_never_submitted_is_partial_with_a_reason(
    tmp_path,
) -> None:
    """계약 §3.4: 조용한 degrade 금지."""
    ledger = _FakeLedger()

    result, _, _ = await _run(tmp_path, ledger=ledger, calls=[])

    assert result.status == "partial"
    assert result.fail_reason == "submit_not_called"
    assert result.claims == []


@pytest.mark.asyncio
async def test_a_continuing_turn_is_partial_and_keeps_its_pointers(
    tmp_path,
) -> None:
    ledger = _FakeLedger()

    result, _, _ = await _run(
        tmp_path,
        ledger=ledger,
        outcome=_Outcome(kind=StepKind.CONTINUING),
    )

    assert result.status == "partial"
    assert result.subagent_run_id == "sa_research_1"
    assert result.subagent_checkpoint_id == "cp_1"
    assert result.subagent_step_kind == StepKind.CONTINUING.value
    assert result.tokens_spent == 120


@pytest.mark.asyncio
async def test_a_finished_turn_destroys_its_sandbox(tmp_path) -> None:
    ledger = _FakeLedger()

    _, provider, seen = await _run(
        tmp_path, ledger=ledger, calls=[("submit.v1", _SUBMISSION)]
    )

    with pytest.raises(SandboxNotFound):
        await provider.get(seen["sandbox_id"])


@pytest.mark.asyncio
async def test_a_child_that_explodes_still_destroys_its_sandbox(tmp_path) -> None:
    """여기서 안 닫으면 아무도 안 닫는다."""
    ledger = _FakeLedger()

    result, provider, seen = await _run(tmp_path, ledger=ledger, boom=True)

    assert result.status == "failed"
    assert "child exploded" in result.fail_reason
    with pytest.raises(SandboxNotFound):
        await provider.get(seen["sandbox_id"])


@pytest.mark.asyncio
async def test_the_child_runs_under_the_research_spec(tmp_path) -> None:
    """explore 가 아니다 -- 스펙이 도구 목록을 정한다 (계약 §2)."""
    ledger = _FakeLedger()

    _, _, seen = await _run(tmp_path, ledger=ledger, calls=[("submit.v1", _SUBMISSION)])

    ticket = seen["runtime"].advanced[0]
    assert ticket.spec == "research"
    assert ticket.parent_tool_call_id == "q_1"

"""J1.5 완료 조건: `execute.v1` → 계산 클레임 → 재실행 → **verified**.

J2 의 채점기·재실행기는 착지한 날부터 초록이었지만 **합성 fixture 에서만**
그랬다 -- 스크립트가 원장에 들어오는 경로가 없어서, 실제로 워커가 쓴 계산이
verified 가 된 적이 한 번도 없었다(로드맵 S7 · S8). 이 파일은 그 사슬을 진짜
원장 위에서 끝까지 돈다.

가짜는 둘뿐이다: 자식 모델(대본대로 도구를 부른다)과 `fetch_url`(네트워크).
원장·오케스트레이터·결정론 채점기·재실행기·샌드박스(메모리 provider 의 진짜
`python3`)는 전부 진짜다.

두 라운드인 이유가 설계다(2026-09-28 결정). 계산의 `premises` 는 verified
quote 클레임의 **원장 ID** 여야 하고(계약 §5 규칙 2), 자식이 그 ID 를 보는
길은 다음 라운드의 briefing 뿐이다. 라운드 1 이 인용을 verified 로 만들고,
라운드 2 의 자식은 briefing 에서 ID 를 읽어 계산한다. 라운드 2 가 ID 를
**briefing 에서 읽는 것**이 brief 전달의 검사이기도 하다.

이 파일이 처음 빨개진 자리가 그 두 라운드였다: 질문의 샌드박스는 라운드마다
새로 열리므로 라운드 1 의 `/evidence` 가 라운드 2 에 **없었다.** 계산은 둘째
라운드부터만 쓸 수 있으니 계산이 읽을 증거는 언제나 사라진 뒤였다. 이제
`LedgerEvidenceStore.restore` 가 원장에서 다시 놓는다.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

import neos.database.models  # noqa: F401 - register Base metadata / FK targets
from neos.coding.sandbox.memory import MemorySandboxProvider
from neos.config.settings import settings
from neos.database.connection import db_manager
from neos.database.deep_analysis_models import DAClaim, DAEvent
from neos.subagent.types import StepKind
from neos.workflow.deep_analysis import orchestrator as orchestrator_module
from neos.workflow.deep_analysis.fetch import _blob_hash
from neos.workflow.deep_analysis.graders.deterministic import DeterministicGrader
from neos.workflow.deep_analysis.ledger import Ledger, create_run
from neos.workflow.deep_analysis.models import ProposedBlob
from neos.workflow.deep_analysis.orchestrator import Orchestrator
from neos.workflow.deep_analysis.reexecutor import SandboxReexecutor
from neos.workflow.deep_analysis.script_blob import is_script_blob
from neos.workflow.deep_analysis.subagent_adapter import VERIFIED_HEADER

_URL = "https://ir.example.com/2025"
_BODY = "A revenue 46\nB revenue 20\n"
_SCRIPT = (
    "import re\n"
    "text = open('evidence/{ref}.txt').read()\n"
    "a = int(re.search(r'A revenue (\\d+)', text).group(1))\n"
    "b = int(re.search(r'B revenue (\\d+)', text).group(1))\n"
    "print(a / b)\n"
)


async def _fake_fetch(url: str) -> ProposedBlob:
    return ProposedBlob(_blob_hash(_BODY, url, 200), url, 200, _BODY)


class _ScriptedChild:
    """자식 모델 자리. 라운드마다 대본 하나, 도구는 **진짜 포트**로 부른다."""

    def __init__(self) -> None:
        self.rounds = 0
        self.tickets: list[Any] = []
        self.results: list[dict] = []

    def factory(self, port):
        child = self

        class _Runtime:
            async def advance(self, ticket):
                child.tickets.append(ticket)
                child.rounds += 1
                if child.rounds == 1:
                    await child._quote_round(port)
                else:
                    await child._compute_round(port, ticket)
                return SimpleNamespace(
                    kind=StepKind.COMPLETED,
                    run_id=f"sa_{child.rounds}",
                    checkpoint_id=f"cp_{child.rounds}",
                    tokens_delta=10,
                )

        return _Runtime()

    async def _quote_round(self, port) -> None:
        fetched = await port.execute("fetch.v1", {"url": _URL})
        ref = fetched["raw_ref"]
        await port.execute(
            "submit.v1",
            {
                # partial: 질문을 열어 둬 라운드 2 가 오게 한다.
                "status": "partial",
                "self_assessment": 0.1,
                "claims": [
                    {
                        "kind": "quote",
                        "text": f"A 의 2025 매출은 {n} 이다" if n == 46 else f"B 의 2025 매출은 {n} 이다",
                        "confidence": 0.4,
                        "evidence": [
                            {"source_url": _URL, "excerpt": excerpt, "raw_ref": ref}
                        ],
                    }
                    for n, excerpt in ((46, "A revenue 46"), (20, "B revenue 20"))
                ],
            },
        )

    async def _compute_round(self, port, ticket) -> None:
        # ID 는 briefing 에서만 온다. 여기서 원장을 읽으면 brief 전달을
        # 검사하지 못한다.
        lines = ticket.briefing.why.split("\n")
        assert lines[0] == VERIFIED_HEADER
        premises = [line.split(" | ", 1)[0] for line in lines[1:]]
        ref = _blob_hash(_BODY, _URL, 200)

        wrote = await port.execute(
            "write_file.v1",
            {"path": "calc.py", "content": _SCRIPT.replace("{ref}", ref)},
        )
        assert "error" not in wrote, wrote
        ran = await port.execute("execute.v1", {"argv": ["python3", "calc.py"]})
        self.results.append(ran)
        await port.execute(
            "submit.v1",
            {
                "status": "completed",
                "self_assessment": 0.9,
                "claims": [
                    {
                        "kind": "computed",
                        "text": "A 의 2025 매출은 B 의 2.3배다",
                        "confidence": 0.4,
                        "computation": {
                            "script_ref": ran["script_ref"],
                            "inputs": [ref],
                            "premises": premises,
                            "runtime": {"profile": "research-offline-v1"},
                            "output_digest": ran["output_digest"],
                            "claimed_value": "2.3",
                        },
                    }
                ],
            },
        )


async def _claims(session, run_id) -> list[DAClaim]:
    rows = await session.execute(select(DAClaim).where(DAClaim.run_id == run_id))
    return list(rows.scalars())


async def _events(session, run_id, kind) -> list[dict]:
    rows = await session.execute(
        select(DAEvent.payload).where(DAEvent.run_id == run_id, DAEvent.kind == kind)
    )
    return [json.loads(payload) for payload in rows.scalars()]


@pytest.mark.asyncio
async def test_a_script_the_child_ran_becomes_a_verified_claim(
    monkeypatch, tmp_path
) -> None:
    """The J1.5 completion condition, on the real ledger.

    Mutation: drop the coding surface -> round 2's `write_file.v1` is
    `tool_not_allowed`. Mutation: skip `commit_script` -> rule 1
    (`E_COMPUTE_INPUT_UNFETCHED`). Mutation: drop IDs from the briefing ->
    no premises, rule 2. Mutation: skip `store.restore` -> round 2's sandbox
    has no `/evidence` and the script dies (this test found that gap).
    """
    config = settings.config.deep_analysis
    monkeypatch.setattr(config, "code_research_enabled", True)
    monkeypatch.setattr(orchestrator_module, "fetch_url", _fake_fetch)
    child = _ScriptedChild()

    async with await db_manager.get_session() as session:
        run_id = await create_run(session, "A 와 B 중 어느 쪽 매출이 큰가", "dev")
        ledger = Ledger(session, run_id)
        grader = DeterministicGrader(
            ledger,
            quote_threshold=config.quote_match_threshold,
            confidence_cap=config.confidence_cap,
            reexecutor=SandboxReexecutor(
                ledger,
                MemorySandboxProvider(root=tmp_path / "reexec"),
                cpu_sec=10.0,
                memory_mb=512,
                stdout_bytes=64 * 1024,
            ),
        )
        orch = Orchestrator(
            session,
            run_id,
            worker_factory=lambda: None,
            grader=grader,
            ledger=ledger,
            decompose_fn=lambda _root: [],
            global_token_cap=50_000,
            sandbox_provider=MemorySandboxProvider(root=tmp_path / "worker"),
            research_runtime_factory=child.factory,
        )
        await orch._install_token_budget()
        await orch._ensure_root("A 와 B 중 어느 쪽 매출이 큰가")

        assert await orch._run_round() is True
        assert await orch._run_round() is True

        claims = {claim.text: claim for claim in await _claims(session, run_id)}
        computed = claims["A 의 2025 매출은 B 의 2.3배다"]
        [ran] = child.results
        script_row = await ledger.get_blob(ran["script_ref"])
        denied = await _events(session, run_id, "code_tool_denied")
        reexecuted = await _events(session, run_id, "compute_reexecuted")
        executed = await _events(session, run_id, "script_executed")

    assert ran["stdout"] == "2.3", ran
    assert computed.kind == "computed"
    assert computed.status == "verified", computed
    # 전제 둘 다 verified quote 이고, 계산은 그 ID 를 가리킨다.
    assert {
        claims["A 의 2025 매출은 46 이다"].status,
        claims["B 의 2025 매출은 20 이다"].status,
    } == {"verified"}
    # 스크립트는 원장에 있고, 원문이 아니라고 표시돼 있다.
    assert script_row is not None and is_script_blob(script_row)
    assert reexecuted, "the grader must have re-run the script"
    assert denied == []
    # S8: the run that produced the claim is on the ledger with the same
    # digest the claim carries, and the evidence it could read.
    [run] = executed
    assert run["script_ref"] == ran["script_ref"]
    assert run["output_digest"] == ran["output_digest"]
    assert run["evidence_refs"] == [_blob_hash(_BODY, _URL, 200)]

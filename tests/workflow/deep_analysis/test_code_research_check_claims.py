"""`check_claims.v1` — 채점기를 읽기 전용으로 (계약 §3.3).

워커의 비용 절감 도구다. **판정은 여전히 오케스트레이터가 다시 한다** --
워커가 초록을 봤다는 사실은 증거가 아니다. 그래서 이 도구는 원장에 쓰지
않고, 결과도 원장에 남기지 않는다.

**계산 클레임은 여기서 판별하지 않는다.** 계약은 "계산 클레임은 재실행까지
한다" 고 적지만 재실행은 J2 다. 지금 계산 클레임을 현재 결정론 채점기에
넘기면 quote 규칙이 돌아 `E_NO_EVIDENCE` 가 나온다 -- 증거가 `computation`
에 있는데 "근거 없음" 이라고 **자신 있게 틀린 답**을 주는 모양이고, 판별을
못 하는 것보다 나쁘다. 그래서 §5 의 `E_*` 어휘를 쓰지 않는 도구 수준
사유로 돌려주고, J2 가 그 자리를 대체한다.

입력은 `submit.v1` 과 같은 모양이라(§3.3) 파서를 함께 쓴다 -- 둘째 방언이
생기지 않게.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

pytestmark = pytest.mark.no_db


@dataclass
class _Verdict:
    """`models.Verdict` 중 이 도구가 읽는 부분."""

    ok: bool
    code: str = ""
    detail: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


class _FakeGrader:
    """`DeterministicGrader` 자리. 원장을 만지지 않는지 여기서 본다."""

    def __init__(self, verdicts: list[_Verdict]) -> None:
        self._verdicts = list(verdicts)
        self.graded: list[Any] = []

    async def grade(self, claim) -> _Verdict:
        self.graded.append(claim)
        return self._verdicts.pop(0)


def _quote(text: str = "런던은 비가 왔다", confidence: float = 0.6) -> dict:
    return {
        "kind": "quote",
        "text": text,
        "confidence": confidence,
        "evidence": [
            {
                "source_url": "https://example.com/doc",
                "excerpt": "it rained",
                "raw_ref": "abc123def456ffff",
            }
        ],
    }


def _computed() -> dict:
    return {
        "kind": "computed",
        "text": "평균은 42.5 다",
        "confidence": 0.7,
        "computation": {
            "script_ref": "f" * 64,
            "inputs": ["abc123def456ffff"],
            "premises": ["claim_1"],
            "runtime": {"profile": "research-offline-v1", "image_digest": "sha256:x"},
            "output_digest": "e" * 64,
            "claimed_value": "42.5",
        },
    }


def _port(grader):
    from neos.workflow.deep_analysis.research_tools import ResearchToolPort

    return ResearchToolPort(
        fetch_fn=None,
        store=None,
        sandbox=None,
        cap_bytes=0,
        grader=grader,
    )


@pytest.mark.asyncio
async def test_the_tool_is_offered_under_the_contract_name() -> None:
    port = _port(_FakeGrader([]))

    assert "check_claims.v1" in {item.name for item in port.definitions()}


@pytest.mark.asyncio
async def test_a_passing_quote_claim_comes_back_ok_with_no_codes() -> None:
    grader = _FakeGrader([_Verdict(ok=True)])
    port = _port(grader)

    result = await port.execute("check_claims.v1", {"claims": [_quote()]})

    assert result["results"] == [{"index": 0, "ok": True, "codes": []}]


@pytest.mark.asyncio
async def test_a_failing_quote_claim_carries_the_graders_code() -> None:
    grader = _FakeGrader([_Verdict(ok=False, code="E_QUOTE_MISMATCH")])
    port = _port(grader)

    result = await port.execute("check_claims.v1", {"claims": [_quote()]})

    assert result["results"] == [
        {"index": 0, "ok": False, "codes": ["E_QUOTE_MISMATCH"]}
    ]


@pytest.mark.asyncio
async def test_the_index_follows_the_submitted_order() -> None:
    """워커가 어느 클레임이 걸렸는지 알아야 고칠 수 있다."""
    grader = _FakeGrader(
        [
            _Verdict(ok=True),
            _Verdict(ok=False, code="E_NO_EVIDENCE"),
            _Verdict(ok=True),
        ]
    )
    port = _port(grader)

    result = await port.execute(
        "check_claims.v1",
        {"claims": [_quote("a"), _quote("b"), _quote("c")]},
    )

    assert [row["index"] for row in result["results"]] == [0, 1, 2]
    assert [row["ok"] for row in result["results"]] == [True, False, True]


@pytest.mark.asyncio
async def test_a_computed_claim_is_not_judged_here(monkeypatch) -> None:
    """판별 못 한다고 말하지, 틀린 답을 주지 않는다.

    채점기에 **닿지도 않아야** 한다 -- 닿으면 quote 규칙이 돌아
    `E_NO_EVIDENCE` 가 나온다.
    """
    grader = _FakeGrader([])
    port = _port(grader)

    result = await port.execute("check_claims.v1", {"claims": [_computed()]})

    row = result["results"][0]
    assert row["ok"] is False
    assert row["codes"] == ["compute_check_unavailable"]
    # §5 의 채점 어휘를 더럽히지 않는다.
    assert not row["codes"][0].startswith("E_")
    assert grader.graded == []


@pytest.mark.asyncio
async def test_a_mixed_batch_keeps_both_kinds_in_place() -> None:
    grader = _FakeGrader([_Verdict(ok=True)])
    port = _port(grader)

    result = await port.execute("check_claims.v1", {"claims": [_computed(), _quote()]})

    assert result["results"][0]["codes"] == ["compute_check_unavailable"]
    assert result["results"][1] == {"index": 1, "ok": True, "codes": []}
    assert len(grader.graded) == 1


@pytest.mark.asyncio
async def test_checking_does_not_record_a_submission() -> None:
    """확인은 제출이 아니다. 둘을 섞으면 워커가 모르는 새 제출이 생긴다."""
    port = _port(_FakeGrader([_Verdict(ok=True)]))

    await port.execute("check_claims.v1", {"claims": [_quote()]})

    assert port.submission is None


@pytest.mark.asyncio
async def test_without_a_grader_the_tool_is_not_offered() -> None:
    """도구 목록은 정직해야 한다 -- 부를 수 없는 것을 내밀지 않는다."""
    from neos.workflow.deep_analysis.research_tools import ResearchToolPort

    port = ResearchToolPort(
        fetch_fn=None, store=None, sandbox=None, cap_bytes=0, grader=None
    )

    assert "check_claims.v1" not in {item.name for item in port.definitions()}

    result = await port.execute("check_claims.v1", {"claims": [_quote()]})
    assert result["error"] == "tool_not_allowed"

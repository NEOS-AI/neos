"""계산 클레임 채점 (계약 §4 · §5).

quote 클레임은 "원문에 그 문장이 있는가" 를 본다. 계산 클레임은 **다시
돌려서 같은 답이 나오는가** 를 본다. 그래서 규칙이 다섯이고, 계약은 그것을
**순서대로 평가하고 첫 실패에서 멈추라**고 적는다 -- 순서가 진단의 품질이다.
입력이 원장에 없는데 "재현 안 됨" 이라고 답하면 고칠 곳을 잘못 짚는다.

**정규화는 최소한이다.** 줄 끝 `\\r\\n`→`\\n`, 끝 공백 제거. 그 외는 건드리지
않는다 -- 숫자 반올림을 정규화에 넣는 순간 채점기가 "비슷하면 같다" 를
판정하게 되고, 그것은 재현성 검사가 아니다.

재실행기는 **주입**한다. 진짜 재실행은 샌드박스를 요구하지만(J2b), 규칙
자체는 그것 없이 전부 고정할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from neos.workflow.deep_analysis.models import ComputedEvidence, ProposedClaim

pytestmark = pytest.mark.no_db

_DIGEST = "e" * 64
_OTHER_DIGEST = "d" * 64


@dataclass
class _Blob:
    http_status: int = 200
    raw_text: str = "body"


@dataclass
class _Claim:
    id: str
    status: str = "verified"


@dataclass
class _Reexecution:
    """한 번 돌린 결과.

    한도 초과(계약 §5 의 **별도 이벤트**)는 여기 없다 -- 그 이벤트가 생기는
    J2b 에서 같이 들어온다. 구현하지 않을 것을 가짜에 미리 그려 두면 이미
    지원하는 것처럼 보인다.
    """

    digest: str
    stdout: str


class _FakeReexecutor:
    def __init__(self, runs: list[_Reexecution]) -> None:
        self._runs = list(runs)
        self.calls: list[Any] = []

    async def run(self, computation) -> _Reexecution:
        self.calls.append(computation)
        return self._runs.pop(0)


class _FakeLedger:
    def __init__(
        self,
        *,
        blobs: frozenset[str] = frozenset({"aaaaaaaaaaaaaaaa", "f" * 64}),
        claims: dict[str, _Claim] | None = None,
        sources: dict[str, list[str]] | None = None,
    ) -> None:
        self._blobs = set(blobs)
        self._claims = claims if claims is not None else {"c1": _Claim("c1")}
        self._sources = sources if sources is not None else {"c1": ["https://a"]}

    async def get_blob(self, content_hash: str):
        return _Blob() if content_hash in self._blobs else None

    async def get_claim(self, claim_id: str):
        return self._claims.get(claim_id)

    async def claim_source_urls(self, claim_id: str) -> list[str]:
        return list(self._sources.get(claim_id, []))


def _computation(**overrides) -> ComputedEvidence:
    values: dict[str, Any] = {
        "script_ref": "f" * 64,
        "inputs": ["aaaaaaaaaaaaaaaa"],
        "premises": ["c1"],
        "runtime": {
            "profile": "research-offline-v1",
            "image_digest": "sha256:x",
        },
        "output_digest": _DIGEST,
        "claimed_value": "42.5",
    }
    values.update(overrides)
    return ComputedEvidence(**values)


def _claim(confidence: float = 0.5, **overrides) -> ProposedClaim:
    return ProposedClaim(
        text="평균은 42.5 다",
        confidence=confidence,
        kind="computed",
        computation=_computation(**overrides),
    )


def _twice(digest: str = _DIGEST, stdout: str = "평균: 42.5\n") -> list:
    return [
        _Reexecution(digest=digest, stdout=stdout),
        _Reexecution(digest=digest, stdout=stdout),
    ]


async def _grade(claim, *, ledger=None, runs=None, reexecutor=None):
    from neos.workflow.deep_analysis.graders.computed import grade_computed

    return await grade_computed(
        claim,
        ledger=ledger or _FakeLedger(),
        confidence_cap={1: 0.6, 2: 0.8, 3: 0.95},
        reexecutor=(
            reexecutor
            if reexecutor is not None
            else _FakeReexecutor(runs if runs is not None else _twice())
        ),
    )


# ---- 정규화 ------------------------------------------------------------------


def test_normalization_touches_line_endings_and_trailing_space_only() -> None:
    from neos.workflow.deep_analysis.graders.computed import normalize_stdout

    assert normalize_stdout("a\r\nb\r\n") == "a\nb"
    assert normalize_stdout("value: 42.50   \n\n") == "value: 42.50"
    # 내부 공백은 그대로다.
    assert normalize_stdout("a  b") == "a  b"


def test_normalization_does_not_round_numbers() -> None:
    """반올림을 넣으면 채점기가 "비슷하면 같다" 를 판정하게 된다."""
    from neos.workflow.deep_analysis.graders.computed import normalize_stdout

    assert normalize_stdout("42.500000\n") == "42.500000"


# ---- 규칙 (계약 §5, 순서대로) -------------------------------------------------


@pytest.mark.asyncio
async def test_an_input_that_is_not_a_ledger_blob_is_refused() -> None:
    verdict = await _grade(_claim(inputs=["aaaaaaaaaaaaaaaa", "zzzzzzzzzzzzzzzz"]))

    assert verdict.ok is False
    assert verdict.code == "E_COMPUTE_INPUT_UNFETCHED"


@pytest.mark.asyncio
async def test_a_script_that_is_not_a_ledger_blob_is_refused() -> None:
    """스크립트도 재실행의 재료다 (계약 §4: "blob 저장소의 스크립트 바이트").

    §5 의 규칙 1 은 문자 그대로는 `inputs` 만 말하지만, 원장에 없는 스크립트를
    통과시키면 재실행 단계에서 **돌리지도 못한 것에 판정을 붙이게 된다** --
    "재현 안 됨" 은 돌려 보고 다른 답이 나왔다는 뜻이어야 한다. 같은 규칙,
    같은 코드로 막는다: 재실행이 필요로 하는 바이트가 원장에 없다.
    """
    verdict = await _grade(_claim(script_ref="z" * 64))

    assert verdict.ok is False
    assert verdict.code == "E_COMPUTE_INPUT_UNFETCHED"


@pytest.mark.asyncio
async def test_a_missing_script_never_reaches_re_execution() -> None:
    """규칙 1 의 자리이므로 샌드박스는 돌지 않는다."""
    reexecutor = _FakeReexecutor(_twice())

    await _grade(_claim(script_ref="z" * 64), reexecutor=reexecutor)

    assert reexecutor.calls == []


@pytest.mark.asyncio
async def test_a_premise_that_is_not_verified_is_refused() -> None:
    ledger = _FakeLedger(claims={"c1": _Claim("c1", status="pending")})

    verdict = await _grade(_claim(), ledger=ledger)

    assert verdict.ok is False
    assert verdict.code == "E_COMPUTE_PREMISE_UNVERIFIED"


@pytest.mark.asyncio
async def test_a_missing_premise_is_refused_the_same_way() -> None:
    ledger = _FakeLedger(claims={})

    verdict = await _grade(_claim(), ledger=ledger)

    assert verdict.ok is False
    assert verdict.code == "E_COMPUTE_PREMISE_UNVERIFIED"


@pytest.mark.asyncio
async def test_two_runs_that_disagree_are_nondeterministic() -> None:
    runs = [
        _Reexecution(digest=_DIGEST, stdout="42.5"),
        _Reexecution(digest=_OTHER_DIGEST, stdout="42.6"),
    ]

    verdict = await _grade(_claim(), runs=runs)

    assert verdict.ok is False
    assert verdict.code == "E_COMPUTE_NONDETERMINISTIC"


@pytest.mark.asyncio
async def test_a_stable_result_that_differs_from_the_claim_is_not_reproduced() -> None:
    """두 번 다 같지만 제출된 digest 와 다르다 -- 재현 실패다."""
    verdict = await _grade(_claim(), runs=_twice(digest=_OTHER_DIGEST))

    assert verdict.ok is False
    assert verdict.code == "E_COMPUTE_NOT_REPRODUCED"


@pytest.mark.asyncio
async def test_a_value_absent_from_stdout_is_a_mismatch() -> None:
    verdict = await _grade(_claim(), runs=_twice(stdout="평균: 41.0\n"))

    assert verdict.ok is False
    assert verdict.code == "E_COMPUTE_VALUE_MISMATCH"


@pytest.mark.asyncio
async def test_confidence_is_capped_by_the_weakest_premise() -> None:
    """상한은 premises 상한의 **최소값**이다 (계약 §5).

    전제 하나가 출처 하나짜리면 그 위에 세운 계산도 그만큼만 강하다.
    """
    ledger = _FakeLedger(
        claims={"c1": _Claim("c1"), "c2": _Claim("c2")},
        sources={"c1": ["https://a", "https://b", "https://c"], "c2": ["https://d"]},
    )

    verdict = await _grade(_claim(confidence=0.9, premises=["c1", "c2"]), ledger=ledger)

    assert verdict.ok is False
    assert verdict.code == "E_CONFIDENCE_INFLATED"


@pytest.mark.asyncio
async def test_a_reproduced_computation_passes() -> None:
    verdict = await _grade(_claim(confidence=0.5))

    assert verdict.ok is True
    assert verdict.code == ""


# ---- 순서 --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_first_failing_rule_wins() -> None:
    """입력이 없는데 "재현 안 됨" 이라고 답하면 고칠 곳을 잘못 짚는다.

    입력·전제가 **둘 다** 틀렸고 재실행도 어긋나지만, 나오는 것은 첫 규칙이다.
    """
    ledger = _FakeLedger(
        blobs=frozenset(), claims={"c1": _Claim("c1", status="rejected")}
    )

    verdict = await _grade(_claim(), ledger=ledger, runs=_twice(digest=_OTHER_DIGEST))

    assert verdict.code == "E_COMPUTE_INPUT_UNFETCHED"


@pytest.mark.asyncio
async def test_a_refused_claim_never_reaches_re_execution() -> None:
    """재실행은 샌드박스를 돌리는 일이다. 질 것이 뻔한 클레임에 쓰지 않는다."""
    ledger = _FakeLedger(blobs=frozenset())
    reexecutor = _FakeReexecutor(_twice())

    await _grade(_claim(), ledger=ledger, reexecutor=reexecutor)

    assert reexecutor.calls == []


@pytest.mark.asyncio
async def test_a_computed_claim_with_no_computation_has_no_evidence() -> None:
    """`parse_claims` 가 실제로 만들 수 있는 모양이다.

    `computation` 이 Mapping 이 아니면 None 이 된다 -- 그 클레임은 계산이라고
    주장하면서 계산을 싣지 않았으므로, quote 쪽의 `E_NO_EVIDENCE` 와 같은
    자리다. 새 코드를 만들지 않는다.
    """
    claim = ProposedClaim(
        text="평균은 42.5 다", confidence=0.5, kind="computed", computation=None
    )

    verdict = await _grade(claim)

    assert verdict.ok is False
    assert verdict.code == "E_NO_EVIDENCE"


@pytest.mark.asyncio
async def test_a_computation_with_no_premises_is_capped_at_zero() -> None:
    """전제가 없으면 그 위에 세운 계산도 기댈 곳이 없다."""
    verdict = await _grade(_claim(confidence=0.1, premises=[]))

    assert verdict.ok is False
    assert verdict.code == "E_CONFIDENCE_INFLATED"


@pytest.mark.asyncio
async def test_a_computed_claim_without_a_reexecutor_is_a_wiring_error() -> None:
    """조용히 통과시키지 않는다 -- 판정할 수 없으면 터뜨린다.

    프로덕션에서는 일어날 수 없다: 계산 클레임을 만드는 analyze 스펙이
    `specs_enabled` 에 없다. 그래서 런타임 degrade 가 아니라 배선 실수다.
    """
    from neos.workflow.deep_analysis.graders.computed import grade_computed

    with pytest.raises(ValueError, match="reexecutor"):
        await grade_computed(
            _claim(),
            ledger=_FakeLedger(),
            confidence_cap={1: 0.6, 2: 0.8, 3: 0.95},
            reexecutor=None,
        )

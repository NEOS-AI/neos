"""계산 클레임 채점 (계약 §4 · §5).

quote 클레임은 "원문에 그 문장이 있는가" 를 본다. 계산 클레임은 **다시 돌려서
같은 답이 나오는가** 를 본다.

계약은 규칙을 **순서대로 평가하고 첫 실패에서 멈추라**고 적는다. 그 순서가
진단의 품질이다 -- 입력이 원장에 없는데 "재현 안 됨" 이라고 답하면 고칠 곳을
잘못 짚게 되고, 무엇보다 **질 것이 뻔한 클레임에 샌드박스를 돌리게 된다.**

이 모듈은 네트워크도 샌드박스도 모른다. 재실행은 주입받는다.
"""

from __future__ import annotations

from typing import Any

from ..models import ProposedClaim, Verdict


def normalize_stdout(value: str) -> str:
    """계약 §4의 정규화. 줄 끝과 끝 공백만 만진다.

    **그 외는 건드리지 않는다.** 숫자 반올림을 여기 넣는 순간 채점기가
    "비슷하면 같다" 를 판정하게 되고, 그것은 재현성 검사가 아니다.
    """
    return value.replace("\r\n", "\n").rstrip()


def _confidence_limit(source_count: int, caps: dict[int, float]) -> float:
    if source_count == 0:
        return 0.0
    return caps[3 if source_count >= 3 else source_count]


def _rejected(code: str, detail: str, diagnostics: dict[str, Any]) -> Verdict:
    diagnostics["deterministic_code"] = code
    return Verdict(ok=False, code=code, detail=detail, diagnostics=diagnostics)


async def grade_computed(
    claim: ProposedClaim,
    *,
    ledger: Any,
    confidence_cap: dict[int, float],
    reexecutor: Any,
) -> Verdict:
    """계약 §5의 계산 클레임 규칙. 첫 실패에서 멈춘다."""
    if reexecutor is None:
        # 조용히 통과시키지 않는다. 프로덕션에서는 일어날 수 없다 --
        # 계산 클레임을 만드는 analyze 스펙이 `specs_enabled` 에 없다.
        raise ValueError("computed claims need a reexecutor")

    diagnostics: dict[str, Any] = {
        "deterministic": "rejected",
        "deterministic_code": "",
        "reexecuted": False,
    }

    computation = claim.computation
    if computation is None:
        # 계산이라고 주장하면서 계산을 싣지 않았다. quote 쪽의 같은 자리를
        # 쓴다 -- 새 코드를 만들 이유가 없다.
        return _rejected(
            "E_NO_EVIDENCE", "computed claim carries no computation", diagnostics
        )

    diagnostics.update(
        input_count=len(computation.inputs),
        premise_count=len(computation.premises),
    )

    # 1. 입력은 전부 원장의 blob 이어야 한다.
    for raw_ref in computation.inputs:
        if await ledger.get_blob(raw_ref) is None:
            return _rejected(
                "E_COMPUTE_INPUT_UNFETCHED",
                f"input {raw_ref} is not a ledger blob",
                diagnostics,
            )

    # 2. 전제는 전부 verified 여야 한다.
    #
    # 계약은 "verified **quote** 클레임" 이라고 적지만 `DAClaim` 에는 아직
    # kind 컬럼이 없다. 지금은 계산 클레임을 저장할 수 없으므로 저장된 것은
    # 전부 quote 이고, 이 검사는 그 사이 정확하다. 컬럼이 생기는 커밋에서
    # kind 검사를 여기 더한다.
    for claim_id in computation.premises:
        premise = await ledger.get_claim(claim_id)
        if premise is None or premise.status != "verified":
            return _rejected(
                "E_COMPUTE_PREMISE_UNVERIFIED",
                f"premise {claim_id} is not a verified claim",
                diagnostics,
            )

    # 3~4. 두 번 돌린다. 먼저 서로 같은지, 그 다음 제출된 digest 와 같은지.
    first = await reexecutor.run(computation)
    second = await reexecutor.run(computation)
    diagnostics["reexecuted"] = True
    if first.digest != second.digest:
        return _rejected(
            "E_COMPUTE_NONDETERMINISTIC",
            "two runs produced different digests",
            diagnostics,
        )
    if first.digest != computation.output_digest:
        return _rejected(
            "E_COMPUTE_NOT_REPRODUCED",
            "re-execution digest does not match the submitted one",
            diagnostics,
        )

    # 5. 주장한 값이 정규화된 stdout 에 **문자 그대로** 있어야 한다.
    if computation.claimed_value not in normalize_stdout(first.stdout):
        return _rejected(
            "E_COMPUTE_VALUE_MISMATCH",
            f"{computation.claimed_value!r} is not in the output",
            diagnostics,
        )

    # 6. 상한은 전제들 상한의 **최소값**이다. 전제 하나가 출처 하나짜리면
    #    그 위에 세운 계산도 그만큼만 강하다. 전제가 없으면 기댈 곳이 없다.
    limits = [
        _confidence_limit(len(await ledger.claim_source_urls(claim_id)), confidence_cap)
        for claim_id in computation.premises
    ]
    limit = min(limits) if limits else 0.0
    diagnostics["premise_confidence_limit"] = limit
    if claim.confidence > limit:
        return _rejected(
            "E_CONFIDENCE_INFLATED",
            f"{claim.confidence} exceeds premise cap {limit}",
            diagnostics,
        )

    diagnostics["deterministic"] = "passed"
    return Verdict(ok=True, diagnostics=diagnostics)

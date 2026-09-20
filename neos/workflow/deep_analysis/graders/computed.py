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


def _capped(limit: str, diagnostics: dict[str, Any]) -> Verdict:
    """한도에 걸린 재실행 (계약 §5).

    `E_COMPUTE_NOT_REPRODUCED` 를 쓰지 않는 이유는 회계가 아니라 **수선
    지시**다. 그 코드는 `DAFeedback` 을 거쳐 워커에게 돌아가고, 워커는 그것을
    읽고 무엇을 고칠지 고른다 -- "결정론을 고쳐라" 와 "계산을 줄여라" 는 다른
    작업이다. 한도 초과에 재현 실패 코드를 붙이면 워커는 고칠 수 없는 것을
    고치러 간다.

    계약의 코드 표에는 없다. §5 가 "비용 문제와 재현성 문제를 섞지 않는다" 고
    적으면서 별도 **이벤트**만 정했고, 판정에 쓸 코드는 정하지 않았다 --
    같은 원칙을 코드에도 적용한 자리다(2026-09-20).
    """
    diagnostics["reexec_capped"] = limit
    return _rejected(
        "E_COMPUTE_CAPPED",
        f"re-execution crossed the {limit} limit",
        diagnostics,
    )


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
        # 이 셋이 계약 §6 의 두 이벤트 원료다. 이벤트를 여기서 내지 않는
        # 이유는 claim_id 다 -- `ProposedClaim` 은 아직 행이 아니라 id 가
        # 없고, id 는 판정을 적용하는 `Ledger._apply_verdict` 에만 있다.
        #
        # `reexecuted` 와 `reexec_matched` 를 나누는 이유: 돌리지 않은 것과
        # 돌렸는데 어긋난 것은 다른 사건이다. `matched=False` 하나로 뭉치면
        # 규칙 1 에서 막힌 클레임이 원장에 "재현 실패" 로 남는다.
        "reexecuted": False,
        "reexec_matched": None,
        "reexec_capped": "",
        "reexec_duration_sec": 0.0,
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

    # 1. 재실행이 필요로 하는 바이트는 전부 원장에 있어야 한다.
    #
    # 계약 §5 의 규칙 1 은 문자 그대로는 `inputs` 만 말하지만, §4 가
    # `script_ref` 를 "blob 저장소의 스크립트 바이트" 로 적는다. 스크립트를
    # 여기서 막지 않으면 재실행 단계가 **돌리지도 못한 것에 판정을 붙인다**
    # -- `E_COMPUTE_NOT_REPRODUCED` 는 돌려 보고 다른 답이 나왔다는 뜻이어야
    # 한다. 같은 규칙이므로 같은 코드를 쓴다: 새 어휘를 만들지 않는다.
    if await ledger.get_blob(computation.script_ref) is None:
        return _rejected(
            "E_COMPUTE_INPUT_UNFETCHED",
            f"script {computation.script_ref} is not a ledger blob",
            diagnostics,
        )
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
    #
    # 한도에 걸린 실행은 **답을 내지 못한 것**이라 비교에 넣지 않는다. 넣으면
    # 빈 digest 가 "다른 digest" 로 읽혀 멀쩡한 계산이 비결정적이라는 낙인을
    # 받는다. 계약 §5: 비용 문제와 재현성 문제를 섞지 않는다.
    first = await reexecutor.run(computation)
    diagnostics["reexecuted"] = True
    diagnostics["reexec_duration_sec"] = float(first.duration_sec)
    if first.capped:
        # 둘째는 돌리지 않는다 -- 같은 스크립트가 같은 한도에 다시 걸릴
        # 뿐이고, 샌드박스는 비싸다.
        return _capped(first.capped, diagnostics)

    second = await reexecutor.run(computation)
    diagnostics["reexec_duration_sec"] += float(second.duration_sec)
    if second.capped:
        return _capped(second.capped, diagnostics)

    # 재현은 **두 실행이 서로 같고, 그것이 제출된 digest 와 같을 때**다.
    # 첫 실행만 맞춰 보면 비결정적인 계산이 절반의 확률로 초록을 받는다.
    diagnostics["reexec_matched"] = (
        first.digest == second.digest == computation.output_digest
    )
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

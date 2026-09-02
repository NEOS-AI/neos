"""Pure metrics for the entailment discard-recall measurement.

No database, no network, no LLM. The caller supplies decoded event payloads
and grading outcomes; this module only reconstructs claims and does
arithmetic.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from .models import ProposedClaim, ProposedEvidence
from .text_norm import claim_hash

_EVIDENCE_FIELDS = ("source_url", "excerpt", "raw_ref")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def claim_from_event(payload: Any) -> ProposedClaim | None:
    """Rebuild a claim from a ``claim_discarded`` payload, or None if malformed."""
    if not isinstance(payload, dict):
        return None

    text = payload.get("text")
    confidence = payload.get("confidence")
    raw_evidence = payload.get("evidence")
    if not isinstance(text, str) or not text.strip():
        return None
    if not _is_number(confidence):
        return None
    if not isinstance(raw_evidence, list):
        return None

    evidence: list[ProposedEvidence] = []
    for item in raw_evidence:
        if not isinstance(item, dict):
            return None
        if any(not isinstance(item.get(f), str) for f in _EVIDENCE_FIELDS):
            return None
        evidence.append(
            ProposedEvidence(
                source_url=item["source_url"],
                excerpt=item["excerpt"],
                raw_ref=item["raw_ref"],
            )
        )

    return ProposedClaim(
        text=text,
        confidence=float(confidence),
        evidence=evidence,
    )


def value_est_from_event(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    value_est = payload.get("value_est")
    return float(value_est) if _is_number(value_est) else None


def wilson_interval(
    successes: int,
    total: int,
    z: float,
) -> tuple[float, float]:
    """Wilson score interval, clamped to [0, 1]. Empty denominator -> (0, 0)."""
    if total <= 0:
        return (0.0, 0.0)
    proportion = successes / total
    denominator = 1.0 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def false_discard_rate(verified: int, total: int) -> float:
    """Share of discarded claims the graders would have verified."""
    return verified / total if total else 0.0


def stopping_verdict(
    low: float,
    high: float,
    *,
    safe_upper: float,
    over_discard_lower: float,
) -> str:
    """Apply the pre-registered stopping rule to a Wilson interval.

    Fixed before data collection. Do not tune after seeing a result.
    """
    if high < safe_upper:
        return "safe"
    if low > over_discard_lower:
        return "over_discarding"
    return "inconclusive"


async def score_discards(
    events: list[Any],
    *,
    grade_fn,
    wilson_z: float,
    safe_upper: float,
    over_discard_lower: float,
    kept_hashes: frozenset[str] | set[str] = frozenset(),
) -> dict[str, Any]:
    """Grade every distinct discarded claim and summarise the recall loss.

    ``grade_fn(claim, value_est)`` must return True when the graders would
    have verified the claim. Every surviving claim is graded — the agentic
    sampling gate is deliberately bypassed so the denominator stays exact.

    The unit of measurement is a **distinct claim**, not an event. A question
    that returns to ``open`` is re-investigated, entailment re-runs, and the
    same claim can be discarded again — so one claim can emit several
    ``claim_discarded`` events within a run. Grading every event would weight
    that claim by its replicate count and shrink the Wilson interval with
    non-independent observations. Two collapses therefore run before grading:

    1. Payloads are deduped by ``claim_hash(text)`` — the same run-scoped
       identity the ledger merges committed claims on (``ledger._upsert_claim``).
    2. Any hash in ``kept_hashes`` (claims that reached ``deep_analysis_claims``
       for this run) is dropped. Entailment kept that claim on some other pass,
       so the pipeline never lost it and it is not recall loss.

    ``raw_events``/``distinct_claims``/``kept_elsewhere`` are reported so the
    collapse from events to the graded denominator stays auditable.
    """
    verified = 0
    malformed = 0
    kept_elsewhere = 0
    seen: set[str] = set()
    gradable: list[tuple[ProposedClaim, float]] = []
    for payload in events:
        claim = claim_from_event(payload)
        value_est = value_est_from_event(payload)
        if claim is None or value_est is None:
            malformed += 1
            continue
        digest = claim_hash(claim.text)
        if digest in seen:
            continue
        seen.add(digest)
        if digest in kept_hashes:
            kept_elsewhere += 1
            continue
        gradable.append((claim, value_est))

    total = len(gradable)
    for claim, value_est in gradable:
        if await grade_fn(claim, value_est):
            verified += 1

    low, high = wilson_interval(verified, total, wilson_z)
    # A zero-total interval degenerates to (0.0, 0.0), which would read as
    # "safe" under the pre-registered rule despite there being no data to
    # support that conclusion. Treat the no-data case as inconclusive
    # explicitly rather than let the degenerate interval imply safety.
    verdict = (
        "inconclusive"
        if total == 0
        else stopping_verdict(
            low,
            high,
            safe_upper=safe_upper,
            over_discard_lower=over_discard_lower,
        )
    )
    return {
        "total_discarded": total,
        "verified": verified,
        "malformed": malformed,
        "raw_events": len(events),
        "distinct_claims": len(seen),
        "kept_elsewhere": kept_elsewhere,
        "false_discard_rate": false_discard_rate(verified, total),
        "wilson_low": low,
        "wilson_high": high,
        "verdict": verdict,
    }


# --- 누적 (C1) ---------------------------------------------------------------
#
# 사전 등록된 정지 규칙은 verified 0 일 때 n >= 35 부터만 `safe` 를 낼 수 있다
# (`DeepAnalysisDiscardRecallConfig` 독스트링의 산술). 5+1 런 하나는 distinct
# discard 를 16개 안팎 내므로 **한 번의 채점으로는 도달할 수 없고**, 그래서
# 로드맵 §7 C1 이 "누적 설계가 선행" 이라고 적었다.
#
# 누적이 그냥 더하기가 아닌 이유는 이 문서가 표본 경계로 배운 것과 같다:
# 판정자를 바꾸면(E3) 같은 클레임이 다른 판정을 받고, 그 둘을 한 분모에 담으면
# n 은 커지는데 **무엇의 n 인지**가 사라진다. 그래서 아래는 합치기 전에
# 지문을 대조하고, 어긋나면 **거부한다** -- 조용히 버리지 않는 이유는
# §8.1.2 가 적은 대로다: 버리면 사람은 그 표본이 세어졌다고 믿는다.


@dataclass(frozen=True)
class ScoringSession:
    """한 번의 채점 실행. 아티팩트 하나에 대응한다."""

    artifact: str
    fingerprint: dict[str, Any]
    run_ids: tuple[str, ...]
    total_discarded: int
    verified: int


def fingerprint_digest(fingerprint: Any) -> str:
    """지문의 안정적인 요약. 키 순서와 무관해야 한다.

    dict 의 반복 순서가 달라도 같은 구성은 같은 digest 여야 한다 -- 안 그러면
    합칠 수 있는 세션이 순서 때문에 거부된다.
    """
    canonical = json.dumps(fingerprint, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def pool_sessions(
    sessions: list[ScoringSession],
    *,
    wilson_z: float,
    safe_upper: float,
    over_discard_lower: float,
) -> dict[str, Any]:
    """여러 채점 세션을 하나의 분모로 합친다 -- 합쳐도 될 때만.

    거부 사유는 둘이고, 둘 다 **이름을 갖는다**:

    ``incompatible_fingerprints``
        세션들이 서로 다른 구성에서 채점됐다. 판정자 모델·임계값·
        `agentic_sample_rate_override` 중 하나라도 다르면 같은 클레임이 다른
        판정을 받을 수 있고, 그것을 한 비율로 보고하면 그 비율은 무엇도
        서술하지 않는다.

    ``overlapping_runs``
        같은 run 이 두 세션에 들어 있다. 그 run 의 클레임이 두 번 세어지면
        분모가 부풀고 Wilson 구간이 **실제보다 좁아진다** -- 즉 `safe` 를
        근거 없이 앞당긴다. 독립 관측이 아닌 것을 독립으로 세는 것은
        `score_discards` 가 run 안에서 이미 한 번 막은 실수와 같은 종류다.

    거부는 `verdict` 로 돌려주고 예외를 던지지 않는다. 호출자는 부분 결과를
    아티팩트에 남겨야 하고, 무엇이 왜 안 합쳐졌는지가 그 아티팩트의 값어치다.
    """
    if not sessions:
        return {
            "verdict": "inconclusive",
            "sessions": 0,
            "total_discarded": 0,
            "verified": 0,
        }

    digests = {fingerprint_digest(s.fingerprint) for s in sessions}
    if len(digests) > 1:
        return {
            "verdict": "incompatible_fingerprints",
            "sessions": len(sessions),
            "digests": sorted(digests),
            "by_artifact": {
                s.artifact: fingerprint_digest(s.fingerprint)
                for s in sessions
            },
        }

    seen: dict[str, str] = {}
    overlaps: dict[str, list[str]] = {}
    for session in sessions:
        for run_id in session.run_ids:
            if run_id in seen:
                overlaps.setdefault(run_id, [seen[run_id]]).append(
                    session.artifact
                )
            else:
                seen[run_id] = session.artifact
    if overlaps:
        return {
            "verdict": "overlapping_runs",
            "sessions": len(sessions),
            "overlaps": {k: sorted(v) for k, v in sorted(overlaps.items())},
        }

    total = sum(s.total_discarded for s in sessions)
    verified = sum(s.verified for s in sessions)
    low, high = wilson_interval(verified, total, wilson_z)
    verdict = (
        "inconclusive"
        if total == 0
        else stopping_verdict(
            low,
            high,
            safe_upper=safe_upper,
            over_discard_lower=over_discard_lower,
        )
    )
    return {
        "verdict": verdict,
        "sessions": len(sessions),
        "artifacts": [s.artifact for s in sessions],
        "run_ids": sorted(seen),
        "fingerprint_digest": next(iter(digests)),
        "total_discarded": total,
        "verified": verified,
        "false_discard_rate": false_discard_rate(verified, total),
        "wilson_low": low,
        "wilson_high": high,
    }


def discards_needed_for_safe(
    verified: int, total: int, *, wilson_z: float, safe_upper: float
) -> int | None:
    """`safe` 에 도달하려면 **몇 개를 더** 모아야 하는가.

    누적을 언제 멈출지가 이 측정의 실무적 질문이고, 그것을 사람이 매번
    손으로 푸는 대신 여기서 답한다. 이미 `safe` 면 0, 지금 verified 수로는
    아무리 모아도 도달할 수 없으면 `None`.

    상한이 없는 것이 아니라 **비율이 이미 문턱을 넘었을 때** 도달 불가다 --
    Wilson 상한은 표본이 커지면 비율로 수렴하므로, `verified/total` 이
    `safe_upper` 이상이면 더 모으는 것으로는 내려오지 않는다. 그 경우
    필요한 것은 표본이 아니라 필터 수정이다.
    """
    if total > 0:
        _, high = wilson_interval(verified, total, wilson_z)
        if high < safe_upper:
            return 0
    if total > 0 and verified / total >= safe_upper:
        return None
    if verified > 0 and safe_upper <= 0:
        return None
    # 새로 모으는 관측이 전부 "검증되지 않음" 이라고 가정한 최선의 경우.
    # 그 가정이 낙관적이라는 것이 요점이다: 이 수는 하한이고, 실제로는 더
    # 필요하다. 낙관적인 하한을 주는 편이 "모르겠다" 보다 계획에 쓸모 있다.
    extra = 0
    while extra < _NEEDED_SEARCH_CAP:
        _, high = wilson_interval(verified, total + extra, wilson_z)
        if total + extra > 0 and high < safe_upper:
            return extra
        extra += 1
    return None


#: `discards_needed_for_safe` 의 탐색 상한. 이만큼 더 모아도 안 되면 그
#: 계획은 표본 수집이 아니라 다른 것을 필요로 한다.
_NEEDED_SEARCH_CAP = 10_000

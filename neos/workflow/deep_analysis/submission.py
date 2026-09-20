"""`submit.v1` 의 페이로드를 읽는다 (계약 §3.4).

도구 **밖에** 있는 이유는 `check_claims.v1` 이 "submit.v1 과 같은 모양" 을
받기 때문이다(계약 §3.3). 파서가 도구 안에 있으면 둘째 도구가 둘째 방언을
갖게 된다.

여기는 **파싱만** 한다. 판정하지 않는다:

- **confidence 를 깎지 않는다.** 기존 워커는 출처 수로 상한을 건다. 제출에서
  같은 일을 하면 워커의 자기 신고가 채점 전에 고쳐지고, 그러면
  `E_CONFIDENCE_INFLATED` 가 영원히 발화하지 못한다. 범위 밖의 값(1.5 같은)도
  손대지 않는다 -- 그것은 어떤 상한보다도 크므로 채점이 잡는다.
- **`raw_ref` 가 원장에 있는지 보지 않는다.** 없는 것은 채점의 코드
  (`E_COMPUTE_INPUT_UNFETCHED` · `E_NO_EVIDENCE`)가 말한다. 워커가 초록을
  봤다는 사실은 증거가 아니다(§3.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, get_args

from .models import (
    ComputedEvidence,
    ProposedClaim,
    ProposedEvidence,
    ProposedSubquestion,
    RepairResult,
)

#: 수리 어휘는 `RepairResult.action` 이 이미 `Literal` 로 갖고 있다. 다시
#: 적으면 `worker.py` 의 `_REPAIR_ACTIONS` 와 갈라질 수 있어 거기서 끌어온다.
REPAIR_ACTIONS: frozenset[str] = frozenset(
    get_args(RepairResult.__annotations__["action"])
)

#: 계약이 정하지 않은 자리. 모르는 status 를 완료로 읽으면 부분 결과가 완료로
#: 원장에 들어간다 -- 계약이 "제출하지 않고 끝난 턴은 partial" 이라고 적은 것과
#: 같은 방향으로 기운다.
DEFAULT_STATUS = "partial"


@dataclass
class Submission:
    """`submit.v1` 한 번의 내용. 오케스트레이터가 읽어 원장에 쓴다 (P2)."""

    status: Literal["completed", "partial"] = "partial"
    claims: list[ProposedClaim] = field(default_factory=list)
    self_assessment: float = 0.0
    proposed_subquestions: list[ProposedSubquestion] = field(default_factory=list)
    dead_ends: list[str] = field(default_factory=list)
    repairs: list[RepairResult] = field(default_factory=list)
    report_path: str | None = None


def _float(raw: object, default: float = 0.0) -> float:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _str_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def _evidence(raw: object) -> list[ProposedEvidence]:
    if not isinstance(raw, list):
        return []
    parsed: list[ProposedEvidence] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        parsed.append(
            ProposedEvidence(
                source_url=str(item.get("source_url", "")),
                excerpt=str(item.get("excerpt", "")),
                # 워커가 `fetch.v1` 결과에서 그대로 들고 온 값이다. URL 로
                # 되찾지 않는다 -- 되찾는 경로는 못 찾은 증거를 조용히 버린다.
                raw_ref=str(item.get("raw_ref", "")),
            )
        )
    return parsed


def _computation(raw: object) -> ComputedEvidence | None:
    if not isinstance(raw, Mapping):
        return None
    runtime = raw.get("runtime")
    return ComputedEvidence(
        script_ref=str(raw.get("script_ref", "")),
        inputs=_str_list(raw.get("inputs")),
        premises=_str_list(raw.get("premises")),
        runtime=dict(runtime) if isinstance(runtime, Mapping) else {},
        output_digest=str(raw.get("output_digest", "")),
        claimed_value=str(raw.get("claimed_value", "")),
    )


def _claims(raw: object) -> list[ProposedClaim]:
    if not isinstance(raw, list):
        return []
    parsed: list[ProposedClaim] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            # 본문 없는 클레임은 지어내지 않는다. 남은 것은 그대로 지나간다.
            continue
        kind = item.get("kind", "quote")
        if kind not in ("quote", "computed"):
            kind = "quote"
        confidence = _float(item.get("confidence"))
        if kind == "computed":
            parsed.append(
                ProposedClaim(
                    text=text,
                    confidence=confidence,
                    kind="computed",
                    computation=_computation(item.get("computation")),
                )
            )
            continue
        parsed.append(
            ProposedClaim(
                text=text,
                confidence=confidence,
                evidence=_evidence(item.get("evidence")),
            )
        )
    return parsed


def _subquestions(raw: object) -> list[ProposedSubquestion]:
    """옛 문자열 형태도 받는다 -- `worker.py` 의 `_parse_subquestions` 와 같다.

    문자열은 `value_est=0.0` 이 되어 채택 임계값 아래로 떨어진다. 값을 모르는
    제안을 통과시키는 쪽으로 기울면 "임계값 없이 전부 채택" 이 된다(D65).
    """
    if not isinstance(raw, list):
        return []
    parsed: list[ProposedSubquestion] = []
    for item in raw:
        if isinstance(item, str):
            text, value = item, 0.0
        elif isinstance(item, Mapping):
            text = str(item.get("text", ""))
            value = _float(item.get("value_est"))
        else:
            continue
        if not text.strip():
            continue
        parsed.append(
            ProposedSubquestion(text=text.strip(), value_est=min(1.0, max(0.0, value)))
        )
    return parsed


def _repairs(raw: object) -> list[RepairResult]:
    if not isinstance(raw, list):
        return []
    parsed: list[RepairResult] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        action = str(item.get("action", "fixed"))
        if action not in REPAIR_ACTIONS:
            action = "fixed"
        new_text = item.get("new_text")
        parsed.append(
            RepairResult(
                claim_id=str(item.get("claim_id", "")),
                action=action,  # type: ignore[arg-type]
                new_text=str(new_text) if new_text is not None else None,
                new_evidence=_evidence(item.get("new_evidence")),
            )
        )
    return parsed


def parse_submission(payload: Mapping[str, Any]) -> Submission:
    data = dict(payload) if isinstance(payload, Mapping) else {}
    report_path = data.get("report_path")
    return Submission(
        status="completed" if data.get("status") == "completed" else DEFAULT_STATUS,
        claims=_claims(data.get("claims")),
        self_assessment=_float(data.get("self_assessment")),
        proposed_subquestions=_subquestions(data.get("proposed_subquestions")),
        dead_ends=_str_list(data.get("dead_ends")),
        repairs=_repairs(data.get("repairs")),
        report_path=str(report_path) if report_path is not None else None,
    )

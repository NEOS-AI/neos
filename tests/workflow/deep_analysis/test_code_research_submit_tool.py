"""`submit.v1` — 출력 계약 (계약 §3.4) 과 계산 증거 (§4).

`submit.v1` 은 **파싱하지 판정하지 않는다.** 판정은 오케스트레이터가 한다
(§3.3: "워커가 초록을 봤다는 사실은 증거가 아니다"). 이 구별이 이 파일의
절반을 설명한다:

- **confidence 를 깎지 않는다.** 기존 워커(`worker.py`)는 출처 수로 상한을
  건다. 제출에서 같은 일을 하면 워커의 자기 신고가 **채점 전에** 고쳐지고,
  그러면 `E_CONFIDENCE_INFLATED` 는 영원히 발화하지 못한다 -- 채점 규칙을
  관측 불가능하게 만드는 "친절한" 파서다.
- **`raw_ref` 를 URL 로 되찾지 않는다.** 기존 워커는 `fetched_by_url` 에서
  찾고 못 찾으면 **조용히 버린다**(`worker.py` 의 `if fetched is None`).
  코드 경로에서는 워커가 `fetch.v1` 결과로 이미 `raw_ref` 를 들고 있고,
  계약 §3.4 가 그것을 그대로 싣는다.

계약이 말하지 않아 **내가 고른** 것 둘은 아래 테스트에 이름으로 박아 둔다:
빠지거나 모르는 `status` 는 `partial` 이고, 두 번째 제출은 거절이다.

임포트를 함수 안에 두는 이유는 같은 디렉터리의 다른 J1 테스트와 같다.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.no_db


_QUOTE = {
    "kind": "quote",
    "text": "런던은 2026년에 비가 왔다",
    "confidence": 0.9,
    "evidence": [
        {
            "source_url": "https://example.com/doc",
            "excerpt": "it rained",
            "raw_ref": "abc123def456ffff",
        }
    ],
}

_COMPUTED = {
    "kind": "computed",
    "text": "평균은 42.5 다",
    "confidence": 0.7,
    "computation": {
        "script_ref": "f" * 16,
        "inputs": ["abc123def456ffff"],
        "premises": ["claim_1"],
        "runtime": {
            "profile": "research-offline-v1",
            "image_digest": "sha256:deadbeef",
        },
        "output_digest": "e" * 64,
        "claimed_value": "42.5",
    },
}


def _payload(**overrides):
    base = {
        "status": "completed",
        "claims": [dict(_QUOTE)],
        "self_assessment": 0.8,
        "proposed_subquestions": [{"text": "런던 말고 파리는?", "value_est": 0.6}],
        "dead_ends": ["기상청 API 는 2020 년까지만 준다"],
        "repairs": [],
        "report_path": None,
    }
    base.update(overrides)
    return base


def test_computed_evidence_carries_the_contract_fields() -> None:
    """계약 §4. 채점(J2)은 아직이지만 모양은 제출이 받는 순간 필요하다."""
    from neos.workflow.deep_analysis.models import ComputedEvidence

    evidence = ComputedEvidence(
        script_ref="f" * 16,
        inputs=["abc123def456ffff"],
        premises=["claim_1"],
        runtime={"profile": "research-offline-v1", "image_digest": "sha256:x"},
        output_digest="e" * 64,
        claimed_value="42.5",
    )

    assert evidence.inputs == ["abc123def456ffff"]
    assert evidence.premises == ["claim_1"]
    assert evidence.claimed_value == "42.5"


def test_a_claim_is_a_quote_claim_unless_it_says_otherwise() -> None:
    """기존 경로가 만드는 클레임은 전부 quote 다. 기본값이 그것을 말한다."""
    from neos.workflow.deep_analysis.models import ProposedClaim

    claim = ProposedClaim(text="t", confidence=0.5)

    assert claim.kind == "quote"
    assert claim.computation is None


def test_a_quote_claim_keeps_the_raw_ref_the_worker_submitted() -> None:
    from neos.workflow.deep_analysis.submission import parse_submission

    submission = parse_submission(_payload())

    claim = submission.claims[0]
    assert claim.kind == "quote"
    assert claim.evidence[0].raw_ref == "abc123def456ffff"
    assert claim.evidence[0].source_url == "https://example.com/doc"


def test_confidence_is_recorded_as_claimed_not_clamped() -> None:
    """깎으면 `E_CONFIDENCE_INFLATED` 가 영원히 발화하지 못한다.

    출처가 하나뿐인데 0.9 를 주장하는 것은 **채점이 잡을 일**이다. 여기서
    0.6 으로 고쳐 두면 원장에는 언제나 규칙을 지킨 클레임만 남고, 과신을
    측정하려던 지표가 0 으로 고정된다.
    """
    from neos.workflow.deep_analysis.submission import parse_submission

    submission = parse_submission(_payload())

    assert submission.claims[0].confidence == 0.9


def test_a_computed_claim_carries_its_computation() -> None:
    from neos.workflow.deep_analysis.submission import parse_submission

    submission = parse_submission(_payload(claims=[dict(_COMPUTED)]))

    claim = submission.claims[0]
    assert claim.kind == "computed"
    assert claim.computation is not None
    assert claim.computation.output_digest == "e" * 64
    assert claim.computation.inputs == ["abc123def456ffff"]
    assert claim.evidence == []


def test_the_rest_of_the_envelope_is_parsed() -> None:
    from neos.workflow.deep_analysis.submission import parse_submission

    submission = parse_submission(_payload())

    assert submission.status == "completed"
    assert submission.self_assessment == 0.8
    assert submission.proposed_subquestions[0].text == "런던 말고 파리는?"
    assert submission.proposed_subquestions[0].value_est == 0.6
    assert submission.dead_ends == ["기상청 API 는 2020 년까지만 준다"]
    assert submission.report_path is None


def test_repairs_keep_the_existing_vocabulary() -> None:
    """계약 §3.4: repairs 는 "기존과 같다"."""
    from neos.workflow.deep_analysis.submission import parse_submission

    submission = parse_submission(
        _payload(
            repairs=[
                {"claim_id": "c1", "action": "weakened", "new_text": "약하게"},
                {"claim_id": "c2", "action": "누가봐도아닌것"},
            ]
        )
    )

    assert submission.repairs[0].action == "weakened"
    assert submission.repairs[0].new_text == "약하게"
    # 모르는 action 은 기존 파서와 같이 "fixed" 로 떨어진다.
    assert submission.repairs[1].action == "fixed"


@pytest.mark.parametrize("raw", [None, "", "done", "COMPLETED", 3])
def test_an_unknown_status_is_partial_not_completed(raw) -> None:
    """계약이 정하지 않은 자리 -- 과대 신고 쪽으로 기울지 않는다.

    `worker.py` 는 빠진 status 를 `completed` 로 읽지만, 그것은 응답 전체를
    자기가 만들던 시절의 기본값이다. 제출은 **명시적 출력 계약**이라 모르는
    값을 완료로 읽으면 부분 결과가 완료로 원장에 들어간다. 계약이 이미
    "제출하지 않고 끝난 턴은 partial" 이라고 적은 것과 같은 방향이다.
    """
    from neos.workflow.deep_analysis.submission import parse_submission

    payload = _payload()
    if raw is None:
        payload.pop("status")
    else:
        payload["status"] = raw

    assert parse_submission(payload).status == "partial"


def test_a_malformed_claim_is_dropped_not_guessed() -> None:
    """text 없는 클레임은 지어내지 않는다. 남은 것은 그대로 지나간다."""
    from neos.workflow.deep_analysis.submission import parse_submission

    submission = parse_submission(
        _payload(claims=[{"kind": "quote", "confidence": 0.5}, dict(_QUOTE)])
    )

    assert len(submission.claims) == 1
    assert submission.claims[0].text == "런던은 2026년에 비가 왔다"


@pytest.mark.asyncio
async def test_the_port_offers_submit_v1_and_records_one_submission() -> None:
    from neos.workflow.deep_analysis.research_tools import ResearchToolPort

    port = ResearchToolPort(fetch_fn=None, store=None, sandbox=None, cap_bytes=0)

    assert "submit.v1" in [item.name for item in port.definitions()]
    assert port.submission is None

    ack = await port.execute("submit.v1", _payload())

    assert ack["status"] == "recorded"
    assert ack["claims"] == 1
    assert port.submission is not None
    assert port.submission.claims[0].text == "런던은 2026년에 비가 왔다"


@pytest.mark.asyncio
async def test_a_second_submission_is_refused_rather_than_overwriting() -> None:
    """계약이 말하지 않은 자리 -- 조용히 덮으면 첫 제출이 사라진다."""
    from neos.workflow.deep_analysis.research_tools import ResearchToolPort

    port = ResearchToolPort(fetch_fn=None, store=None, sandbox=None, cap_bytes=0)
    await port.execute("submit.v1", _payload())

    second = await port.execute("submit.v1", _payload(claims=[], status="partial"))

    assert second["error"] == "already_submitted"
    assert port.submission.status == "completed"
    assert len(port.submission.claims) == 1

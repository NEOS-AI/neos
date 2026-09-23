"""루브릭 문장은 매 요청 본문에 실린다 -- WAF 가 막는 문자열이 있으면 그 루브릭의
**모든** 호출이 막힌다(로드맵 §12.11 ②).

D-L2 의 첫 초안이 정확히 그랬다: `exfiltration` 기준에 시스템 계정 파일 경로를
예로 적었고, 대상과 무관하게 모든 호출이 403 이었다. 게이트로는 "사실상 off" 다.

목록은 **실측으로 확인한 것만** 적는다. 추측으로 늘리면 루브릭 문구가 이유 없이
빈약해지고, 목록이 무엇을 근거로 하는지 아무도 모르게 된다.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from neos.jev.rubric import load_rubric

pytestmark = pytest.mark.no_db

RUBRICS = pathlib.Path(__file__).resolve().parents[2] / "neos" / "jev" / "rubrics"

#: 트리거 -> 확인한 곳.
KNOWN_TRIGGERS = {
    "/etc/passwd": "artifacts/jev-probe/20260923T102517Z-waf-minimal-pairs/",
}


def test_the_rubrics_were_found() -> None:
    assert len(list(RUBRICS.glob("*.yaml"))) >= 3


@pytest.mark.parametrize("path", sorted(RUBRICS.glob("*.yaml")), ids=lambda p: p.name)
def test_no_rubric_sends_a_known_waf_trigger(path: pathlib.Path) -> None:
    # 파일 원문이 아니라 **나가는 것**을 본다 -- YAML 주석은 요청에 실리지
    # 않으므로 트리거를 설명하는 주석은 문제가 없다(이 검사가 처음 그 주석을
    # 잡아 거짓 경보를 냈다).
    text = json.dumps(load_rubric(path.stem).questions, ensure_ascii=False)
    for trigger, evidence in KNOWN_TRIGGERS.items():
        assert trigger not in text, (
            f"{path.name} 에 WAF 트리거 {trigger!r} 가 있다({evidence}). "
            "이 루브릭의 모든 호출이 403 으로 막힌다 -- 문자 그대로 적지 말고 풀어 쓸 것."
        )

"""워커에게 줄 지시 하나를 짓는다 (원장 상태 → `Assignment`).

`Orchestrator._partition` 안에 있던 블록을 그대로 옮긴 것이다. 옮긴 이유는
**J3 오프라인 섀도**가 같은 brief 를 필요로 하기 때문이다 -- 섀도가 자기
brief 를 따로 지으면 비교한 것이 두 워커가 아니라 두 프롬프트가 된다.

⚠️ **여기 있는 것은 워커가 보는 것의 일부다(I1).** brief 한 글자가 달라지면
플래그 off 경로의 워커 프롬프트가 달라진다. 그래서 추출은 바이트 동일성을
측정해 확인했고(2026-09-21, 여섯 경우: fresh·with_history × scout·dig·synth),
앞으로 이 함수를 고치는 커밋은 같은 것을 확인해야 한다.

원장 접근자는 **방어적으로** 읽는다(`_collect_caveats` 와 같은 패턴) --
최소 test double 이 `verified_summaries`·`unverified_and_deadends` 를
구현하지 않아도 되게 하려는 것이고, 옮기면서 그대로 두었다.
"""

from __future__ import annotations

from typing import Any

from neos.config.settings import settings

from .models import Assignment, Effort
from .prompt_loader import render

#: 거절 코드별 수선 지시. `worker_brief.md` 의 repairs 줄에 그대로 박힌다.
REPAIR_PRESCRIPTIONS = {
    "E_OVERCLAIM": "문구를 증거 수준으로 약화(action=weakened, 재조사 금지)",
    "E_CONTRADICTED": "부정형으로 재작성(action=fixed, new_text=부정형)",
    "E_UNSUPPORTED": "다른 증거 탐색, 실패 시 action=abandoned",
    "E_QUOTE_MISMATCH": "salvage 출처에서 정확 발췌 재수집",
}


def render_repair_lines(repairs: list[dict]) -> str:
    """수선 지시 한 줄씩. `worker_brief` 와 조사 자식의 briefing(J1.5)이 같이 쓴다.

    두 벌로 두면 처방 문구를 고칠 때 한쪽만 바뀐다. 빈 목록의 "(없음)" 은
    부르는 쪽 몫이다 -- 조사 briefing 은 빈 칸을 비워 둔다.
    """
    return "\n".join(
        f"{r['claim_id']} | {r['code']} | {r['detail']} | "
        f"{REPAIR_PRESCRIPTIONS.get(r['code'], '')} | "
        f"{r['salvage'] or ''}"
        for r in repairs
    )


async def build_assignment(
    ledger: Any, question: Any, effort: Effort
) -> Assignment:
    """이 질문·이 노력 수준에 대한 지시 하나.

    `Effort.SPLIT` 은 여기 오지 않는다 -- 분할은 지시가 아니라 다른 행동이고,
    그 갈래는 부르는 쪽(`_partition`)이 먼저 걸러낸다.
    """
    config = settings.config.deep_analysis
    feedback = await ledger.pending_feedback(question.id)
    repairs = [
        {
            "claim_id": item.claim_id,
            "code": item.code,
            "detail": item.detail,
            "salvage": item.salvage,
        }
        for item in feedback
    ]
    if repairs:
        repair_count = len(repairs)
        repairs_rendered = render_repair_lines(repairs)
    else:
        repair_count = 0
        repairs_rendered = "(없음)"
    # worker_brief.md [3] "확정된 발견 — 재조사 금지": 이 질문의 이전
    # 패스가 이미 확정한 클레임과 막다른 길을 워커에 전달해야 재조사가
    # 같은 길을 반복하지 않고 수렴한다. (첫 패스에는 둘 다 "(없음)".)
    # Ledger 접근자는 방어적으로 읽어 최소 test double은 구현할
    # 필요가 없게 한다(_collect_caveats와 동일한 패턴).
    summaries_fn = getattr(ledger, "verified_summaries", None)
    verified_summaries = (
        await summaries_fn(question.id) if summaries_fn is not None else "(없음)"
    )
    deadends_fn = getattr(ledger, "unverified_and_deadends", None)
    dead_end_entries = (
        await deadends_fn(question.id) if deadends_fn is not None else []
    )
    dead_ends_rendered = (
        "\n".join(f"- {entry}" for entry in dead_end_entries)
        if dead_end_entries
        else "(없음)"
    )
    brief = render(
        "worker_brief",
        question_text=question.text,
        verified_summaries=verified_summaries,
        dead_ends=dead_ends_rendered,
        repair_count=repair_count,
        repairs=repairs_rendered,
        token_cap=config.effort[effort.value].token_cap,
        confidence_cap_one=config.confidence_cap[1],
        confidence_cap_two=config.confidence_cap[2],
        confidence_cap_three_plus=config.confidence_cap[3],
        subq_adopt_threshold=config.subq_adopt_threshold,
        resolve_threshold=config.resolve_threshold,
    )
    return Assignment(
        question.id,
        brief,
        effort,
        repairs,
        question_text=question.text,
    )

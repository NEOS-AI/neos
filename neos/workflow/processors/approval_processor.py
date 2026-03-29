"""실행 승인 프로세서 (Phase 2 — OpenClaw Execution Approval System)

LangGraph Human-in-the-Loop 패턴을 구현한다.
EXECUTION_APPROVAL 노드는 interrupt_before에 의해 중단된 후 resume 시 실행된다.
따라서 진입 시 state["approval_decision"]에는 이미 사용자 결정이 담겨 있다.

흐름:
    SKILL_TOOL_SELECTOR
        ↓ (민감 스킬 + allowlist 없음)
    [LangGraph interrupt_before=EXECUTION_APPROVAL]
        ↓ (SSE로 approval_request 이벤트 발행)
    [사용자가 POST /api/v1/approval/respond 호출]
        ↓ (graph.aupdate_state → approval_decision 설정)
    [graph.ainvoke(None) 로 resume]
        ↓
    EXECUTION_APPROVAL 노드 실행 ← 여기가 이 파일
        ├→ "approved" → 오케스트레이터 경로 (HYPOTHESIS_GENERATION)
        └→ "rejected" → RESP_GENERATOR (거부 응답 생성)
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from neos.workflow.state import AgentState

logger = logging.getLogger(__name__)


class ApprovalProcessor:
    """
    실행 승인 노드 프로세서

    LangGraph interrupt_before에 의해 그래프가 중단된 후 resume 시 실행된다.
    state["approval_decision"]을 읽어 후속 라우팅을 결정한다.

    반환 값에 따른 라우팅 (graph.py의 _should_continue_after_approval 참조):
    - approval_decision == "approved" → "approved" 경로 (오케스트레이터로 진행)
    - approval_decision == "rejected" → "rejected" 경로 (RESP_GENERATOR로 종료)
    - 그 외 → "rejected" (안전 기본값)
    """

    async def process(self, state: AgentState) -> Dict[str, Any]:
        """
        승인 결정에 따라 상태를 업데이트한다.

        Args:
            state: 현재 워크플로우 상태 (approval_decision 포함)

        Returns:
            업데이트할 상태 필드들
        """
        decision = state.get("approval_decision")
        pending = state.get("pending_approvals") or []

        skill_names = [p.get("skill_name", "unknown") for p in pending]

        if decision == "approved":
            logger.info(
                f"[ApprovalProcessor] Skills approved: {skill_names}. "
                "Continuing workflow execution."
            )
            return {
                "pending_approvals": [],
                "approval_decision": None,  # 초기화 — 다음 라운드에서 재사용 가능
                "approval_outcome": "approved",  # 라우팅 전용 필드
            }

        elif decision == "rejected":
            logger.info(
                f"[ApprovalProcessor] Skills rejected by user: {skill_names}. "
                "Routing to response generator."
            )
            return {
                "pending_approvals": [],
                "approval_decision": None,
                "approval_outcome": "rejected",  # 라우팅 전용 필드
                "final_response": (
                    f"요청하신 작업({', '.join(skill_names)})이 사용자에 의해 취소되었습니다.\n"
                    "다른 방법으로 도움을 드릴 수 있는지 알려주세요."
                ),
            }

        else:
            # interrupt 이전에 EXECUTION_APPROVAL 노드가 실행되는 경우는 없어야 하나,
            # 만약 도달하면 안전하게 rejected 처리한다.
            logger.warning(
                f"[ApprovalProcessor] Unexpected approval_decision={decision!r}. "
                "Defaulting to rejected (safety fallback)."
            )
            return {
                "pending_approvals": [],
                "approval_decision": None,
                "approval_outcome": "rejected",  # 라우팅 전용 필드
                "final_response": (
                    "승인 처리 중 예기치 않은 상태가 발생했습니다. "
                    "다시 시도해주세요."
                ),
            }

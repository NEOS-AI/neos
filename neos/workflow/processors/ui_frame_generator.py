"""UI Frame Generator (Phase 8 — OpenClaw A2UI)

QueryClassifier가 needs_ui=True로 표시한 경우 실행.
SKILL_TOOL_SELECTOR 직후 단락 경로로 연결 (research 파이프라인 우회).
LLM 구조화 출력(Claude tool_use)으로 UIFrame JSON 생성.

⚠️ 주의사항:
- NEOS 노드들은 WorkflowStreamCallback을 LangGraph 이벤트로 자동 감지하지 않음.
  state["_event_handler"]에서 event_handler를 가져와 명시적으로 호출한다.
- 반환 값은 state diff만 (state 직접 수정 금지).
- UI_FRAME_GENERATOR → END 단락 경로 — research 파이프라인 전체 우회.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from neos.config.settings import settings
from neos.utils.llm_factory import create_llm
from neos.workflow.state import AgentState

logger = logging.getLogger(__name__)

# UIFrame 생성용 LLM 시스템 프롬프트
_UI_FRAME_SYSTEM_PROMPT = """You are a UI component generator for an AI assistant.
Given a user query and intent, generate a UIFrame JSON with appropriate input components.

Rules:
- Use ONLY the provided component types
- Keep components minimal (max {max_components} components)
- All required fields must have "required": true
- Use Korean labels for Korean queries, English for English queries
- The "intent" field must be a snake_case descriptor (e.g., "restaurant_reservation")
"""

_UI_FRAME_TOOL_SCHEMA = {
    "name": "generate_ui_frame",
    "description": "Generate a UI frame with components for user input collection",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "description": "snake_case intent descriptor"},
            "components": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string", "enum": [
                            "text_field", "date_picker", "time_picker", "select",
                            "multi_select", "slider", "checkbox", "file_upload",
                            "card", "chart", "table", "progress", "divider", "button", "form"
                        ]},
                        "label": {"type": "string"},
                        "placeholder": {"type": "string"},
                        "required": {"type": "boolean"},
                        "options": {"type": "array"},
                        "min": {"type": "number"},
                        "max": {"type": "number"},
                        "step": {"type": "number"},
                        "default_value": {},
                    },
                    "required": ["id", "type"],
                },
            },
        },
        "required": ["intent", "components"],
    },
}


class UIFrameGenerator:
    """
    UIFrame 생성 노드 프로세서

    graph.py 초기화 시 인스턴스가 생성되고, 노드 래퍼(_ui_frame_generator_node)를 통해
    state를 받아 UIFrame을 생성한 뒤 SSE 이벤트를 발행한다.

    반환 값: {"ui_frame": UIFrame.dict(), "needs_ui": False}
    """

    async def generate(self, state: AgentState) -> Dict[str, Any]:
        """
        UIFrame 생성 메인 메서드.

        Args:
            state: 현재 워크플로우 상태 (original_query, session_id, conversation_context 포함)

        Returns:
            {"ui_frame": dict, "needs_ui": False}
        """
        query = state.get("original_query", "")
        session_id = state.get("session_id", "")
        context = state.get("conversation_context", "")

        logger.info("[UIFrameGenerator] Generating UIFrame for query: %s...", query[:50])

        try:
            ui_frame_data = await self._call_llm(query, context, session_id)
        except Exception as e:
            logger.error("[UIFrameGenerator] LLM call failed: %s", e)
            # fallback: 텍스트 입력 단일 컴포넌트
            ui_frame_data = self._fallback_frame(query, session_id)

        # Pydantic 검증
        from neos.api.models.ui_components import UIFrame
        try:
            validated = UIFrame(**ui_frame_data)
        except Exception as e:
            logger.warning("[UIFrameGenerator] Pydantic validation failed: %s", e)
            validated = UIFrame(**self._fallback_frame(query, session_id))

        # timeout_seconds를 설정값으로 동기화 (LLM은 이 필드를 생성하지 않음)
        # DB expires_at과 클라이언트 표시값 일치를 보장한다.
        validated.timeout_seconds = settings.A2UI_FRAME_TIMEOUT

        validated_dict = validated.model_dump()

        # UIFrameSession DB 저장 (submit 시 원본 쿼리 복원용)
        # 저장 실패 시 SSE 발행을 취소하여 submit 시 404를 방지
        saved = await self._save_frame_session(
            frame_id=validated.frame_id,
            session_id=session_id,
            conversation_id=state.get("conversation_id"),
            original_query=query,
            frame_data=validated_dict,
            user_id=state.get("user_id"),
        )

        if not saved:
            logger.error(
                "[UIFrameGenerator] Skipping SSE emission due to DB save failure. "
                "frame_id=%s",
                validated.frame_id,
            )
            # state diff: needs_ui=False만 해제 (UI 발행 없이 종료)
            return {"needs_ui": False}

        # SSE 이벤트 발행 (DB 저장 성공 후에만 발행)
        event_handler = state.get("_event_handler")
        if event_handler and hasattr(event_handler, "on_ui_frame"):
            await event_handler.on_ui_frame(validated_dict)

        logger.info(
            "[UIFrameGenerator] Generated UIFrame frame_id=%s, components=%d",
            validated.frame_id,
            len(validated.components),
        )

        # state diff만 반환 (state 직접 수정 금지 — 기존 노드 일관성)
        return {"ui_frame": validated_dict, "needs_ui": False}

    async def _call_llm(
        self, query: str, context: str, session_id: str
    ) -> Dict[str, Any]:
        """Claude tool_use로 UIFrame JSON 구조화 출력."""
        llm = create_llm(
            provider="anthropic",
            model=settings.A2UI_LLM_MODEL,
            temperature=0.0,
            max_tokens=800,  # UI는 간결해야 함
        )

        system = _UI_FRAME_SYSTEM_PROMPT.format(
            max_components=settings.A2UI_MAX_COMPONENTS
        )
        user_msg = f"User query: {query}"
        if context:
            user_msg += f"\n\nConversation context: {context[:300]}"

        # tool_use 강제 (bind_tools 패턴)
        llm_with_tools = llm.bind_tools([_UI_FRAME_TOOL_SCHEMA], tool_choice="generate_ui_frame")
        response = await llm_with_tools.ainvoke([
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ])

        # tool_use 응답 파싱
        for block in (response.content if hasattr(response, "content") else []):
            if hasattr(block, "type") and block.type == "tool_use":
                frame_data = dict(block.input)   # 얕은 복사 — SDK 원본 객체 보호
                frame_data["session_id"] = session_id
                return frame_data

        raise ValueError("LLM did not return tool_use block")

    def _fallback_frame(self, query: str, session_id: str) -> Dict[str, Any]:
        """LLM 실패 시 단일 텍스트 입력 폼."""
        return {
            "intent": "user_input",
            "components": [
                {
                    "id": "input",
                    "type": "text_field",
                    "label": "입력",
                    "placeholder": query,
                    "required": True,
                },
                {"id": "submit", "type": "button", "label": "확인"},
            ],
            "session_id": session_id,
        }

    async def _save_frame_session(
        self,
        frame_id: str,
        session_id: str,
        conversation_id: Optional[str],
        original_query: str,
        frame_data: dict,
        user_id: Optional[str] = None,
    ) -> bool:
        """UIFrameSession DB 저장 (submit 시 원본 쿼리 복원용).

        Returns:
            True: 저장 성공
            False: 저장 실패 (호출자는 SSE 발행을 건너뛰어야 함)
        """
        from datetime import datetime, timedelta, timezone
        from neos.database.connection import get_db_session
        from neos.database.models import UIFrameSession
        import uuid

        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
            seconds=settings.A2UI_FRAME_TIMEOUT
        )

        try:
            async with get_db_session() as db:
                session_record = UIFrameSession(
                    frame_id=uuid.UUID(frame_id),
                    session_id=session_id,
                    user_id=uuid.UUID(user_id) if user_id else None,
                    conversation_id=uuid.UUID(conversation_id) if conversation_id else None,
                    original_query=original_query,
                    frame_data=frame_data,
                    expires_at=expires_at,
                )
                db.add(session_record)
                await db.commit()
            return True
        except Exception as e:
            logger.warning("[UIFrameGenerator] Failed to save UIFrameSession: %s", e)
            return False

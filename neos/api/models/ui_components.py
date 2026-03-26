"""UI 컴포넌트 모델 (Phase 8 — OpenClaw A2UI)

에이전트가 생성하는 UIFrame JSON 스키마를 정의한다.
순수 JSON 데이터만 전송 (실행 코드 없음) — UI 인젝션 원천 차단.
평면 리스트(flat list) 구조 — LLM 토큰 효율 극대화.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class UIComponentType(str, Enum):
    # 입력형
    TEXT_FIELD   = "text_field"
    DATE_PICKER  = "date_picker"
    TIME_PICKER  = "time_picker"
    SELECT       = "select"
    MULTI_SELECT = "multi_select"
    SLIDER       = "slider"
    CHECKBOX     = "checkbox"
    FILE_UPLOAD  = "file_upload"
    # 표시형
    CARD         = "card"
    CHART        = "chart"
    TABLE        = "table"
    PROGRESS     = "progress"
    DIVIDER      = "divider"
    # 액션형
    BUTTON       = "button"
    FORM         = "form"


class UIComponent(BaseModel):
    id: str                                 # 고유 식별자 (폼 제출 시 key)
    type: UIComponentType
    label: Optional[str] = None
    placeholder: Optional[str] = None
    required: bool = False
    options: Optional[List[Dict[str, Any]]] = None  # select/multi_select용: [{"label": ..., "value": ...}]
    min: Optional[float] = None             # slider/number용
    max: Optional[float] = None
    step: Optional[float] = None
    default_value: Optional[Any] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)  # 렌더러 힌트 (style, icon 등)


class UIFrame(BaseModel):
    frame_id: str = Field(default_factory=lambda: str(uuid4()))
    intent: str                             # 사람이 읽을 수 있는 의도 설명 (예: "restaurant_reservation")
    components: List[UIComponent]           # 평면 리스트 (트리 구조 아님 — LLM 토큰 효율)
    submit_action: str = "/api/v1/ui/submit"
    session_id: str
    conversation_id: Optional[str] = None
    timeout_seconds: int = 300              # 폼 만료 시간 (A2UI_FRAME_TIMEOUT과 동기화)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UISubmitRequest(BaseModel):
    """POST /api/v1/ui/submit 요청 본문"""
    frame_id: str
    session_id: str
    conversation_id: Optional[str] = None
    values: Dict[str, Any]                  # 폼 제출값: {"date": "2026-03-25", "time": "19:00", "party": 3}

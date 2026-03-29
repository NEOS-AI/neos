"""CanvasSkill — 연구 결과를 동적 캔버스로 렌더링하는 스킬

Phase 6 (OpenClaw Canvas / PDF 스킬 강화)

세션 ID를 받아 DB의 연구 결과를 조회하고, 요청한 캔버스 타입에 따라
구조화된 마크다운 / 차트 / Mermaid 다이어그램을 조합하여 반환한다.
"""

import asyncio
import logging
from typing import Any, Dict

from neos.skills.base.skill import BaseSkill
from neos.skills.base.result import SkillResult
from neos.skills.base.types import SkillType

logger = logging.getLogger(__name__)

CANVAS_TYPES = ("markdown", "chart", "diagram", "all")


class CanvasSkill(BaseSkill):
    """연구 세션 결과를 캔버스 형태로 렌더링하는 스킬.

    사용 예:
        - "TSLA 분석 결과를 캔버스로 보여줘"
        - "리서치 결과 차트로 시각화해줘"
        - "연구 결과 마인드맵으로 정리해줘"
    """

    def __init__(self):
        super().__init__(
            name="canvas",
            skill_type=SkillType.CONTENT_GENERATION,
            description="연구 결과를 구조화된 캔버스(마크다운·차트·다이어그램)로 렌더링",
            capabilities=[
                "render_canvas",
                "export_canvas_html",
                "generate_chart",
                "generate_diagram",
            ],
            version="1.0.0",
        )
        self.is_available = True

    async def initialize(self) -> bool:
        self.is_available = True
        return True

    async def cleanup(self) -> None:
        pass

    @classmethod
    def get_input_schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "렌더링할 연구 세션 ID",
                },
                "user_id": {
                    "type": "string",
                    "description": "사용자 ID (권한 확인용)",
                },
                "canvas_type": {
                    "type": "string",
                    "enum": list(CANVAS_TYPES),
                    "default": "all",
                    "description": "캔버스 타입 (markdown|chart|diagram|all)",
                },
            },
            "required": ["session_id", "user_id"],
        }

    async def execute(self, **kwargs) -> SkillResult:
        session_id: str = kwargs.get("session_id", "")
        user_id: str = kwargs.get("user_id", "")
        canvas_type: str = kwargs.get("canvas_type", "all")

        if not session_id or not user_id:
            return SkillResult(
                success=False,
                error="session_id와 user_id는 필수 입력값입니다.",
                data={},
            )

        if canvas_type not in CANVAS_TYPES:
            return SkillResult(
                success=False,
                error=f"지원하지 않는 canvas_type: {canvas_type}. 허용값: {CANVAS_TYPES}",
                data={},
            )

        # DB에서 연구 결과 로드 (ExportService 재사용)
        report = await _load_report(session_id, user_id)
        if not report:
            return SkillResult(
                success=False,
                error=f"세션을 찾을 수 없습니다: {session_id}",
                data={"session_id": session_id},
            )

        canvas_data = await _render_canvas(report, canvas_type)

        return SkillResult(
            success=True,
            data={
                "session_id": session_id,
                "canvas_type": canvas_type,
                **canvas_data,
                "message": f"캔버스 렌더링 완료 (타입: {canvas_type})",
            },
            metadata={
                "has_charts": bool(canvas_data.get("charts")),
                "has_diagram": bool(canvas_data.get("diagram")),
            },
        )


async def _load_report(session_id: str, user_id: str):
    """ExportService.get_research_report()를 통해 ResearchReport 반환 (CR-P6-05)."""
    try:
        from neos.api.services.export_service import export_service
        return await export_service.get_research_report(session_id, user_id)
    except Exception as e:
        logger.error(f"Failed to load report for session {session_id}: {e}", exc_info=True)
        return None


async def _render_canvas(report, canvas_type: str) -> Dict[str, Any]:
    """요청한 타입에 따라 렌더러를 선택적으로 실행."""
    from neos.skills.builtin.canvas.renderers import (
        StructuredMarkdownRenderer,
        ChartRenderer,
        MermaidDiagramRenderer,
    )

    result: Dict[str, Any] = {}
    want_all = canvas_type == "all"

    if want_all or canvas_type == "markdown":
        result["markdown"] = StructuredMarkdownRenderer().render(report)

    if want_all or canvas_type == "chart":
        result["charts"] = await asyncio.to_thread(ChartRenderer().render, report)

    if want_all or canvas_type == "diagram":
        result["diagram"] = MermaidDiagramRenderer().render(report)

    return result

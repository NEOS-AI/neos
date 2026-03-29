"""
Export API Handlers (Phase 3.4)

연구 세션을 Markdown/HTML/PDF로 내보내기
"""

import io
import logging

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse

from neos.api.dependencies.auth import get_current_user
from neos.database.models import User
from neos.api.services.export_service import export_service
from neos.exporters import ExportFormat

router = APIRouter(prefix="/api/v1/research", tags=["export"])
logger = logging.getLogger(__name__)


@router.get("/{session_id}/export")
async def export_research_report(
    session_id: str,
    format: str = "markdown",
    current_user: User = Depends(get_current_user),
):
    """연구 세션을 구조화된 리포트로 export

    Args:
        session_id: 연구 세션 ID
        format: 출력 형식 (markdown, html, pdf)
    """
    # 포맷 검증
    try:
        export_format = ExportFormat(format.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {format}. Use markdown, html, pdf, or canvas",
        )

    try:
        report_bytes = await export_service.export_research_session(
            session_id=session_id,
            format=export_format,
            user_id=current_user.user_id,
        )

        exporter = export_service.exporters[export_format]
        mime_type = exporter.get_mime_type()
        extension = exporter.get_file_extension()
        filename = f"research_report_{session_id}.{extension}"

        return StreamingResponse(
            io.BytesIO(report_bytes),
            media_type=mime_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ImportError as e:
        raise HTTPException(
            status_code=501,
            detail=f"Export dependency not installed: {e}",
        )
    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Export failed")

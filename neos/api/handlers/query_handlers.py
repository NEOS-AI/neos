"""시스템 헬스 체크 라우트.

이 라우터에는 레거시 쿼리 API(`/query`, `/trending`, `/related`, `/history`,
`/cache`, `/stats/system`, `/hyper-research`, `/ws/{session_id}`)가 있었다.
딥 하네스·코딩 루프로 대체되어 2026-09-27 에 걷어 냈고
(`tests/api/test_retired_routes.py`), 남은 것은 docker-compose 가 부르는
`/api/v1/health` 하나다.
"""

from fastapi import APIRouter, HTTPException

from neos.api.models.query_models import HealthCheckResponse
from neos.api.services.query_service import QueryService

router = APIRouter()


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """시스템 헬스 체크"""
    try:
        health_data = await QueryService.check_system_health()
        return HealthCheckResponse(**health_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")

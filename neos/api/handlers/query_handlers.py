"""Query API handlers - thin layer for FastAPI routes"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import List, Optional
import uuid

from neos.api.models.query_models import (
    QueryRequest,
    QueryResponse,
    HealthCheckResponse,
    TrendingQuery,
    RelatedQuery,
    HyperResearchReportResponse,
    HyperResearchReportsListResponse,
    HyperResearchReportSummary
)
from neos.api.services.query_service import QueryService
from neos.utils.cache import cache_manager

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def process_query(
    request: QueryRequest,
    background_tasks: BackgroundTasks
):
    """
    메인 쿼리 처리 엔드포인트
    멀티 에이전트 워크플로우를 실행하여 사용자 쿼리에 응답
    """
    try:
        # 세션 ID 생성
        session_id = request.session_id or str(uuid.uuid4())
        user_id = request.user_id or f"anonymous_{uuid.uuid4().hex[:8]}"

        # 사용자 생성/조회
        await QueryService.get_or_create_user(user_id)

        preferences = dict(request.preferences or {})
        if request.autonomy_level is not None:
            preferences["autonomy_level"] = request.autonomy_level

        # 워크플로우 실행
        result = await QueryService.process_query_workflow(
            user_id=user_id,
            session_id=session_id,
            query=request.query,
            bypass_cache=preferences.get("bypass_cache", False),
            preferences=preferences,
        )

        if result.get("interrupted"):
            return JSONResponse(status_code=202, content=result)

        # 응답 객체 생성
        response = QueryResponse(**result)

        # 백그라운드에서 쿼리 히스토리 저장
        background_tasks.add_task(
            QueryService.save_query_history_background,
            user_id=user_id,
            session_id=session_id,
            original_query=request.query,
            result=result,
            execution_time_ms=result["execution_time_ms"],
            channel_source=result.get("channel_source", "api")
        )

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """시스템 헬스 체크"""
    try:
        health_data = await QueryService.check_system_health()
        return HealthCheckResponse(**health_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@router.get("/trending", response_model=List[TrendingQuery])
async def get_trending_queries(
    time_period: str = "daily",
    limit: int = 10
):
    """인기 검색어 조회"""
    try:
        queries = await QueryService.get_trending_queries(time_period, limit)
        return [TrendingQuery(**q) for q in queries]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/related/{query_id}", response_model=List[RelatedQuery])
async def get_related_queries(query_id: int, limit: int = 5):
    """연관 검색어 조회"""
    try:
        queries = await QueryService.get_related_queries(query_id, limit)
        return [RelatedQuery(**q) for q in queries]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{user_id}")
async def get_user_query_history(
    user_id: str,
    limit: int = 20,
    offset: int = 0
):
    """사용자 쿼리 히스토리 조회"""
    try:
        return await QueryService.get_user_query_history(user_id, limit, offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/cache/{cache_key}")
async def clear_cache(cache_key: str):
    """특정 캐시 삭제"""
    try:
        success = await cache_manager.delete(cache_key)
        return {"success": success, "message": f"Cache key '{cache_key}' cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/system")
async def get_system_stats():
    """시스템 통계"""
    try:
        return await QueryService.get_system_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket, session_id: str):
    """실시간 쿼리 처리용 웹소켓"""
    from neos.workflow.graph import multi_agent_workflow

    await websocket.accept()

    try:
        while True:
            # 클라이언트로부터 메시지 수신
            data = await websocket.receive_json()

            if data.get("type") == "query":
                query = data.get("query")
                user_id = data.get("user_id", f"ws_{uuid.uuid4().hex[:8]}")

                # 진행 상황 전송
                await websocket.send_json({
                    "type": "status",
                    "message": "쿼리 처리 중...",
                    "progress": 10
                })

                # 워크플로우 실행
                try:
                    workflow_input = {
                        "user_id": user_id,
                        "session_id": session_id,
                        "query": query,
                        "autonomy_level": data.get("autonomy_level"),
                    }

                    # 진행 상황 업데이트
                    await websocket.send_json({
                        "type": "status",
                        "message": "에이전트들이 작업 중...",
                        "progress": 50
                    })

                    result = await multi_agent_workflow.execute_workflow(workflow_input)

                    if result["success"]:
                        await websocket.send_json({
                            "type": "result",
                            "response": result["response"],
                            "metadata": result["metadata"],
                            "quality_score": result["quality_score"]
                        })
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"처리 실패: {result.get('error', 'Unknown error')}"
                        })

                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"오류 발생: {str(e)}"
                    })

            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await websocket.close()


@router.get("/hyper-research/{report_uuid}", response_model=HyperResearchReportResponse)
async def get_hyper_research_report(report_uuid: str):
    """HyperDeepResearch 보고서 조회"""
    try:
        report = await QueryService.get_hyper_research_report(report_uuid)

        if not report:
            raise HTTPException(status_code=404, detail=f"Report not found: {report_uuid}")

        return HyperResearchReportResponse(**report)

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Failed to retrieve HyperResearch report: {e}")
        import traceback
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve report: {str(e)}")


@router.get("/hyper-research", response_model=HyperResearchReportsListResponse)
async def list_hyper_research_reports(
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """HyperDeepResearch 보고서 목록 조회"""
    try:
        result = await QueryService.list_hyper_research_reports(user_id, status, limit, offset)

        reports = [HyperResearchReportSummary(**r) for r in result["reports"]]

        return HyperResearchReportsListResponse(
            success=result["success"],
            reports=reports,
            total_count=result["total_count"]
        )

    except Exception as e:
        print(f"[ERROR] Failed to list HyperResearch reports: {e}")
        import traceback
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to list reports: {str(e)}")

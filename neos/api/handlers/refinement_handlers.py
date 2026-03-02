"""
Refinement API Handlers (Phase 3.8)

사용자가 mid-session에서 연구를 조정하는 API 엔드포인트
"""

import logging

from fastapi import APIRouter, HTTPException, Depends

from neos.api.dependencies.auth import get_current_user
from neos.database.models import User
from neos.api.models.refinement_models import (
    InvestigateClaimRequest,
    RejectSourceRequest,
    AdjustTrustRequest,
    RedirectResearchRequest,
    RequestMoreDetailRequest,
    RefinementResponse,
)
from neos.api.services.refinement_service import refinement_service

router = APIRouter(prefix="/api/v1/research/refine", tags=["research-refinement"])
logger = logging.getLogger(__name__)


@router.post("/investigate-claim", response_model=RefinementResponse)
async def investigate_claim(
    request: InvestigateClaimRequest,
    current_user: User = Depends(get_current_user),
):
    """특정 주장에 대해 추가 심층 조사 요청"""
    result = await refinement_service.investigate_claim(
        user_id=current_user.user_id,
        session_id=request.session_id,
        claim_text=request.claim_text,
        depth=request.depth,
    )
    return RefinementResponse(
        success=True,
        action="investigate_claim",
        message=f"Investigation submitted: {result['refined_query'][:80]}",
        session_id=request.session_id,
    )


@router.post("/reject-source", response_model=RefinementResponse)
async def reject_source(
    request: RejectSourceRequest,
    current_user: User = Depends(get_current_user),
):
    """특정 소스를 블랙리스트에 추가"""
    try:
        await refinement_service.reject_source(
            user_id=current_user.user_id,
            session_id=request.session_id,
            source_url=request.source_url,
            reason=request.reason or "",
        )
        return RefinementResponse(
            success=True,
            action="reject_source",
            message=f"Source blacklisted: {request.source_url}",
            session_id=request.session_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/adjust-trust", response_model=RefinementResponse)
async def adjust_trust(
    request: AdjustTrustRequest,
    current_user: User = Depends(get_current_user),
):
    """소스 신뢰도 조정"""
    if not (-1.0 <= request.trust_adjustment <= 1.0):
        raise HTTPException(
            status_code=400, detail="trust_adjustment must be between -1.0 and 1.0"
        )

    try:
        await refinement_service.adjust_trust(
            user_id=current_user.user_id,
            session_id=request.session_id,
            source_url=request.source_url,
            adjustment=request.trust_adjustment,
        )
        return RefinementResponse(
            success=True,
            action="adjust_trust",
            message=f"Trust adjusted: {request.source_url} ({request.trust_adjustment:+.2f})",
            session_id=request.session_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/redirect", response_model=RefinementResponse)
async def redirect_research(
    request: RedirectResearchRequest,
    current_user: User = Depends(get_current_user),
):
    """연구 방향 변경"""
    result = await refinement_service.redirect_research(
        user_id=current_user.user_id,
        session_id=request.session_id,
        new_direction=request.new_direction,
        keep_existing=request.keep_existing_results,
    )
    return RefinementResponse(
        success=True,
        action="redirect_research",
        message=f"Research redirected: {request.new_direction[:80]}",
        session_id=request.session_id,
    )


@router.post("/more-detail", response_model=RefinementResponse)
async def request_more_detail(
    request: RequestMoreDetailRequest,
    current_user: User = Depends(get_current_user),
):
    """특정 토픽에 대한 상세 연구 요청"""
    result = await refinement_service.request_more_detail(
        user_id=current_user.user_id,
        session_id=request.session_id,
        topic=request.topic,
    )
    return RefinementResponse(
        success=True,
        action="request_more_detail",
        message=f"Detail request submitted: {request.topic[:80]}",
        session_id=request.session_id,
    )

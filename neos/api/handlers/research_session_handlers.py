"""
Research Session API Handlers

연구 세션의 목록 조회, 상세 조회, 분기(branching) API를 제공합니다.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from neos.api.dependencies.auth import get_current_user
from neos.database.models import User
from neos.api.services.research_session_service import research_session_service

router = APIRouter(prefix="/api/v1/research/sessions", tags=["research-sessions"])


# ============================================================================
# Request/Response Models
# ============================================================================

class BranchSessionRequest(BaseModel):
    parent_session_id: str
    branch_query: str
    title: Optional[str] = None


class SessionSummary(BaseModel):
    session_id: str
    query: str
    user_id: str
    created_at: Optional[str] = None
    status: str = "completed"


class ListSessionsResponse(BaseModel):
    sessions: List[SessionSummary]
    total: int


class SessionDetailResponse(BaseModel):
    session_id: str
    checkpoint_exists: bool
    summary: Dict[str, Any]
    created_at: Optional[str] = None


class BranchSessionResponse(BaseModel):
    new_session_id: str
    parent_session_id: str


class BranchInfo(BaseModel):
    branch_session_id: str
    branch_query: Optional[str] = None
    title: Optional[str] = None
    created_at: Optional[str] = None


# ============================================================================
# Endpoints
# ============================================================================

@router.get("", response_model=ListSessionsResponse)
async def list_sessions(
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
):
    """연구 세션 목록을 조회합니다."""
    result = await research_session_service.list_sessions(
        user_id=current_user.user_id,
        limit=limit,
        offset=offset,
    )
    return result


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    """특정 연구 세션의 상세 정보를 조회합니다."""
    session = await research_session_service.get_session(
        session_id=session_id,
        user_id=current_user.user_id,
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionDetailResponse(
        session_id=session_id,
        checkpoint_exists=bool(session.get("checkpoint_data")),
        summary=session.get("summary", {}),
        created_at=session.get("created_at"),
    )


@router.post("/branch", status_code=201, response_model=BranchSessionResponse)
async def branch_session(
    req: BranchSessionRequest,
    current_user: User = Depends(get_current_user),
):
    """기존 세션에서 분기하여 새 연구 세션을 생성합니다."""
    try:
        new_session_id = await research_session_service.branch_session(
            parent_session_id=req.parent_session_id,
            branch_query=req.branch_query,
            user_id=current_user.user_id,
            title=req.title,
        )
        return BranchSessionResponse(
            new_session_id=new_session_id,
            parent_session_id=req.parent_session_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/branches", response_model=List[BranchInfo])
async def list_branches(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    """특정 세션의 분기 목록을 조회합니다."""
    branches = await research_session_service.list_branches(
        parent_session_id=session_id,
        user_id=current_user.user_id,
    )
    return branches

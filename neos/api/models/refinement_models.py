"""
Refinement Request/Response Models (Phase 3.8)
"""

from pydantic import BaseModel
from typing import Optional
from enum import Enum


class RefinementAction(str, Enum):
    INVESTIGATE_CLAIM = "investigate_claim"
    REJECT_SOURCE = "reject_source"
    ADJUST_TRUST = "adjust_trust"
    REDIRECT_RESEARCH = "redirect_research"
    REQUEST_MORE_DETAIL = "request_more_detail"


class InvestigateClaimRequest(BaseModel):
    session_id: str
    claim_text: str
    depth: str = "medium"  # shallow, medium, deep


class RejectSourceRequest(BaseModel):
    session_id: str
    source_url: str
    reason: Optional[str] = None


class AdjustTrustRequest(BaseModel):
    session_id: str
    source_url: str
    trust_adjustment: float  # -1.0 ~ +1.0


class RedirectResearchRequest(BaseModel):
    session_id: str
    new_direction: str
    keep_existing_results: bool = True


class RequestMoreDetailRequest(BaseModel):
    session_id: str
    topic: str


class RefinementResponse(BaseModel):
    success: bool
    action: str
    message: str
    session_id: str

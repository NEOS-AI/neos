"""
Research Template API Handlers (Phase 4.7)

연구 템플릿 목록 조회 및 적용 API를 제공합니다.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from neos.api.dependencies.auth import get_current_user
from neos.database.models import User
from neos.templates.research_templates import (
    RESEARCH_TEMPLATES,
    list_templates,
    get_template,
)

router = APIRouter(prefix="/api/v1/research/templates", tags=["research-templates"])


# ============================================================================
# Response Models
# ============================================================================


class TemplateParameterInfo(BaseModel):
    key: str
    description: str


class TemplateSummary(BaseModel):
    template_id: str
    name: str
    name_en: str
    description: str
    category: str
    output_format: str
    parameters: List[TemplateParameterInfo]


class ListTemplatesResponse(BaseModel):
    templates: List[TemplateSummary]
    total: int


class TemplateDetailResponse(BaseModel):
    template_id: str
    name: str
    name_en: str
    description: str
    category: str
    output_format: str
    parameters: List[TemplateParameterInfo]
    required_agents: List[str]
    recommended_skills: List[str]
    research_guidance: str


# ============================================================================
# Endpoints
# ============================================================================


@router.get("", response_model=ListTemplatesResponse)
async def list_research_templates(
    category: Optional[str] = Query(
        None, description="Filter by category: business, academic, technology, finance"
    ),
    current_user: User = Depends(get_current_user),
):
    """사용 가능한 연구 템플릿 목록"""
    templates = list_templates(category=category)

    summaries = []
    for t in templates:
        summaries.append(
            TemplateSummary(
                template_id=t.template_id,
                name=t.name,
                name_en=t.name_en,
                description=t.description,
                category=t.category,
                output_format=t.output_format,
                parameters=[
                    TemplateParameterInfo(key=k, description=v)
                    for k, v in t.parameter_schema.items()
                ],
            )
        )

    return ListTemplatesResponse(templates=summaries, total=len(summaries))


@router.get("/{template_id}", response_model=TemplateDetailResponse)
async def get_research_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
):
    """특정 연구 템플릿 상세 정보"""
    template = get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    return TemplateDetailResponse(
        template_id=template.template_id,
        name=template.name,
        name_en=template.name_en,
        description=template.description,
        category=template.category,
        output_format=template.output_format,
        parameters=[
            TemplateParameterInfo(key=k, description=v)
            for k, v in template.parameter_schema.items()
        ],
        required_agents=template.required_agents,
        recommended_skills=template.recommended_skills,
        research_guidance=template.research_guidance,
    )

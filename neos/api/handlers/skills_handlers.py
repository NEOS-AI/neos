"""Skills API handlers"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
import logging

from neos.skills.manager import skill_manager
from neos.skills.base import SkillType


logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== Request Models ====================


class ExecuteSkillRequest(BaseModel):
    """스킬 실행 요청"""

    skill_name: str = Field(..., description="스킬 이름")
    params: Dict[str, Any] = Field(default_factory=dict, description="실행 파라미터")


class InitializeSkillRequest(BaseModel):
    """스킬 초기화 요청"""

    skill_name: str = Field(..., description="스킬 이름")


# ==================== Response Models ====================


class SkillInfoResponse(BaseModel):
    """스킬 정보 응답"""

    name: str
    type: str
    description: str
    capabilities: List[str]
    version: str
    is_available: bool
    allowed_tools: Optional[str] = None


class SkillExecutionResponse(BaseModel):
    """스킬 실행 응답"""

    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    skill_name: Optional[str] = None


# ==================== API Endpoints ====================


@router.get("/skills", response_model=List[SkillInfoResponse])
async def list_skills(skill_type: Optional[str] = None):
    """스킬 목록 조회

    Args:
        skill_type: 스킬 타입 필터 (선택사항)

    Returns:
        스킬 정보 목록
    """
    try:
        # 스킬 타입 변환
        type_filter = None
        if skill_type:
            try:
                type_filter = SkillType(skill_type)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid skill type: {skill_type}"
                )

        # 스킬 목록 조회
        skills = skill_manager.get_available_skills(type_filter)

        return skills

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing skills: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# `/skills/prompt` 는 `/skills/{skill_name}` 보다 먼저 등록돼야 한다 --
# 뒤에 두면 "prompt" 가 스킬 이름으로 잡혀 이 핸들러에 닿지 않는다.
@router.get("/skills/prompt")
async def get_skills_prompt(
    skill_names: Optional[str] = None,
    include_body: bool = True,
    skill_type: Optional[str] = None,
):
    """Generate XML prompt for skills

    Args:
        skill_names: Comma-separated skill names (None = all)
        include_body: Include SKILL.md documentation body
        skill_type: Filter by skill type

    Returns:
        XML formatted skills prompt
    """
    try:
        names = skill_names.split(',') if skill_names else None
        stype = SkillType(skill_type) if skill_type else None

        prompt = skill_manager.generate_skills_prompt(
            skill_names=names,
            include_body=include_body,
            skill_type=stype,
        )

        return {"prompt": prompt}

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid skill_type: {skill_type}"
        )
    except Exception as e:
        logger.error(f"Error generating skills prompt: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/skills/{skill_name}", response_model=SkillInfoResponse)
async def get_skill(skill_name: str):
    """특정 스킬 정보 조회

    Args:
        skill_name: 스킬 이름

    Returns:
        스킬 정보
    """
    try:
        skill_info = skill_manager.get_skill_info(skill_name)

        if not skill_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{skill_name}' not found"
            )

        return skill_info

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting skill info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/skills/{skill_name}/initialize")
async def initialize_skill(skill_name: str):
    """스킬 초기화

    Args:
        skill_name: 스킬 이름

    Returns:
        초기화 성공 여부
    """
    try:
        success = await skill_manager.initialize_skill(skill_name)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to initialize skill '{skill_name}'"
            )

        return {
            "success": True,
            "message": f"Skill '{skill_name}' initialized successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error initializing skill: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/skills/{skill_name}/execute", response_model=SkillExecutionResponse)
async def execute_skill(skill_name: str, request: ExecuteSkillRequest):
    """스킬 실행

    Args:
        skill_name: 스킬 이름
        request: 실행 요청 (파라미터 포함)

    Returns:
        실행 결과
    """
    try:
        # 스킬 실행
        result = await skill_manager.execute_skill(skill_name, request.params)

        return {
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "metadata": result.metadata,
            "skill_name": result.skill_name,
        }

    except Exception as e:
        logger.error(f"Error executing skill: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/skills/{skill_name}/cleanup")
async def cleanup_skill(skill_name: str):
    """스킬 정리

    Args:
        skill_name: 스킬 이름

    Returns:
        정리 성공 여부
    """
    try:
        success = await skill_manager.cleanup_skill(skill_name)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to cleanup skill '{skill_name}'"
            )

        return {
            "success": True,
            "message": f"Skill '{skill_name}' cleaned up successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cleaning up skill: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/skills/types/list")
async def list_skill_types():
    """사용 가능한 스킬 타입 목록

    Returns:
        스킬 타입 목록
    """
    try:
        types = [t.value for t in SkillType]
        return {"skill_types": types}

    except Exception as e:
        logger.error(f"Error listing skill types: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/skills/initialize-all")
async def initialize_all_skills():
    """모든 스킬 초기화

    Returns:
        초기화 결과
    """
    try:
        results = await skill_manager.initialize_all()

        return {
            "success": True,
            "message": f"Initialized {sum(results.values())}/{len(results)} skills",
            "results": results
        }

    except Exception as e:
        logger.error(f"Error initializing all skills: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/skills/validate")
async def validate_skill_metadata(
    metadata: Dict[str, Any],
    skill_dir_name: Optional[str] = None,
):
    """Validate skill metadata without loading skill

    Args:
        metadata: Skill metadata dictionary (frontmatter)
        skill_dir_name: Optional directory name for validation

    Returns:
        Validation result with errors if any
    """
    try:
        from neos.skills.base.validator import validate_metadata
        from pathlib import Path

        skill_dir = Path(skill_dir_name) if skill_dir_name else None
        errors = validate_metadata(metadata, skill_dir)

        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }

    except Exception as e:
        logger.error(f"Error validating metadata: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

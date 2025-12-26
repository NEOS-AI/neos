"""SKILL.md 메타데이터 파서

SKILL.md 파일의 YAML frontmatter를 파싱하여 스킬 메타데이터를 추출합니다.
"""

from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import logging
import re
import yaml

from .errors import SkillValidationError, SkillParseError


logger = logging.getLogger(__name__)


class SkillMetadataError(Exception):
    """스킬 메타데이터 관련 에러 (backward compatibility)"""
    pass


def parse_skill_metadata(
    skill_dir: Path, include_body: bool = True
) -> Dict[str, Any]:
    """SKILL.md 파일에서 메타데이터 파싱

    YAML frontmatter 형식:
    ---
    name: pdf
    type: document
    version: 1.0.0
    description: PDF 문서 읽기, 텍스트 추출, 생성
    capabilities:
      - document_reading
      - text_extraction
    dependencies:
      - PyPDF2>=3.0.0
    allowed_tools: "Read, Write"  # Optional
    ---

    Args:
        skill_dir: 스킬 디렉토리 경로
        include_body: True이면 body를 metadata['_body']에 포함

    Returns:
        파싱된 메타데이터 딕셔너리

    Raises:
        SkillMetadataError: 파싱 실패 또는 필수 필드 누락 (backward compatibility)
        SkillParseError: YAML 파싱 실패
        SkillValidationError: Validation 실패
    """
    skill_md_path = skill_dir / "SKILL.md"

    if not skill_md_path.exists():
        raise SkillMetadataError(
            f"SKILL.md not found in {skill_dir}"
        )

    try:
        with open(skill_md_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        raise SkillMetadataError(
            f"Failed to read SKILL.md in {skill_dir}: {e}"
        )

    # YAML frontmatter와 body 추출
    frontmatter, body = extract_frontmatter(content)

    if not frontmatter:
        raise SkillParseError(
            f"No YAML frontmatter found in {skill_md_path}. "
            "Make sure the file starts with '---' and contains valid YAML."
        )

    # YAML 파싱
    try:
        metadata = yaml.safe_load(frontmatter)
    except yaml.YAMLError as e:
        raise SkillParseError(
            f"Invalid YAML in {skill_md_path}: {e}"
        )

    if not isinstance(metadata, dict):
        raise SkillParseError(
            f"YAML frontmatter in {skill_md_path} must be a dictionary"
        )

    # 메타데이터 검증 (strict mode)
    from .validator import validate_metadata as validate_strict
    validation_errors = validate_strict(metadata, skill_dir)

    if validation_errors:
        raise SkillValidationError(
            f"Validation failed for {skill_dir}",
            errors=validation_errors
        )

    # 기본값 설정
    metadata.setdefault('version', '1.0.0')
    metadata.setdefault('dependencies', [])
    metadata.setdefault('allowed_tools', None)

    # Body 포함
    if include_body and body:
        metadata['_body'] = body

    logger.info(
        f"Successfully parsed metadata for skill '{metadata.get('name')}' "
        f"from {skill_md_path}"
    )

    return metadata


def extract_frontmatter(content: str) -> Tuple[Optional[str], Optional[str]]:
    """마크다운 콘텐츠에서 YAML frontmatter와 body 추출

    Args:
        content: 마크다운 파일 내용

    Returns:
        (frontmatter_yaml, body_markdown) tuple. 없으면 (None, None)
    """
    # Frontmatter는 파일 시작부터 --- 사이에 있어야 함
    pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
    match = re.match(pattern, content, re.DOTALL)

    if match:
        return match.group(1), match.group(2).strip()

    return None, None


def validate_metadata(metadata: Dict[str, Any], file_path: Path = None) -> bool:
    """메타데이터 유효성 검사

    필수 필드:
    - name: str
    - type: str
    - description: str
    - capabilities: list

    선택 필드:
    - version: str (기본값: "1.0.0")
    - dependencies: list (기본값: [])

    Args:
        metadata: 검증할 메타데이터
        file_path: 파일 경로 (에러 메시지용, 선택)

    Returns:
        검증 성공 여부

    Raises:
        SkillMetadataError: 필수 필드 누락 또는 타입 오류
    """
    file_info = f" in {file_path}" if file_path else ""

    # 필수 필드 확인
    required_fields = {
        'name': str,
        'type': str,
        'description': str,
        'capabilities': list,
    }

    for field, expected_type in required_fields.items():
        if field not in metadata:
            raise SkillMetadataError(
                f"Required field '{field}' missing{file_info}"
            )

        if not isinstance(metadata[field], expected_type):
            raise SkillMetadataError(
                f"Field '{field}' must be {expected_type.__name__}, "
                f"got {type(metadata[field]).__name__}{file_info}"
            )

    # name 검증
    if not metadata['name'].strip():
        raise SkillMetadataError(
            f"Field 'name' cannot be empty{file_info}"
        )

    # type 검증 (유효한 SkillType인지)
    valid_types = [
        'document', 'data_analysis', 'api_integration',
        'code', 'research', 'content_generation',
        'database', 'custom'
    ]
    if metadata['type'] not in valid_types:
        raise SkillMetadataError(
            f"Field 'type' must be one of {valid_types}, "
            f"got '{metadata['type']}'{file_info}"
        )

    # capabilities 검증
    if not metadata['capabilities']:
        raise SkillMetadataError(
            f"Field 'capabilities' cannot be empty{file_info}"
        )

    for cap in metadata['capabilities']:
        if not isinstance(cap, str):
            raise SkillMetadataError(
                f"All capabilities must be strings{file_info}"
            )

    # 선택 필드 검증
    if 'version' in metadata:
        if not isinstance(metadata['version'], str):
            raise SkillMetadataError(
                f"Field 'version' must be a string{file_info}"
            )

    if 'dependencies' in metadata:
        if not isinstance(metadata['dependencies'], list):
            raise SkillMetadataError(
                f"Field 'dependencies' must be a list{file_info}"
            )

        for dep in metadata['dependencies']:
            if not isinstance(dep, str):
                raise SkillMetadataError(
                    f"All dependencies must be strings{file_info}"
                )

    logger.debug(f"Metadata validation passed{file_info}")
    return True


def get_skill_metadata_summary(metadata: Dict[str, Any]) -> str:
    """메타데이터 요약 문자열 생성

    Args:
        metadata: 스킬 메타데이터

    Returns:
        요약 문자열
    """
    return (
        f"Skill: {metadata.get('name', 'Unknown')} "
        f"(Type: {metadata.get('type', 'unknown')}, "
        f"Version: {metadata.get('version', '1.0.0')})\n"
        f"Description: {metadata.get('description', 'No description')}\n"
        f"Capabilities: {', '.join(metadata.get('capabilities', []))}\n"
        f"Dependencies: {len(metadata.get('dependencies', []))} packages"
    )

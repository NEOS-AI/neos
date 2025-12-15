"""스킬 의존성 체커

스킬의 requirements.txt 또는 메타데이터의 dependencies를 확인하여
필요한 패키지가 설치되어 있는지 검증합니다.
"""

from pathlib import Path
from typing import List, Tuple, Optional
import logging
import importlib.util
import re


logger = logging.getLogger(__name__)


def check_dependencies(requirements: List[str]) -> Tuple[bool, List[str]]:
    """패키지 의존성 확인

    Args:
        requirements: 패키지 요구사항 리스트 (예: ["PyPDF2>=3.0.0", "reportlab"])

    Returns:
        (전체 성공 여부, 누락된 패키지 리스트)
    """
    missing_packages = []

    for requirement in requirements:
        # 공백 제거 및 빈 줄 스킵
        requirement = requirement.strip()
        if not requirement or requirement.startswith('#'):
            continue

        # 패키지명과 버전 분리
        package_name, version_spec = parse_requirement(requirement)

        # 패키지 설치 여부 확인
        if not check_package_installed(package_name):
            missing_packages.append(requirement)
            logger.debug(f"Package not found: {package_name}")
        else:
            logger.debug(f"Package found: {package_name}")

    all_satisfied = len(missing_packages) == 0

    if all_satisfied:
        logger.info(f"All {len(requirements)} dependencies satisfied")
    else:
        logger.warning(
            f"{len(missing_packages)}/{len(requirements)} dependencies missing: "
            f"{missing_packages}"
        )

    return all_satisfied, missing_packages


def check_skill_dependencies(skill_dir: Path) -> Tuple[bool, List[str]]:
    """스킬 디렉토리의 requirements.txt 확인

    Args:
        skill_dir: 스킬 디렉토리 경로

    Returns:
        (전체 성공 여부, 누락된 패키지 리스트)
    """
    requirements_file = skill_dir / "requirements.txt"

    if not requirements_file.exists():
        logger.debug(f"No requirements.txt found in {skill_dir}")
        return True, []

    try:
        with open(requirements_file, 'r', encoding='utf-8') as f:
            requirements = f.readlines()
    except Exception as e:
        logger.error(f"Failed to read requirements.txt in {skill_dir}: {e}")
        return False, []

    # 빈 줄과 주석 제거
    requirements = [
        req.strip() for req in requirements
        if req.strip() and not req.strip().startswith('#')
    ]

    if not requirements:
        logger.debug(f"Empty requirements.txt in {skill_dir}")
        return True, []

    logger.info(f"Checking {len(requirements)} dependencies for {skill_dir.name}")
    return check_dependencies(requirements)


def check_package_installed(package_name: str) -> bool:
    """패키지 설치 여부 확인

    Args:
        package_name: 패키지명 (예: "PyPDF2", "reportlab")

    Returns:
        설치 여부
    """
    # 패키지명 정규화 (언더스코어 -> 하이픈)
    normalized_name = normalize_package_name(package_name)

    # 두 가지 방법으로 확인
    # 1. importlib.util로 확인
    try:
        spec = importlib.util.find_spec(normalized_name)
        if spec is not None:
            return True
    except (ImportError, ModuleNotFoundError, ValueError):
        pass

    # 2. 직접 import 시도 (일부 패키지는 find_spec으로 찾지 못함)
    try:
        __import__(normalized_name)
        return True
    except (ImportError, ModuleNotFoundError):
        pass

    # 3. 원본 이름으로도 시도
    if normalized_name != package_name:
        try:
            spec = importlib.util.find_spec(package_name)
            if spec is not None:
                return True
        except (ImportError, ModuleNotFoundError, ValueError):
            pass

        try:
            __import__(package_name)
            return True
        except (ImportError, ModuleNotFoundError):
            pass

    return False


def parse_requirement(requirement_str: str) -> Tuple[str, Optional[str]]:
    """요구사항 문자열 파싱

    Examples:
        "PyPDF2>=3.0.0" → ("PyPDF2", ">=3.0.0")
        "reportlab" → ("reportlab", None)
        "requests[security]>=2.20.0" → ("requests", ">=2.20.0")

    Args:
        requirement_str: 요구사항 문자열

    Returns:
        (패키지명, 버전 스펙)
    """
    # 정규식으로 패키지명과 버전 분리
    # 패턴: package_name[extras]version_spec
    pattern = r'^([a-zA-Z0-9_-]+)(?:\[.*?\])?(.*?)$'
    match = re.match(pattern, requirement_str.strip())

    if not match:
        # 파싱 실패시 전체를 패키지명으로 간주
        return requirement_str.strip(), None

    package_name = match.group(1).strip()
    version_spec = match.group(2).strip() if match.group(2) else None

    return package_name, version_spec


def normalize_package_name(package_name: str) -> str:
    """패키지명 정규화

    PyPI 패키지명은 대소문자 구분 없고, 하이픈/언더스코어/점을 동일하게 취급

    Args:
        package_name: 원본 패키지명

    Returns:
        정규화된 패키지명
    """
    # 소문자 변환 및 하이픈을 언더스코어로 변환
    normalized = package_name.lower().replace('-', '_').replace('.', '_')
    return normalized


def get_dependency_summary(skill_dir: Path) -> str:
    """스킬 의존성 요약 생성

    Args:
        skill_dir: 스킬 디렉토리 경로

    Returns:
        의존성 요약 문자열
    """
    requirements_file = skill_dir / "requirements.txt"

    if not requirements_file.exists():
        return "No dependencies"

    try:
        with open(requirements_file, 'r', encoding='utf-8') as f:
            requirements = [
                line.strip() for line in f
                if line.strip() and not line.strip().startswith('#')
            ]
    except Exception as e:
        return f"Error reading dependencies: {e}"

    all_satisfied, missing = check_dependencies(requirements)

    if all_satisfied:
        return f"{len(requirements)} dependencies (all satisfied)"
    else:
        return (
            f"{len(requirements)} dependencies "
            f"({len(missing)} missing: {', '.join(missing[:3])}...)"
        )


def validate_requirements_file(skill_dir: Path) -> Tuple[bool, str]:
    """requirements.txt 파일 유효성 검사

    Args:
        skill_dir: 스킬 디렉토리 경로

    Returns:
        (유효성 여부, 메시지)
    """
    requirements_file = skill_dir / "requirements.txt"

    if not requirements_file.exists():
        return True, "No requirements.txt file"

    try:
        with open(requirements_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        return False, f"Failed to read file: {e}"

    if not lines:
        return True, "Empty requirements file"

    # 각 줄 검증
    invalid_lines = []
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # 기본적인 형식 검증
        if not re.match(r'^[a-zA-Z0-9_\-\[\].]+.*$', line):
            invalid_lines.append((i, line))

    if invalid_lines:
        invalid_str = ", ".join(
            [f"line {i}: '{line}'" for i, line in invalid_lines[:3]]
        )
        return False, f"Invalid requirement format: {invalid_str}"

    return True, f"Valid requirements file with {len(lines)} lines"

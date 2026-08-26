"""스킬 자동 발견 모듈

스킬 디렉토리를 스캔하여 SKILL.md와 skill.py가 있는 스킬들을 자동으로 발견하고 로드합니다.
"""

from pathlib import Path
from typing import List, Type, Optional
import logging
import importlib.util
import sys
import inspect

from neos.skills.base import BaseSkill, SkillType, parse_skill_metadata, SkillMetadataError
from neos.skills.manager.skill_registry import SkillInfo
from neos.skills.manager.dependency_checker import check_skill_dependencies


logger = logging.getLogger(__name__)


def discover_skills(
    skills_dir: Path,
    check_deps: bool = True,
    skip_on_missing_deps: bool = False
) -> List[SkillInfo]:
    """스킬 디렉토리 스캔 및 자동 발견

    Args:
        skills_dir: 스킬이 있는 디렉토리 경로
        check_deps: 의존성 체크 수행 여부
        skip_on_missing_deps: 의존성 누락 시 스킬 스킵 여부

    Returns:
        발견된 스킬들의 SkillInfo 리스트
    """
    if not skills_dir.exists():
        logger.warning(f"Skills directory not found: {skills_dir}")
        return []

    if not skills_dir.is_dir():
        logger.error(f"Skills path is not a directory: {skills_dir}")
        return []

    discovered_skills = []
    logger.info(f"Scanning for skills in: {skills_dir}")

    # 디렉토리 순회
    for skill_dir in sorted(skills_dir.iterdir()):
        # 디렉토리가 아니거나 _로 시작하면 스킵
        if not skill_dir.is_dir() or skill_dir.name.startswith('_'):
            continue

        logger.debug(f"Checking directory: {skill_dir.name}")

        try:
            skill_info = discover_single_skill(
                skill_dir,
                check_deps=check_deps,
                skip_on_missing_deps=skip_on_missing_deps
            )

            if skill_info:
                discovered_skills.append(skill_info)
                logger.info(f"✓ Discovered skill: {skill_info.name} ({skill_info.skill_type.value})")

        except Exception as e:
            logger.error(f"✗ Failed to discover skill in {skill_dir.name}: {e}", exc_info=True)
            continue

    logger.info(f"Total discovered: {len(discovered_skills)} skills")
    return discovered_skills


def discover_single_skill(
    skill_dir: Path,
    check_deps: bool = True,
    skip_on_missing_deps: bool = False
) -> Optional[SkillInfo]:
    """단일 스킬 디렉토리에서 스킬 발견

    Args:
        skill_dir: 스킬 디렉토리 경로
        check_deps: 의존성 체크 수행 여부
        skip_on_missing_deps: 의존성 누락 시 None 반환

    Returns:
        SkillInfo 객체 또는 None
    """
    skill_md_path = skill_dir / "SKILL.md"
    skill_py_path = skill_dir / "skill.py"

    # 필수 파일 확인
    if not skill_md_path.exists():
        logger.debug(f"No SKILL.md in {skill_dir.name}")
        return None

    if not skill_py_path.exists():
        logger.debug(f"No skill.py in {skill_dir.name}")
        return None

    # 1. SKILL.md에서 메타데이터 파싱
    try:
        metadata = parse_skill_metadata(skill_dir)
    except SkillMetadataError as e:
        logger.error(f"Metadata parsing failed for {skill_dir.name}: {e}")
        raise

    # 2. 의존성 체크 (선택적)
    if check_deps:
        deps_ok, missing_deps = check_skill_dependencies(skill_dir)
        if not deps_ok:
            logger.warning(
                f"Skill '{metadata['name']}' has missing dependencies: {missing_deps}"
            )
            if skip_on_missing_deps:
                logger.info(f"Skipping skill '{metadata['name']}' due to missing dependencies")
                return None

    # 3. skill.py에서 스킬 클래스 로드
    try:
        skill_class = load_skill_class(skill_py_path, metadata['name'])
    except Exception as e:
        logger.error(f"Failed to load skill class from {skill_py_path}: {e}")
        raise

    # 4. SkillInfo 생성
    try:
        skill_info = SkillInfo(
            name=metadata['name'],
            skill_class=skill_class,
            skill_type=SkillType(metadata['type']),
            description=metadata['description'],
            capabilities=metadata['capabilities'],
            version=metadata.get('version', '1.0.0'),
            skill_dir=skill_dir
        )
    except Exception as e:
        logger.error(f"Failed to create SkillInfo for {metadata['name']}: {e}")
        raise

    return skill_info


def load_skill_class(skill_py_path: Path, expected_name: str) -> Type[BaseSkill]:
    """skill.py 파일에서 스킬 클래스 동적 로드

    Args:
        skill_py_path: skill.py 파일 경로
        expected_name: 예상 스킬 이름 (로깅용)

    Returns:
        BaseSkill을 상속한 클래스

    Raises:
        ImportError: 모듈 로드 실패
        ValueError: BaseSkill을 상속한 클래스를 찾지 못함
    """
    # 모듈명 생성 (예: neos.skills.builtin.pdf.skill)
    module_name = f"neos.skills.{skill_py_path.parent.parent.name}.{skill_py_path.parent.name}.skill"

    logger.debug(f"Loading module: {module_name} from {skill_py_path}")

    # 이미 로드된 모듈이면 재사용
    if module_name in sys.modules:
        logger.debug(f"Module already loaded: {module_name}")
        module = sys.modules[module_name]
    else:
        # 1) 먼저 **정상 패키지 import** 를 시도한다.
        #
        # `spec_from_file_location` 으로 만든 모듈은 `__package__` 가 잡히지 않아
        # 상대 import(`from .parser import ...`)가 부모 패키지를 찾지 못한다.
        # `cron` 이 헬퍼 모듈을 가진 유일한 스킬이라 이 경로에서만 깨졌고,
        # `import neos.skills.builtin.cron.skill` 은 멀쩡히 성공하는데 discovery
        # 만 실패해 원인이 늦게 드러났다. 상대 import 는 정상적인 파이썬이므로
        # 고칠 곳은 스킬이 아니라 로더다.
        #
        # 2) 실패하면 기존 파일 경로 로드로 폴백한다 -- `discover_skills` 는
        # `skills_dir` 를 인자로 받으므로 패키지 트리 **밖** 의 디렉터리도
        # 지원해야 하고, 그 경우 dotted path 가 실제 패키지에 대응하지 않는다.
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            module = None

        if module is not None:
            logger.debug(f"Imported as package: {module_name}")
            return _require_skill_class(module, skill_py_path)

        # 동적 모듈 로드 (패키지 트리 밖의 스킬)
        spec = importlib.util.spec_from_file_location(module_name, skill_py_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Failed to create module spec for {skill_py_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            # 로드 실패 시 sys.modules에서 제거
            del sys.modules[module_name]
            raise ImportError(f"Failed to execute module {module_name}: {e}")

    return _require_skill_class(module, skill_py_path)


def _require_skill_class(module, skill_py_path: Path) -> Type[BaseSkill]:
    """로드된 모듈에서 `BaseSkill` 하위 클래스를 꺼낸다. 없으면 거절한다.

    두 로드 경로(패키지 import / 파일 경로)가 같은 판정을 쓰도록 따로 뺐다 --
    한쪽만 검사하면 그쪽으로 들어온 스킬만 조용히 통과한다.
    """

    skill_class = find_skill_class_in_module(module)

    if skill_class is None:
        raise ValueError(
            f"No BaseSkill subclass found in {skill_py_path}. "
            f"Make sure your skill class inherits from BaseSkill."
        )

    logger.debug(f"Found skill class: {skill_class.__name__}")
    return skill_class


def find_skill_class_in_module(module) -> Optional[Type[BaseSkill]]:
    """모듈에서 BaseSkill을 상속한 클래스 찾기

    Args:
        module: 검사할 모듈

    Returns:
        BaseSkill 서브클래스 또는 None
    """
    for name, obj in inspect.getmembers(module, inspect.isclass):
        # BaseSkill 자체는 제외
        if obj is BaseSkill:
            continue

        # BaseSkill을 상속했는지 확인
        if issubclass(obj, BaseSkill):
            # 해당 모듈에서 정의된 클래스인지 확인 (import된 것 제외)
            if obj.__module__ == module.__name__:
                return obj

    return None


def list_potential_skill_directories(skills_dir: Path) -> List[Path]:
    """스킬이 있을 가능성이 있는 디렉토리 목록

    SKILL.md 또는 skill.py가 있는 디렉토리를 반환합니다.

    Args:
        skills_dir: 스캔할 디렉토리

    Returns:
        잠재적 스킬 디렉토리 리스트
    """
    if not skills_dir.exists() or not skills_dir.is_dir():
        return []

    potential_dirs = []

    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith('_'):
            continue

        # SKILL.md 또는 skill.py가 있으면 추가
        if (skill_dir / "SKILL.md").exists() or (skill_dir / "skill.py").exists():
            potential_dirs.append(skill_dir)

    return potential_dirs


def validate_skill_directory(skill_dir: Path) -> tuple[bool, str]:
    """스킬 디렉토리 유효성 검사

    Args:
        skill_dir: 검사할 디렉토리

    Returns:
        (유효성 여부, 메시지)
    """
    if not skill_dir.exists():
        return False, "Directory does not exist"

    if not skill_dir.is_dir():
        return False, "Path is not a directory"

    skill_md = skill_dir / "SKILL.md"
    skill_py = skill_dir / "skill.py"

    if not skill_md.exists():
        return False, "Missing SKILL.md"

    if not skill_py.exists():
        return False, "Missing skill.py"

    # SKILL.md 파싱 시도
    try:
        parse_skill_metadata(skill_dir)
    except SkillMetadataError as e:
        return False, f"Invalid SKILL.md: {e}"

    # skill.py 기본 검증 (파일 읽기)
    try:
        with open(skill_py, 'r', encoding='utf-8') as f:
            content = f.read()
            if 'BaseSkill' not in content:
                return False, "skill.py does not appear to contain a BaseSkill subclass"
    except Exception as e:
        return False, f"Failed to read skill.py: {e}"

    return True, "Valid skill directory"


def get_discovery_report(skills_dir: Path) -> str:
    """스킬 발견 리포트 생성

    Args:
        skills_dir: 스캔할 디렉토리

    Returns:
        발견 리포트 문자열
    """
    if not skills_dir.exists():
        return f"Directory not found: {skills_dir}"

    potential_dirs = list_potential_skill_directories(skills_dir)
    report_lines = [
        f"Skill Discovery Report for: {skills_dir}",
        f"=" * 60,
        f"Found {len(potential_dirs)} potential skill directories:",
        ""
    ]

    for skill_dir in potential_dirs:
        valid, message = validate_skill_directory(skill_dir)
        status = "✓" if valid else "✗"
        report_lines.append(f"{status} {skill_dir.name}: {message}")

    return "\n".join(report_lines)

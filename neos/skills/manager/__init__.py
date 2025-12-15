"""Skills Manager and Registry"""

from .skill_registry import SkillRegistry, SkillInfo
from .skill_manager import SkillManager, skill_manager
from .dependency_checker import (
    check_dependencies,
    check_skill_dependencies,
    check_package_installed,
    parse_requirement,
    normalize_package_name,
    get_dependency_summary,
    validate_requirements_file,
)
from .auto_discovery import (
    discover_skills,
    discover_single_skill,
    load_skill_class,
    find_skill_class_in_module,
    list_potential_skill_directories,
    validate_skill_directory,
    get_discovery_report,
)

__all__ = [
    "SkillRegistry",
    "SkillInfo",
    "SkillManager",
    "skill_manager",
    "check_dependencies",
    "check_skill_dependencies",
    "check_package_installed",
    "parse_requirement",
    "normalize_package_name",
    "get_dependency_summary",
    "validate_requirements_file",
    "discover_skills",
    "discover_single_skill",
    "load_skill_class",
    "find_skill_class_in_module",
    "list_potential_skill_directories",
    "validate_skill_directory",
    "get_discovery_report",
]

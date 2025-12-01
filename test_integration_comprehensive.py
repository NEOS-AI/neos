#!/usr/bin/env python3
"""Comprehensive Integration and Code Quality Check"""

import sys
from pathlib import Path
import importlib

# Add neos to path
sys.path.insert(0, str(Path(__file__).parent))


class IntegrationChecker:
    """통합 검증 체커"""

    def __init__(self):
        self.checks_passed = 0
        self.checks_failed = 0
        self.issues = []

    def check(self, name: str, condition: bool, error_msg: str = ""):
        """체크 수행"""
        if condition:
            self.checks_passed += 1
            print(f"✅ {name}")
            return True
        else:
            self.checks_failed += 1
            self.issues.append((name, error_msg))
            print(f"❌ {name}")
            if error_msg:
                print(f"   Issue: {error_msg}")
            return False

    def print_summary(self):
        """결과 요약 출력"""
        print("\n" + "="*70)
        print("INTEGRATION CHECK SUMMARY")
        print("="*70)
        print(f"Total Checks: {self.checks_passed + self.checks_failed}")
        print(f"Passed: {self.checks_passed}")
        print(f"Failed: {self.checks_failed}")
        print(f"Success Rate: {(self.checks_passed/(self.checks_passed+self.checks_failed)*100):.1f}%")

        if self.issues:
            print("\nIssues Found:")
            for name, error in self.issues:
                print(f"  - {name}: {error}")

        print("="*70)


checker = IntegrationChecker()


def check_module_structure():
    """모듈 구조 검증"""
    print("\n[1] Module Structure Check")
    print("-" * 70)

    # Check base module
    try:
        from neos.skills import base
        checker.check("neos.skills.base module exists", True)
        checker.check("BaseSkill exists", hasattr(base, 'BaseSkill'))
        checker.check("SkillResult exists", hasattr(base, 'SkillResult'))
        checker.check("SkillType exists", hasattr(base, 'SkillType'))
    except Exception as e:
        checker.check("neos.skills.base module import", False, str(e))

    # Check manager module
    try:
        from neos.skills import manager
        checker.check("neos.skills.manager module exists", True)
        checker.check("SkillManager exists", hasattr(manager, 'SkillManager'))
        checker.check("SkillRegistry exists", hasattr(manager, 'SkillRegistry'))
        checker.check("SkillInfo exists", hasattr(manager, 'SkillInfo'))
        checker.check("skill_manager instance exists", hasattr(manager, 'skill_manager'))
    except Exception as e:
        checker.check("neos.skills.manager module import", False, str(e))

    # Check builtin module
    try:
        from neos.skills import builtin
        checker.check("neos.skills.builtin module exists", True)
        checker.check("get_builtin_skills exists", hasattr(builtin, 'get_builtin_skills'))
        checker.check("BigQuerySkill exists", hasattr(builtin, 'BigQuerySkill'))
        checker.check("DocxSkill exists", hasattr(builtin, 'DocxSkill'))
        checker.check("PdfSkill exists", hasattr(builtin, 'PdfSkill'))
        checker.check("ResearchAssistantSkill exists", hasattr(builtin, 'ResearchAssistantSkill'))
    except Exception as e:
        checker.check("neos.skills.builtin module import", False, str(e))


def check_skill_files():
    """스킬 파일 존재 확인"""
    print("\n[2] Skill Files Check")
    print("-" * 70)

    skills_dir = Path("neos/skills")

    # Check base files
    base_files = [
        "base/__init__.py",
        "base/skill.py",
        "base/result.py",
        "base/types.py"
    ]

    for file_path in base_files:
        full_path = skills_dir / file_path
        checker.check(f"File exists: {file_path}", full_path.exists())

    # Check manager files
    manager_files = [
        "manager/__init__.py",
        "manager/skill_manager.py",
        "manager/skill_registry.py"
    ]

    for file_path in manager_files:
        full_path = skills_dir / file_path
        checker.check(f"File exists: {file_path}", full_path.exists())

    # Check builtin skills
    builtin_skills = ["bigquery", "docx", "pdf", "research_assistant"]

    for skill in builtin_skills:
        skill_dir = skills_dir / "builtin" / skill
        checker.check(f"Skill dir exists: {skill}", skill_dir.exists())
        checker.check(f"Skill has __init__.py: {skill}", (skill_dir / "__init__.py").exists())
        checker.check(f"Skill has skill.py: {skill}", (skill_dir / "skill.py").exists())
        checker.check(f"Skill has SKILL.md: {skill}", (skill_dir / "SKILL.md").exists())

    # Check README
    checker.check("README.md exists", (skills_dir / "README.md").exists())


def check_api_integration():
    """API 통합 확인"""
    print("\n[3] API Integration Check")
    print("-" * 70)

    # Check API handler
    api_handler = Path("neos/api/handlers/skills_handlers.py")
    checker.check("Skills API handler exists", api_handler.exists())

    try:
        # Check main.py integration
        main_file = Path("neos/main.py")
        with open(main_file, 'r') as f:
            main_content = f.read()

        checker.check(
            "Skills router imported in main.py",
            "from neos.api.handlers.skills_handlers import router as skills_router" in main_content
        )

        checker.check(
            "Skills router registered in main.py",
            'app.include_router(skills_router' in main_content
        )

        checker.check(
            "Skills initialization in lifespan",
            "skill_manager.register_builtin_skills()" in main_content
        )

    except Exception as e:
        checker.check("main.py integration check", False, str(e))


def check_workflow_integration():
    """Workflow 통합 확인"""
    print("\n[4] Workflow Integration Check")
    print("-" * 70)

    try:
        # Check executors.py
        executors_file = Path("neos/workflow/builder/executors.py")
        with open(executors_file, 'r') as f:
            executors_content = f.read()

        checker.check(
            "skill_manager imported in executors",
            "from neos.skills.manager import skill_manager" in executors_content
        )

        checker.check(
            "execute_skill method exists in NodeExecutor",
            "async def execute_skill(" in executors_content
        )

        # Check workflow_executor.py
        workflow_executor_file = Path("neos/workflow/builder/workflow_executor.py")
        with open(workflow_executor_file, 'r') as f:
            workflow_executor_content = f.read()

        checker.check(
            "Skill node type handled in workflow executor",
            'elif node.node_type == "skill":' in workflow_executor_content
        )

    except Exception as e:
        checker.check("Workflow integration check", False, str(e))


def check_hyper_deep_research_integration():
    """HyperDeepResearch 통합 확인"""
    print("\n[5] HyperDeepResearch Integration Check")
    print("-" * 70)

    try:
        agent_file = Path("neos/agents/search_agents/hyper_deep_research/agent.py")
        with open(agent_file, 'r') as f:
            agent_content = f.read()

        checker.check(
            "skill_manager imported in HyperDeepResearch",
            "from neos.skills.manager import skill_manager" in agent_content
        )

        checker.check(
            "Skills integration methods exist",
            "async def _init_skills(self)" in agent_content
        )

        checker.check(
            "_analyze_source_with_skill method exists",
            "async def _analyze_source_with_skill(" in agent_content
        )

        checker.check(
            "_summarize_with_skill method exists",
            "async def _summarize_with_skill(" in agent_content
        )

        checker.check(
            "_extract_references_with_skill method exists",
            "async def _extract_references_with_skill(" in agent_content
        )

    except Exception as e:
        checker.check("HyperDeepResearch integration check", False, str(e))


def check_class_interfaces():
    """클래스 인터페이스 검증"""
    print("\n[6] Class Interface Check")
    print("-" * 70)

    try:
        from neos.skills.base import BaseSkill, SkillResult, SkillType
        from neos.skills.manager import SkillManager, SkillRegistry

        # Check BaseSkill interface
        required_methods = ['initialize', 'execute', 'cleanup', 'check_availability', 'get_info']
        for method in required_methods:
            checker.check(f"BaseSkill has {method} method", hasattr(BaseSkill, method))

        # Check SkillResult interface
        result_methods = ['success_result', 'error_result', 'to_dict', 'to_json']
        for method in result_methods:
            checker.check(f"SkillResult has {method} method", hasattr(SkillResult, method))

        # Check SkillManager interface
        manager_methods = [
            'register_builtin_skills',
            'initialize_all',
            'initialize_skill',
            'execute_skill',
            'cleanup_skill',
            'cleanup_all',
            'get_available_skills',
            'get_skill_info'
        ]
        for method in manager_methods:
            checker.check(f"SkillManager has {method} method", hasattr(SkillManager, method))

        # Check SkillRegistry interface
        registry_methods = [
            'register_skill',
            'unregister_skill',
            'get_skill',
            'get_skill_info',
            'list_skills',
            'skill_exists',
            'get_skills_by_capability',
            'get_skills_by_type'
        ]
        for method in registry_methods:
            checker.check(f"SkillRegistry has {method} method", hasattr(SkillRegistry, method))

    except Exception as e:
        checker.check("Class interface check", False, str(e))


def main():
    """메인 실행 함수"""
    print("="*70)
    print("COMPREHENSIVE INTEGRATION AND CODE QUALITY CHECK")
    print("="*70)

    check_module_structure()
    check_skill_files()
    check_api_integration()
    check_workflow_integration()
    check_hyper_deep_research_integration()
    check_class_interfaces()

    checker.print_summary()

    return 0 if checker.checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

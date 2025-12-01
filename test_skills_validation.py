#!/usr/bin/env python3
"""Skills Module Validation Script"""

import asyncio
import sys
from pathlib import Path

# Add neos to path
sys.path.insert(0, str(Path(__file__).parent))

from neos.skills.base import BaseSkill, SkillResult, SkillType
from neos.skills.manager import SkillManager, SkillRegistry, SkillInfo
from neos.skills.builtin import (
    get_builtin_skills,
    ResearchAssistantSkill,
)


class TestResults:
    """테스트 결과 추적"""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []

    def add_pass(self, test_name: str):
        self.passed += 1
        self.tests.append((test_name, True, None))
        print(f"✅ PASS: {test_name}")

    def add_fail(self, test_name: str, error: str):
        self.failed += 1
        self.tests.append((test_name, False, error))
        print(f"❌ FAIL: {test_name}")
        print(f"   Error: {error}")

    def print_summary(self):
        print("\n" + "="*70)
        print("TEST SUMMARY")
        print("="*70)
        print(f"Total Tests: {self.passed + self.failed}")
        print(f"Passed: {self.passed}")
        print(f"Failed: {self.failed}")
        print(f"Success Rate: {(self.passed/(self.passed+self.failed)*100):.1f}%")
        print("="*70)


results = TestResults()


# ==================== Test 1: SkillType Enum ====================
def test_skill_types():
    """Test SkillType enum"""
    try:
        assert SkillType.DOCUMENT.value == "document"
        assert SkillType.DATA_ANALYSIS.value == "data_analysis"
        assert SkillType.RESEARCH.value == "research"
        assert str(SkillType.DOCUMENT) == "document"
        results.add_pass("SkillType enum")
    except Exception as e:
        results.add_fail("SkillType enum", str(e))


# ==================== Test 2: SkillResult ====================
def test_skill_result():
    """Test SkillResult class"""
    try:
        # Success result
        success = SkillResult.success_result(
            data={"message": "test"},
            skill_name="test_skill",
            metadata={"time": 100}
        )
        assert success.success == True
        assert success.data["message"] == "test"
        assert success.skill_name == "test_skill"
        assert success.error is None

        # Error result
        error = SkillResult.error_result(
            error="test error",
            skill_name="test_skill"
        )
        assert error.success == False
        assert error.error == "test error"
        assert error.data is None

        # to_dict conversion
        result_dict = success.to_dict()
        assert "success" in result_dict
        assert "data" in result_dict
        assert "timestamp" in result_dict

        results.add_pass("SkillResult class")
    except Exception as e:
        results.add_fail("SkillResult class", str(e))


# ==================== Test 3: SkillRegistry ====================
def test_skill_registry():
    """Test SkillRegistry"""
    try:
        registry = SkillRegistry()

        # Create test skill info
        skill_info = SkillInfo(
            name="test_skill",
            skill_class=ResearchAssistantSkill,
            skill_type=SkillType.RESEARCH,
            description="Test skill",
            capabilities=["test1", "test2"],
            version="1.0.0"
        )

        # Register skill
        registry.register_skill(skill_info)
        assert "test_skill" in registry
        assert registry.skill_exists("test_skill")
        assert len(registry) == 1

        # Get skill info
        info = registry.get_skill_info("test_skill")
        assert info is not None
        assert info.name == "test_skill"

        # List skills
        skills = registry.list_skills()
        assert len(skills) == 1

        # Filter by type
        research_skills = registry.get_skills_by_type(SkillType.RESEARCH)
        assert len(research_skills) == 1

        # Filter by capability
        cap_skills = registry.get_skills_by_capability("test1")
        assert len(cap_skills) == 1

        # Unregister
        registry.unregister_skill("test_skill")
        assert not registry.skill_exists("test_skill")

        results.add_pass("SkillRegistry")
    except Exception as e:
        results.add_fail("SkillRegistry", str(e))


# ==================== Test 4: SkillManager ====================
async def test_skill_manager():
    """Test SkillManager"""
    try:
        manager = SkillManager()

        # Register builtin skills
        manager.register_builtin_skills()

        # Check skills are registered
        skills = manager.get_available_skills()
        assert len(skills) > 0
        print(f"   Registered {len(skills)} builtin skills")

        # Get specific skill info
        skill_info = manager.get_skill_info("research_assistant")
        assert skill_info is not None
        assert skill_info["name"] == "research_assistant"

        results.add_pass("SkillManager basic operations")
    except Exception as e:
        results.add_fail("SkillManager basic operations", str(e))


# ==================== Test 5: Builtin Skills Info ====================
def test_builtin_skills_info():
    """Test builtin skills metadata"""
    try:
        builtin_skills = get_builtin_skills()
        assert len(builtin_skills) == 4  # bigquery, docx, pdf, research_assistant

        skill_names = [s.name for s in builtin_skills]
        assert "bigquery" in skill_names
        assert "docx" in skill_names
        assert "pdf" in skill_names
        assert "research_assistant" in skill_names

        # Check each skill has required fields
        for skill_info in builtin_skills:
            assert skill_info.name
            assert skill_info.skill_class
            assert skill_info.skill_type
            assert skill_info.description
            assert len(skill_info.capabilities) > 0
            assert skill_info.version

        results.add_pass("Builtin skills metadata")
    except Exception as e:
        results.add_fail("Builtin skills metadata", str(e))


# ==================== Test 6: Research Assistant Skill ====================
async def test_research_assistant_skill():
    """Test Research Assistant Skill execution"""
    try:
        skill = ResearchAssistantSkill()

        # Initialize
        success = await skill.initialize()
        assert success == True
        assert skill.is_available == True

        # Test analyze_source
        result = await skill.execute({
            "action": "analyze_source",
            "content": "This is a test article with some data: 50%, and a citation [1]. https://example.com",
            "options": {"extract_key_points": True}
        })
        assert result.success == True
        assert "quality_score" in result.data
        assert "has_citations" in result.data
        assert "has_data" in result.data
        assert "has_links" in result.data

        # Test summarize
        result = await skill.execute({
            "action": "summarize",
            "content": "This is a long article. It has multiple sentences. Each sentence contains information. The article discusses important topics. These topics are relevant to research.",
            "options": {"max_length": 100}
        })
        assert result.success == True
        assert "summary" in result.data
        assert len(result.data["summary"]) <= 100 + 3  # +3 for "..."

        # Test extract_references
        result = await skill.execute({
            "action": "extract_references",
            "content": "See https://example.com and https://test.org. DOI: 10.1234/test.5678"
        })
        assert result.success == True
        assert "urls" in result.data
        assert len(result.data["urls"]) >= 2
        assert "dois" in result.data

        # Cleanup
        await skill.cleanup()
        assert skill.is_available == False

        results.add_pass("Research Assistant Skill execution")
    except Exception as e:
        results.add_fail("Research Assistant Skill execution", str(e))


# ==================== Test 7: SkillManager Execute ====================
async def test_skill_manager_execute():
    """Test SkillManager execute method"""
    try:
        manager = SkillManager()
        manager.register_builtin_skills()

        # Execute research assistant
        result = await manager.execute_skill(
            "research_assistant",
            {
                "action": "analyze_source",
                "content": "Test content with citation [1]",
                "options": {}
            }
        )

        assert result.success == True
        assert result.skill_name == "research_assistant"
        assert result.data is not None

        results.add_pass("SkillManager execute method")
    except Exception as e:
        results.add_fail("SkillManager execute method", str(e))


# ==================== Test 8: Error Handling ====================
async def test_error_handling():
    """Test error handling"""
    try:
        manager = SkillManager()
        manager.register_builtin_skills()

        # Test with invalid skill name
        result = await manager.execute_skill(
            "nonexistent_skill",
            {"param": "value"}
        )
        assert result.success == False
        assert result.error is not None

        # Test with invalid action
        result = await manager.execute_skill(
            "research_assistant",
            {
                "action": "invalid_action",
                "content": "test"
            }
        )
        assert result.success == False
        assert "Unknown action" in result.error

        # Test with missing required params
        result = await manager.execute_skill(
            "research_assistant",
            {
                "action": "analyze_source"
                # Missing 'content' parameter
            }
        )
        assert result.success == False

        results.add_pass("Error handling")
    except Exception as e:
        results.add_fail("Error handling", str(e))


# ==================== Main ====================
async def main():
    """Run all tests"""
    print("="*70)
    print("NEOS SKILLS MODULE VALIDATION")
    print("="*70)
    print()

    # Synchronous tests
    print("Running synchronous tests...")
    test_skill_types()
    test_skill_result()
    test_skill_registry()
    test_builtin_skills_info()

    # Async tests
    print("\nRunning async tests...")
    await test_skill_manager()
    await test_research_assistant_skill()
    await test_skill_manager_execute()
    await test_error_handling()

    # Print summary
    results.print_summary()

    # Return exit code
    return 0 if results.failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

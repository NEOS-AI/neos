#!/usr/bin/env python3
"""Simplified Workflow Integration Validation (without langgraph dependency)"""

import asyncio
import sys
from pathlib import Path
from typing import Dict, Any, List

# Add neos to path
sys.path.insert(0, str(Path(__file__).parent))

# Direct imports to avoid langgraph dependency
from neos.skills.manager import skill_manager


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


# ==================== Test 1: Workflow Node Configuration ====================
def test_workflow_node_config():
    """Test skill node configuration format"""
    try:
        # Valid skill node config
        node_config = {
            "name": "analyze_source",
            "type": "skill",
            "config": {
                "skill_name": "research_assistant",
                "params": {
                    "action": "analyze_source",
                    "content": "Test content"
                }
            }
        }

        assert node_config["type"] == "skill"
        assert "skill_name" in node_config["config"]
        assert "params" in node_config["config"]

        results.add_pass("Workflow node configuration format")
    except Exception as e:
        results.add_fail("Workflow node configuration format", str(e))


# ==================== Test 2: Simulated Workflow Execution ====================
async def test_simulated_workflow_execution():
    """Simulate workflow execution with skills"""
    try:
        # Initialize skills
        skill_manager.register_builtin_skills()
        await skill_manager.initialize_skill("research_assistant")

        # Simulate workflow state
        workflow_state = {
            "user_id": "test_user",
            "session_id": "test_session",
            "original_query": "test query",
            "execution_steps": []
        }

        # Simulate skill node execution
        skill_config = {
            "skill_name": "research_assistant",
            "params": {
                "action": "analyze_source",
                "content": "Test article with citation [1] and data 50%"
            }
        }

        # Execute skill
        result = await skill_manager.execute_skill(
            skill_config["skill_name"],
            skill_config["params"]
        )

        assert result.success == True

        # Simulate adding to execution steps
        step_result = {
            "node": "analyze_source",
            "type": "skill",
            "skill_name": skill_config["skill_name"],
            "success": result.success,
            "data": result.data,
            "metadata": result.metadata
        }

        workflow_state["execution_steps"].append(step_result)

        assert len(workflow_state["execution_steps"]) == 1
        assert workflow_state["execution_steps"][0]["success"] == True

        results.add_pass("Simulated workflow execution")
    except Exception as e:
        results.add_fail("Simulated workflow execution", str(e))


# ==================== Test 3: Multi-Step Workflow ====================
async def test_multi_step_workflow():
    """Test multi-step workflow with skills"""
    try:
        workflow_state = {
            "execution_steps": [],
            "content": "Long article content to be summarized..."
        }

        # Step 1: Analyze source
        result1 = await skill_manager.execute_skill(
            "research_assistant",
            {
                "action": "analyze_source",
                "content": "Article with citation [1]"
            }
        )
        workflow_state["execution_steps"].append({
            "step": 1,
            "action": "analyze_source",
            "result": result1.data
        })

        # Step 2: Summarize
        result2 = await skill_manager.execute_skill(
            "research_assistant",
            {
                "action": "summarize",
                "content": workflow_state["content"]
            }
        )
        workflow_state["execution_steps"].append({
            "step": 2,
            "action": "summarize",
            "result": result2.data
        })

        # Step 3: Extract references
        result3 = await skill_manager.execute_skill(
            "research_assistant",
            {
                "action": "extract_references",
                "content": "See https://example.com"
            }
        )
        workflow_state["execution_steps"].append({
            "step": 3,
            "action": "extract_references",
            "result": result3.data
        })

        assert len(workflow_state["execution_steps"]) == 3
        assert all(result.success for result in [result1, result2, result3])

        results.add_pass("Multi-step workflow")
    except Exception as e:
        results.add_fail("Multi-step workflow", str(e))


# ==================== Test 4: Dynamic Parameter Substitution ====================
async def test_dynamic_params():
    """Test dynamic parameter substitution pattern"""
    try:
        # Simulate state
        state = {
            "query": "What is AI?",
            "content": "Article about artificial intelligence"
        }

        # Define params with placeholders
        params_template = {
            "action": "summarize",
            "content": "${state.content}"
        }

        # Simulate parameter substitution
        params = params_template.copy()
        if params["content"] == "${state.content}":
            params["content"] = state["content"]

        # Execute with substituted params
        result = await skill_manager.execute_skill(
            "research_assistant",
            params
        )

        assert result.success == True
        assert "summary" in result.data

        results.add_pass("Dynamic parameter substitution pattern")
    except Exception as e:
        results.add_fail("Dynamic parameter substitution pattern", str(e))


# ==================== Test 5: Error Propagation ====================
async def test_error_propagation():
    """Test error propagation in workflow"""
    try:
        workflow_state = {
            "execution_steps": [],
            "errors": []
        }

        # Execute with invalid skill
        result = await skill_manager.execute_skill(
            "nonexistent_skill",
            {"param": "value"}
        )

        # Simulate error handling
        if not result.success:
            workflow_state["errors"].append({
                "skill": "nonexistent_skill",
                "error": result.error
            })

        assert result.success == False
        assert len(workflow_state["errors"]) == 1

        # Execute with invalid params
        result2 = await skill_manager.execute_skill(
            "research_assistant",
            {
                "action": "analyze_source"
                # Missing content parameter
            }
        )

        if not result2.success:
            workflow_state["errors"].append({
                "skill": "research_assistant",
                "error": result2.error
            })

        assert result2.success == False
        assert len(workflow_state["errors"]) == 2

        results.add_pass("Error propagation")
    except Exception as e:
        results.add_fail("Error propagation", str(e))


# ==================== Test 6: Integration Points ====================
def test_integration_points():
    """Test that all integration points exist"""
    try:
        # Check NodeExecutor has execute_skill method
        from neos.workflow.builder import executors
        assert hasattr(executors.NodeExecutor, 'execute_skill')

        # Check skill_manager is imported
        from neos.workflow.builder.executors import skill_manager as executor_skill_manager
        assert executor_skill_manager is not None

        results.add_pass("Integration points verification")
    except Exception as e:
        results.add_fail("Integration points verification", str(e))


# ==================== Main ====================
async def main():
    """Run all tests"""
    print("="*70)
    print("WORKFLOW INTEGRATION VALIDATION (SIMPLIFIED)")
    print("="*70)
    print()

    # Synchronous tests
    print("Running synchronous tests...")
    test_workflow_node_config()
    test_integration_points()

    # Async tests
    print("\nRunning async tests...")
    await test_simulated_workflow_execution()
    await test_multi_step_workflow()
    await test_dynamic_params()
    await test_error_propagation()

    # Print summary
    results.print_summary()

    # Return exit code
    return 0 if results.failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

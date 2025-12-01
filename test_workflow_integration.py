#!/usr/bin/env python3
"""Workflow Integration Validation Script"""

import asyncio
import sys
from pathlib import Path

# Add neos to path
sys.path.insert(0, str(Path(__file__).parent))

from neos.workflow.builder.nodes import WorkflowNode
from neos.workflow.builder.executors import NodeExecutor
from neos.workflow.state import AgentState
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


# ==================== Test 1: WorkflowNode for Skills ====================
def test_workflow_node_creation():
    """Test WorkflowNode creation for skills"""
    try:
        # Create skill node
        node = WorkflowNode(
            name="analyze_source",
            node_type="skill",
            config={
                "skill_name": "research_assistant",
                "params": {
                    "action": "analyze_source",
                    "content": "Test content"
                }
            }
        )

        assert node.name == "analyze_source"
        assert node.node_type == "skill"
        assert node.config["skill_name"] == "research_assistant"

        # Test to_dict
        node_dict = node.to_dict()
        assert node_dict["name"] == "analyze_source"
        assert node_dict["type"] == "skill"
        assert "config" in node_dict

        # Test from_dict
        reconstructed = WorkflowNode.from_dict(node_dict)
        assert reconstructed.name == node.name
        assert reconstructed.node_type == node.node_type

        results.add_pass("WorkflowNode creation for skills")
    except Exception as e:
        results.add_fail("WorkflowNode creation for skills", str(e))


# ==================== Test 2: NodeExecutor Skill Execution ====================
async def test_node_executor_skill():
    """Test NodeExecutor.execute_skill method"""
    try:
        # Initialize skills
        skill_manager.register_builtin_skills()
        await skill_manager.initialize_skill("research_assistant")

        # Create executor
        executor = NodeExecutor(workflow_id=1, workflow_name="test_workflow")

        # Create skill node
        node = WorkflowNode(
            name="analyze_content",
            node_type="skill",
            config={
                "skill_name": "research_assistant",
                "params": {
                    "action": "analyze_source",
                    "content": "This is a test article with data: 75% and citation [1]. http://example.com"
                }
            }
        )

        # Create state
        state = AgentState(
            user_id="test_user",
            session_id="test_session",
            original_query="test query",
            query_intent=None,
            execution_steps=[],
            errors=[]
        )

        # Execute node
        result = await executor.execute_skill(node, state)

        assert result["success"] == True
        assert result["node"] == "analyze_content"
        assert result["type"] == "skill"
        assert result["skill_name"] == "research_assistant"
        assert "data" in result
        assert "execution_time_ms" in result

        # Check data content
        data = result["data"]
        assert "quality_score" in data
        assert "has_citations" in data
        assert data["has_citations"] == True  # We included [1]

        results.add_pass("NodeExecutor skill execution")
    except Exception as e:
        results.add_fail("NodeExecutor skill execution", str(e))


# ==================== Test 3: Dynamic Parameters ====================
async def test_dynamic_parameters():
    """Test dynamic parameter substitution from state"""
    try:
        # Create executor
        executor = NodeExecutor(workflow_id=1, workflow_name="test_workflow")

        # Create node with dynamic parameters
        node = WorkflowNode(
            name="analyze_query_content",
            node_type="skill",
            config={
                "skill_name": "research_assistant",
                "params": {
                    "action": "summarize",
                    "content": "${state.content}",  # Dynamic parameter
                    "options": {"max_length": 100}
                }
            }
        )

        # Create state with content
        state = AgentState(
            user_id="test_user",
            session_id="test_session",
            original_query="test query",
            query_intent=None,
            execution_steps=[],
            errors=[],
            content="This is a long article that needs summarization. It contains multiple sentences with important information."
        )

        # Execute node
        result = await executor.execute_skill(node, state)

        assert result["success"] == True
        assert "summary" in result["data"]

        results.add_pass("Dynamic parameter substitution")
    except Exception as e:
        results.add_fail("Dynamic parameter substitution", str(e))


# ==================== Test 4: Error Handling in Workflow ====================
async def test_workflow_error_handling():
    """Test error handling in workflow execution"""
    try:
        executor = NodeExecutor(workflow_id=1, workflow_name="test_workflow")

        # Test 1: Missing skill_name
        node = WorkflowNode(
            name="bad_node",
            node_type="skill",
            config={
                "params": {"action": "test"}
                # Missing skill_name
            }
        )

        state = AgentState(
            user_id="test_user",
            session_id="test_session",
            original_query="test",
            query_intent=None,
            execution_steps=[],
            errors=[]
        )

        result = await executor.execute_skill(node, state)
        assert result["success"] == False
        assert "skill_name not specified" in result["error"]

        # Test 2: Invalid skill name
        node = WorkflowNode(
            name="invalid_skill_node",
            node_type="skill",
            config={
                "skill_name": "nonexistent_skill",
                "params": {}
            }
        )

        result = await executor.execute_skill(node, state)
        assert result["success"] == False

        results.add_pass("Workflow error handling")
    except Exception as e:
        results.add_fail("Workflow error handling", str(e))


# ==================== Test 5: Multiple Skill Executions ====================
async def test_multiple_skill_executions():
    """Test multiple skill executions in sequence"""
    try:
        executor = NodeExecutor(workflow_id=1, workflow_name="test_workflow")

        state = AgentState(
            user_id="test_user",
            session_id="test_session",
            original_query="test",
            query_intent=None,
            execution_steps=[],
            errors=[]
        )

        # Execute analyze_source
        node1 = WorkflowNode(
            name="analyze",
            node_type="skill",
            config={
                "skill_name": "research_assistant",
                "params": {
                    "action": "analyze_source",
                    "content": "Test article with citation [1]"
                }
            }
        )

        result1 = await executor.execute_skill(node1, state)
        assert result1["success"] == True

        # Execute summarize
        node2 = WorkflowNode(
            name="summarize",
            node_type="skill",
            config={
                "skill_name": "research_assistant",
                "params": {
                    "action": "summarize",
                    "content": "Long article text here. Multiple sentences. More information."
                }
            }
        )

        result2 = await executor.execute_skill(node2, state)
        assert result2["success"] == True

        # Execute extract_references
        node3 = WorkflowNode(
            name="extract_refs",
            node_type="skill",
            config={
                "skill_name": "research_assistant",
                "params": {
                    "action": "extract_references",
                    "content": "See https://example.com for more info"
                }
            }
        )

        result3 = await executor.execute_skill(node3, state)
        assert result3["success"] == True
        assert len(result3["data"]["urls"]) > 0

        results.add_pass("Multiple skill executions")
    except Exception as e:
        results.add_fail("Multiple skill executions", str(e))


# ==================== Main ====================
async def main():
    """Run all tests"""
    print("="*70)
    print("WORKFLOW INTEGRATION VALIDATION")
    print("="*70)
    print()

    # Synchronous tests
    print("Running synchronous tests...")
    test_workflow_node_creation()

    # Async tests
    print("\nRunning async tests...")
    await test_node_executor_skill()
    await test_dynamic_parameters()
    await test_workflow_error_handling()
    await test_multiple_skill_executions()

    # Print summary
    results.print_summary()

    # Return exit code
    return 0 if results.failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

import pytest

from neos.workflow.hyper_deep.executor import HyperDeepExecutor
from neos.workflow.recursive.models import RecursiveTaskNode, TaskStatus


class FakeAgent:
    def reset(self):
        return None

    async def execute(self, query, context):
        return {
            "success": True,
            "results": [
                {
                    "content": "# Report\n\nClaim with citation [1].",
                    "metadata": {
                        "sources": [{"id": "1", "url": "https://example.org"}]
                    },
                }
            ],
        }


class FakeRun:
    run_id = "harness-run-1"
    score = 0.9
    failed_checks = []
    metadata = {}

    class verdict:
        value = "pass"

    class mode:
        value = "gate"


class FakeRunner:
    async def arun(self, **kwargs):
        return FakeRun()


@pytest.mark.asyncio
async def test_hyperdeep_executor_records_harness_run_id(monkeypatch):
    executor = HyperDeepExecutor(harness_runner=FakeRunner())
    executor._agent = FakeAgent()
    task = RecursiveTaskNode(description="Research topic")

    result = await executor.execute(task, {"session_id": "s1", "user_id": "u1"})

    assert "Report" in result
    assert task.status == TaskStatus.COMPLETED
    assert task.harness_run_id == "harness-run-1"

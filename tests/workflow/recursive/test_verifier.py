import pytest

from neos.workflow.recursive.models import RecursiveTaskNode
from neos.workflow.recursive.verifier import RecursiveVerifier


@pytest.mark.asyncio
async def test_verifier_accepts_passed_harness_metadata():
    verifier = RecursiveVerifier()
    task = RecursiveTaskNode(
        description="Research task",
        metadata={"harness": {"mode": "gate", "verdict": "pass", "score": 0.91}},
    )

    result = await verifier.verify(task, "A sufficiently detailed result.", {})

    assert result["satisfied"] is True
    assert result["score"] == 0.91
    assert result["gaps"] == []


@pytest.mark.asyncio
async def test_verifier_rejects_failed_harness_metadata():
    verifier = RecursiveVerifier()
    task = RecursiveTaskNode(
        description="Research task",
        metadata={
            "harness": {
                "mode": "gate",
                "verdict": "fail",
                "score": 0.4,
                "failed_checks": ["source_count"],
            }
        },
    )

    result = await verifier.verify(task, "A result.", {})

    assert result["satisfied"] is False
    assert result["gaps"] == ["source_count"]

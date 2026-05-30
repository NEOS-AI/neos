import pytest

from neos.workflow.processors.research_harness_processor import ResearchHarnessProcessor
from neos.workflow.state import GenerationResult, SearchResult


@pytest.mark.asyncio
async def test_research_harness_processor_writes_harness_state():
    processor = ResearchHarnessProcessor()
    state = {
        "original_query": "Summarize the reports",
        "query_intent": "deep_research",
        "query_classification": {"complexity_score": 0.4},
        "search_results": [
            SearchResult(source="web", title="A", content="A", url="https://a.com/a", score=0.9),
            SearchResult(source="web", title="B", content="B", url="https://b.com/b", score=0.8),
            SearchResult(source="web", title="C", content="C", url="https://c.com/c", score=0.7),
        ],
        "analysis_results": [],
        "generation_results": [
            GenerationResult(
                content_type="answer",
                content="Revenue increased [1]. Churn decreased [2]. Margin improved [3].",
            )
        ],
        "execution_steps": [],
        "errors": [],
        "quality_score": 0.9,
        "quality_feedback": "ok",
        "fact_check_result": {"score": 0.9},
    }

    new_state = await processor.process(state)

    assert new_state["harness_verdict"] in {"pass", "advisory_pass", "needs_repair", "fail"}
    assert isinstance(new_state["harness_score"], float)
    assert len(new_state["harness_runs"]) == 1
    assert new_state["harness_contract"]["mode"] == "gate"


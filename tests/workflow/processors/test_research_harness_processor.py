import pytest

from neos.workflow.processors.research_harness_processor import ResearchHarnessProcessor
from neos.workflow.state import GenerationResult, SearchResult


class RecordingEventHandler:
    def __init__(self):
        self.progress = []

    async def on_node_progress(self, node_name, message, progress=0):
        self.progress.append((node_name, message, progress))


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
    assert "checks" in new_state["harness_runs"][0]
    assert isinstance(new_state["harness_runs"][0]["checks"], list)
    assert "check_results" in new_state["harness_metadata"]
    assert new_state["thinking_trace"][0]["node_id"] == "research_harness"
    assert new_state["thinking_trace"][0]["event_type"] == "harness.run.completed"
    assert new_state["thinking_trace"][0]["run_id"] == new_state["harness_metadata"]["run_id"]


@pytest.mark.asyncio
async def test_research_harness_processor_emits_progress_events():
    handler = RecordingEventHandler()
    processor = ResearchHarnessProcessor()
    state = {
        "original_query": "Summarize reports",
        "query_intent": "deep_research",
        "query_classification": {"complexity_score": 0.4},
        "search_results": [
            SearchResult(source="web", title="A", content="A", url="https://a.com/a", score=0.9),
            SearchResult(source="web", title="B", content="B", url="https://b.com/b", score=0.8),
            SearchResult(source="web", title="C", content="C", url="https://c.com/c", score=0.7),
        ],
        "generation_results": [
            GenerationResult(content_type="answer", content="A [1]. B [2]. C [3].")
        ],
        "execution_steps": [],
        "errors": [],
        "quality_score": 0.9,
        "_event_handler": handler,
    }

    await processor.process(state)

    assert any(item[0] == "research_harness" for item in handler.progress)
    assert any("harness_check_started" in item[1] for item in handler.progress)
    assert any("harness_completed" in item[1] for item in handler.progress)


@pytest.mark.asyncio
async def test_research_harness_processor_persists_when_enabled(monkeypatch):
    class FakeRepository:
        def __init__(self):
            self.calls = []

        async def save_run(self, **kwargs):
            self.calls.append(kwargs)

    fake_repository = FakeRepository()
    monkeypatch.setattr(
        "neos.workflow.processors.research_harness_processor.settings.RESEARCH_HARNESS_PERSIST_RUNS",
        True,
    )
    monkeypatch.setattr(
        "neos.database.repositories.harness_repository.harness_repository",
        fake_repository,
    )

    processor = ResearchHarnessProcessor()
    state = {
        "user_id": "user-1",
        "session_id": "session-1",
        "original_query": "Summarize reports",
        "query_intent": "deep_research",
        "query_classification": {"complexity_score": 0.4},
        "search_results": [
            SearchResult(source="web", title="A", content="A", url="https://a.com/a", score=0.9),
            SearchResult(source="web", title="B", content="B", url="https://b.com/b", score=0.8),
            SearchResult(source="web", title="C", content="C", url="https://c.com/c", score=0.7),
        ],
        "generation_results": [
            GenerationResult(content_type="answer", content="A [1]. B [2]. C [3].")
        ],
        "execution_steps": [],
        "errors": [],
        "quality_score": 0.9,
    }

    await processor.process(state)

    assert len(fake_repository.calls) == 1
    assert fake_repository.calls[0]["session_id"] == "session-1"
    assert fake_repository.calls[0]["user_id"] == "user-1"

import pytest

from neos.api.services.deep_research_section_regenerator import (
    DeepResearchSectionRegenerator,
)


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    async def ainvoke(self, messages):
        self.prompts.append(messages)
        return self.response


class FakeResponse:
    def __init__(self, content):
        self.content = content


@pytest.mark.asyncio
async def test_regenerator_returns_fake_llm_section_content():
    llm = FakeLLM(FakeResponse("Repaired claim with support [1]."))
    regenerator = DeepResearchSectionRegenerator(llm_factory=lambda: llm)

    content = await regenerator.regenerate(
        research_topic="AI market",
        section_title="Summary",
        current_content="Unsupported claim.",
        sources=[{"title": "Source", "url": "https://example.com", "content": "support"}],
        failed_items=[{"sentence": "Unsupported claim."}],
        action_type="regenerate_cited_sections",
    )

    assert content == "Repaired claim with support [1]."
    assert regenerator.last_metadata["status"] == "executed"
    assert llm.prompts


@pytest.mark.asyncio
async def test_regenerator_returns_controlled_fallback_when_sources_are_empty():
    regenerator = DeepResearchSectionRegenerator(llm_factory=lambda: FakeLLM("unused"))

    content = await regenerator.regenerate(
        research_topic="AI market",
        section_title="Summary",
        current_content="Original section.",
        sources=[],
        failed_items=[],
        action_type="regenerate_unsupported_claims",
    )

    assert "Original section." in content
    assert "Repair note" in content
    assert regenerator.last_metadata["status"] == "fallback"
    assert regenerator.last_metadata["reason"] == "insufficient_sources"


@pytest.mark.asyncio
async def test_regenerator_detects_invalid_citation_markers_before_saving():
    llm = FakeLLM(FakeResponse("Repaired claim [source A]."))
    regenerator = DeepResearchSectionRegenerator(llm_factory=lambda: llm)

    content = await regenerator.regenerate(
        research_topic="AI market",
        section_title="Summary",
        current_content="Original section.",
        sources=[{"title": "Source", "url": "https://example.com", "content": "support"}],
        failed_items=[],
        action_type="regenerate_cited_sections",
    )

    assert "Original section." in content
    assert regenerator.last_metadata["status"] == "fallback"
    assert regenerator.last_metadata["reason"] == "invalid_citation_markers"

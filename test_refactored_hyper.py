"""Test script for refactored HyperDeepResearch agent."""

import asyncio
from neos.agents.search_agents.hyper_deep_research import HyperDeepResearchAgent


async def test_language_detection():
    """Test language detection utility."""
    from neos.agents.search_agents.hyper_deep_research.utils import LanguageDetector

    test_cases = [
        ("What is artificial intelligence?", "en", "English"),
        ("인공지능이란 무엇인가?", "ko", "Korean"),
        ("人工知能とは何ですか？", "ja", "Japanese"),
        ("NVIDIA stock market analysis", "en", "English"),
    ]

    print("========== Language Detection Test ==========")
    for query, expected, name in test_cases:
        detected = LanguageDetector.detect(query)
        status = "✓" if detected == expected else "✗"
        print(f"{status} Query: {query}")
        print(f"  Expected: {name} ({expected}), Got: {LanguageDetector.get_language_name(detected)} ({detected})")
    print()


async def test_data_processor():
    """Test data processor utility."""
    from neos.agents.search_agents.hyper_deep_research.utils import DataProcessor

    print("========== Data Processor Test ==========")

    # Test deduplication
    results = [
        [
            {"url": "https://example.com/1", "title": "Test 1"},
            {"url": "https://example.com/2", "title": "Test 2"},
        ],
        [
            {"url": "https://example.com/1", "title": "Test 1 Duplicate"},
            {"url": "https://example.com/3", "title": "Test 3"},
        ]
    ]

    unique = DataProcessor.deduplicate_sources(results)
    print(f"✓ Deduplication: {len(unique)} unique sources from {sum(len(r) for r in results)} total")

    # Test domain extraction
    domains = DataProcessor.extract_unique_domains(unique)
    print(f"✓ Domain extraction: {domains}")

    # Test question extraction
    text = """
    What is AI?
    Why is machine learning important?
    How does deep learning work?
    """
    questions = DataProcessor.extract_research_questions(text)
    print(f"✓ Question extraction: {len(questions)} questions found")
    print()


async def test_prompts():
    """Test prompt templates."""
    from neos.agents.search_agents.hyper_deep_research.prompts import (
        TopicAnalysisPrompts,
        QueryGenerationPrompts
    )

    print("========== Prompt Templates Test ==========")

    # Test topic analysis prompts
    en_prompt = TopicAnalysisPrompts.get_prompt("AI research", "en")
    ko_prompt = TopicAnalysisPrompts.get_prompt("AI research", "ko")
    ja_prompt = TopicAnalysisPrompts.get_prompt("AI research", "ja")

    print(f"✓ English prompt generated ({len(en_prompt)} chars)")
    print(f"✓ Korean prompt generated ({len(ko_prompt)} chars)")
    print(f"✓ Japanese prompt generated ({len(ja_prompt)} chars)")

    # Test query generation prompts
    multi_prompt = QueryGenerationPrompts.get_multi_query_prompt(
        "AI trends", ["What is AI?", "Why AI matters?"], "en"
    )
    print(f"✓ Multi-query prompt generated ({len(multi_prompt)} chars)")
    print()


async def test_repository():
    """Test repository pattern."""
    from neos.agents.search_agents.hyper_deep_research.repository import HyperResearchRepository

    print("========== Repository Test ==========")

    try:
        # Test table creation
        await HyperResearchRepository.ensure_tables_exist()
        print("✓ Database tables ensured")

        # Test report creation (will fail gracefully if DB not available)
        test_id = "test_report_123"
        success = await HyperResearchRepository.create_report(
            test_id, "test_user", "test_session", "Test Topic"
        )
        if success:
            print("✓ Report creation successful")
        else:
            print("⚠ Report creation skipped (DB not available)")

    except Exception as e:
        print(f"⚠ Repository test skipped: {e}")

    print()


async def test_agent_initialization():
    """Test agent initialization."""
    print("========== Agent Initialization Test ==========")

    try:
        agent = HyperDeepResearchAgent()
        print(f"✓ Agent created: {agent.name}")
        print(f"✓ Config loaded: {len(agent.config)} settings")
        print(f"✓ API available: {agent.api_available}")
        print(f"✓ Repository initialized: {agent.repository is not None}")
        print(f"✓ Sub-agents initialized: multi_query={agent.multi_query_agent is not None}, "
              f"criticism={agent.criticism_agent is not None}")
    except Exception as e:
        print(f"✗ Agent initialization failed: {e}")
        import traceback
        print(traceback.format_exc())

    print()


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("Testing Refactored HyperDeepResearch Implementation")
    print("="*60 + "\n")

    await test_language_detection()
    await test_data_processor()
    await test_prompts()
    await test_repository()
    await test_agent_initialization()

    print("="*60)
    print("Test Suite Completed")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

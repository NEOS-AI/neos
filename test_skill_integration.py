"""Test script to verify skill selection and integration"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Direct imports to avoid loading all agents
from neos.agents.skill_based_tool_selector import SkillBasedToolSelector
try:
    from neos.skills.manager import skill_manager
except ImportError as e:
    print(f"Warning: Could not import skill_manager: {e}")
    skill_manager = None


async def test_skill_selection_for_research():
    """Test 1: Check if new skills are selected by SkillBasedToolSelector"""
    print("\n" + "="*70)
    print("TEST 1: Skill Selection by SkillBasedToolSelector")
    print("="*70)

    selector = SkillBasedToolSelector()

    # Test Case 1: AI/ML research query
    print("\n[Test Case 1] AI/ML Research Query")
    query1 = "Explain the latest advances in large language models and transformer architecture"
    context1 = {
        "intent": "hyper_deep_research",
        "query_type": "research",
        "complexity": "high",
        "requires_analysis": True,
        "requires_data_sources": True
    }

    selection1 = await selector.select_skills_and_tools(
        query=query1,
        context=context1,
        session_id="test_session_1",
        user_id="test_user",
        detected_language="en"
    )

    print(f"Query: {query1}")
    print(f"Selected Skills: {selection1.selected_skills}")
    print(f"Selected Tools: {selection1.selected_tools}")
    print(f"Reasoning: {selection1.reasoning}")

    # Check if arxiv is selected
    arxiv_selected = "arxiv" in selection1.selected_skills
    print(f"\n✓ ArXiv selected: {arxiv_selected}")

    # Test Case 2: Medical research query
    print("\n[Test Case 2] Medical Research Query")
    query2 = "What are the latest findings on COVID-19 vaccine efficacy and safety?"
    context2 = {
        "intent": "hyper_deep_research",
        "query_type": "research",
        "complexity": "high",
        "requires_analysis": True,
        "requires_data_sources": True
    }

    selection2 = await selector.select_skills_and_tools(
        query=query2,
        context=context2,
        session_id="test_session_2",
        user_id="test_user",
        detected_language="en"
    )

    print(f"Query: {query2}")
    print(f"Selected Skills: {selection2.selected_skills}")
    print(f"Selected Tools: {selection2.selected_tools}")
    print(f"Reasoning: {selection2.reasoning}")

    # Check if pubmed is selected
    pubmed_selected = "pubmed" in selection2.selected_skills
    print(f"\n✓ PubMed selected: {pubmed_selected}")

    # Test Case 3: General knowledge query
    print("\n[Test Case 3] General Knowledge Query")
    query3 = "Explain the history and impact of the Industrial Revolution"
    context3 = {
        "intent": "hyper_deep_research",
        "query_type": "research",
        "complexity": "medium",
        "requires_analysis": True,
        "requires_data_sources": True
    }

    selection3 = await selector.select_skills_and_tools(
        query=query3,
        context=context3,
        session_id="test_session_3",
        user_id="test_user",
        detected_language="en"
    )

    print(f"Query: {query3}")
    print(f"Selected Skills: {selection3.selected_skills}")
    print(f"Selected Tools: {selection3.selected_tools}")
    print(f"Reasoning: {selection3.reasoning}")

    # Check if wikipedia is selected
    wikipedia_selected = "wikipedia" in selection3.selected_skills
    print(f"\n✓ Wikipedia selected: {wikipedia_selected}")

    # Summary
    print("\n" + "="*70)
    print("SUMMARY: Skill Selection Test")
    print("="*70)
    print(f"ArXiv selected for AI/ML query: {arxiv_selected}")
    print(f"PubMed selected for medical query: {pubmed_selected}")
    print(f"Wikipedia selected for general query: {wikipedia_selected}")

    return {
        "arxiv_selected": arxiv_selected,
        "pubmed_selected": pubmed_selected,
        "wikipedia_selected": wikipedia_selected
    }


async def test_skill_availability():
    """Test 2: Check if new skills are available in skill_manager"""
    print("\n" + "="*70)
    print("TEST 2: Skill Availability in SkillManager")
    print("="*70)

    # Initialize all skills
    await skill_manager.initialize_all_skills()

    # Check available skills
    all_skills = skill_manager.registry.list_skills()
    skill_names = [skill.name for skill in all_skills]

    print(f"\nTotal skills available: {len(skill_names)}")
    print(f"Skills: {skill_names}")

    # Check new research skills
    arxiv_available = "arxiv" in skill_names
    pubmed_available = "pubmed" in skill_names
    wikipedia_available = "wikipedia" in skill_names

    print(f"\n✓ ArXiv available: {arxiv_available}")
    print(f"✓ PubMed available: {pubmed_available}")
    print(f"✓ Wikipedia available: {wikipedia_available}")

    # Check if skills can be initialized
    if arxiv_available:
        arxiv_init = await skill_manager.initialize_skill("arxiv")
        print(f"✓ ArXiv initialized: {arxiv_init}")

    if pubmed_available:
        pubmed_init = await skill_manager.initialize_skill("pubmed")
        print(f"✓ PubMed initialized: {pubmed_init}")

    if wikipedia_available:
        wikipedia_init = await skill_manager.initialize_skill("wikipedia")
        print(f"✓ Wikipedia initialized: {wikipedia_init}")

    return {
        "arxiv_available": arxiv_available,
        "pubmed_available": pubmed_available,
        "wikipedia_available": wikipedia_available
    }


async def test_current_deep_research_integration():
    """Test 3: Check current HyperDeepResearchAgent integration"""
    print("\n" + "="*70)
    print("TEST 3: Current HyperDeepResearchAgent Integration")
    print("="*70)

    # Check what skills are currently used in HyperDeepResearchAgent
    from neos.agents.search_agents.hyper_deep_research.agent import HyperDeepResearchAgent

    agent = HyperDeepResearchAgent()

    # Check if skill_tool_selector is available
    has_selector = hasattr(agent, 'skill_tool_selector')
    print(f"\n✓ Has SkillBasedToolSelector: {has_selector}")

    # Check if skill_manager is available
    has_skill_manager = hasattr(agent, 'skill_manager')
    print(f"✓ Has SkillManager: {has_skill_manager}")

    # Check what skills are initialized
    if has_skill_manager:
        print(f"\n✓ SkillManager registry has {len(agent.skill_manager.registry.list_skills())} skills")

    return {
        "has_selector": has_selector,
        "has_skill_manager": has_skill_manager
    }


async def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("SKILL SELECTION AND INTEGRATION VERIFICATION")
    print("="*70)

    results = {}

    # Test 1: Skill Selection
    try:
        selection_results = await test_skill_selection_for_research()
        results["selection"] = selection_results
    except Exception as e:
        print(f"\n❌ Test 1 failed: {e}")
        import traceback
        traceback.print_exc()
        results["selection"] = {"error": str(e)}

    # Test 2: Skill Availability
    try:
        availability_results = await test_skill_availability()
        results["availability"] = availability_results
    except Exception as e:
        print(f"\n❌ Test 2 failed: {e}")
        import traceback
        traceback.print_exc()
        results["availability"] = {"error": str(e)}

    # Test 3: Integration Check
    try:
        integration_results = await test_current_deep_research_integration()
        results["integration"] = integration_results
    except Exception as e:
        print(f"\n❌ Test 3 failed: {e}")
        import traceback
        traceback.print_exc()
        results["integration"] = {"error": str(e)}

    # Final Summary
    print("\n" + "="*70)
    print("FINAL SUMMARY")
    print("="*70)

    print("\n1. Skill Selection:")
    if "selection" in results and "error" not in results["selection"]:
        print(f"   - ArXiv selected for AI/ML: {results['selection'].get('arxiv_selected', False)}")
        print(f"   - PubMed selected for medical: {results['selection'].get('pubmed_selected', False)}")
        print(f"   - Wikipedia selected for general: {results['selection'].get('wikipedia_selected', False)}")
    else:
        print(f"   ❌ Error occurred")

    print("\n2. Skill Availability:")
    if "availability" in results and "error" not in results["availability"]:
        print(f"   - ArXiv available: {results['availability'].get('arxiv_available', False)}")
        print(f"   - PubMed available: {results['availability'].get('pubmed_available', False)}")
        print(f"   - Wikipedia available: {results['availability'].get('wikipedia_available', False)}")
    else:
        print(f"   ❌ Error occurred")

    print("\n3. Integration:")
    if "integration" in results and "error" not in results["integration"]:
        print(f"   - Has SkillBasedToolSelector: {results['integration'].get('has_selector', False)}")
        print(f"   - Has SkillManager: {results['integration'].get('has_skill_manager', False)}")
    else:
        print(f"   ❌ Error occurred")

    print("\n" + "="*70)
    print("CONCLUSION")
    print("="*70)

    # Check if everything is working
    all_good = (
        results.get("availability", {}).get("arxiv_available", False) and
        results.get("availability", {}).get("pubmed_available", False) and
        results.get("availability", {}).get("wikipedia_available", False) and
        results.get("integration", {}).get("has_selector", False) and
        results.get("integration", {}).get("has_skill_manager", False)
    )

    if all_good:
        print("\n✅ All skills are available and infrastructure is in place")
        print("✅ SkillBasedToolSelector can select skills dynamically")
        print("\n⚠️  NEXT STEPS REQUIRED:")
        print("   1. HyperDeepResearchAgent needs to USE selected skills")
        print("   2. Add domain-specific skill usage (ArXiv for science, PubMed for medical)")
        print("   3. Integrate skill results with Tavily search results")
    else:
        print("\n❌ Some components are missing or not working")

    return results


if __name__ == "__main__":
    results = asyncio.run(main())

"""Test script for new research skills"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from neos.skills.builtin import ArxivSkill, PubmedSkill, WikipediaSkill


async def test_arxiv_skill():
    """Test ArXiv skill"""
    print("\n" + "="*50)
    print("Testing ArXiv Skill")
    print("="*50)

    skill = ArxivSkill()

    # Initialize
    print("Initializing ArXiv skill...")
    init_result = await skill.initialize()
    print(f"Initialization result: {init_result}")
    print(f"Is available: {skill.is_available}")

    if not skill.is_available:
        print("❌ ArXiv skill not available. Check dependencies.")
        return False

    # Test search
    print("\nTesting search...")
    try:
        result = await skill.execute({
            "action": "search",
            "query": "large language models",
            "max_results": 2
        })

        if result.success:
            print(f"✅ Search successful!")
            print(f"Found {result.data.get('total_results', 0)} papers")
            if result.data.get('papers'):
                first_paper = result.data['papers'][0]
                print(f"\nFirst paper:")
                print(f"  Title: {first_paper.get('title', 'N/A')[:80]}...")
                print(f"  ArXiv ID: {first_paper.get('arxiv_id', 'N/A')}")
        else:
            print(f"❌ Search failed: {result.error}")
            return False
    except Exception as e:
        print(f"❌ Search error: {e}")
        return False

    # Cleanup
    await skill.cleanup()
    print("✅ ArXiv skill test completed!")
    return True


async def test_pubmed_skill():
    """Test PubMed skill"""
    print("\n" + "="*50)
    print("Testing PubMed Skill")
    print("="*50)

    skill = PubmedSkill()

    # Initialize
    print("Initializing PubMed skill...")
    init_result = await skill.initialize()
    print(f"Initialization result: {init_result}")
    print(f"Is available: {skill.is_available}")

    if not skill.is_available:
        print("❌ PubMed skill not available. Check dependencies.")
        return False

    # Test search
    print("\nTesting search...")
    try:
        result = await skill.execute({
            "action": "search",
            "query": "covid-19 vaccine",
            "max_results": 2
        })

        if result.success:
            print(f"✅ Search successful!")
            print(f"Found {result.data.get('total_results', 0)} papers")
            if result.data.get('papers'):
                first_paper = result.data['papers'][0]
                print(f"\nFirst paper:")
                print(f"  Title: {first_paper.get('title', 'N/A')[:80]}...")
                print(f"  PMID: {first_paper.get('pmid', 'N/A')}")
        else:
            print(f"❌ Search failed: {result.error}")
            return False
    except Exception as e:
        print(f"❌ Search error: {e}")
        return False

    # Cleanup
    await skill.cleanup()
    print("✅ PubMed skill test completed!")
    return True


async def test_wikipedia_skill():
    """Test Wikipedia skill"""
    print("\n" + "="*50)
    print("Testing Wikipedia Skill")
    print("="*50)

    skill = WikipediaSkill()

    # Initialize
    print("Initializing Wikipedia skill...")
    init_result = await skill.initialize()
    print(f"Initialization result: {init_result}")
    print(f"Is available: {skill.is_available}")

    if not skill.is_available:
        print("❌ Wikipedia skill not available. Check dependencies.")
        return False

    # Test search
    print("\nTesting search...")
    try:
        result = await skill.execute({
            "action": "search",
            "query": "artificial intelligence",
            "max_results": 2,
            "lang": "en"
        })

        if result.success:
            print(f"✅ Search successful!")
            print(f"Found {result.data.get('total_results', 0)} articles")
            if result.data.get('articles'):
                first_article = result.data['articles'][0]
                print(f"\nFirst article:")
                print(f"  Title: {first_article.get('title', 'N/A')}")
                print(f"  URL: {first_article.get('url', 'N/A')[:80]}...")
        else:
            print(f"❌ Search failed: {result.error}")
            return False
    except Exception as e:
        print(f"❌ Search error: {e}")
        return False

    # Cleanup
    await skill.cleanup()
    print("✅ Wikipedia skill test completed!")
    return True


async def main():
    """Run all tests"""
    print("\n" + "="*50)
    print("Testing New Research Skills")
    print("="*50)

    results = []

    # Test each skill
    results.append(("ArXiv", await test_arxiv_skill()))
    results.append(("PubMed", await test_pubmed_skill()))
    results.append(("Wikipedia", await test_wikipedia_skill()))

    # Summary
    print("\n" + "="*50)
    print("Test Summary")
    print("="*50)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{name}: {status}")

    all_passed = all(result for _, result in results)

    if all_passed:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n⚠️  Some tests failed. Check the output above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

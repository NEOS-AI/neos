"""
YouTube Integration Usage Examples

This file demonstrates how to use the YouTube search, comparison, and playlist analysis features.
"""

import asyncio
from neos.tools.manager import mcp_manager
from neos.agents.search_agents import YouTubeSearchAgent


async def example_1_basic_video_search():
    """Example 1: Basic video search"""
    print("\n" + "=" * 80)
    print("Example 1: Basic Video Search")
    print("=" * 80)

    # Initialize tools
    await mcp_manager.initialize()

    # Search for videos
    result = await mcp_manager.execute_tool(
        "youtube_mcp",
        {
            "operation": "search_videos",
            "query": "Python asyncio tutorial",
            "max_results": 5,
            "order": "relevance"
        }
    )

    if result.success:
        videos = result.data.get("videos", [])
        print(f"\nFound {len(videos)} videos:")
        for i, video in enumerate(videos, 1):
            print(f"\n{i}. {video['title']}")
            print(f"   Channel: {video['channel_title']}")
            print(f"   Duration: {video['duration_formatted']}")
            print(f"   Views: {video['view_count']:,}")
            print(f"   URL: {video['url']}")
    else:
        print(f"Error: {result.error}")


async def example_2_get_transcript():
    """Example 2: Get video transcript"""
    print("\n" + "=" * 80)
    print("Example 2: Get Video Transcript")
    print("=" * 80)

    await mcp_manager.initialize()

    # Get transcript for a specific video
    # Replace with an actual video ID
    video_id = "dQw4w9WgXcQ"  # Example video ID

    result = await mcp_manager.execute_tool(
        "youtube_mcp",
        {
            "operation": "get_transcript",
            "video_id": video_id,
            "languages": ["en", "ko"]
        }
    )

    if result.success:
        transcript = result.data
        print(f"\nVideo ID: {transcript['video_id']}")
        print(f"Language: {transcript['language']}")
        print(f"Auto-generated: {transcript['is_auto_generated']}")
        print(f"Segments: {transcript['segment_count']}")
        print(f"\nFirst 500 characters:")
        print(transcript['full_text'][:500] + "...")
    else:
        print(f"Error: {result.error}")


async def example_3_analyze_video():
    """Example 3: Complete video analysis"""
    print("\n" + "=" * 80)
    print("Example 3: Complete Video Analysis")
    print("=" * 80)

    await mcp_manager.initialize()

    # Analyze a video (metadata + transcript)
    video_id = "dQw4w9WgXcQ"  # Example video ID

    result = await mcp_manager.execute_tool(
        "youtube_mcp",
        {
            "operation": "analyze_video",
            "video_id": video_id,
        }
    )

    if result.success:
        data = result.data
        print(f"\nVideo ID: {data['video_id']}")
        print(f"Analysis Complete: {data['analysis_complete']}")

        if data.get("metadata"):
            metadata = data["metadata"]
            print(f"\nMetadata:")
            print(f"  Title: {metadata['title']}")
            print(f"  Channel: {metadata['channel_title']}")
            print(f"  Views: {metadata['view_count']:,}")

        if data.get("transcript"):
            transcript = data["transcript"]
            print(f"\nTranscript:")
            print(f"  Language: {transcript['language']}")
            print(f"  Length: {transcript['text_length']} characters")
    else:
        print(f"Error: {result.error}")


async def example_4_search_with_agent():
    """Example 4: Use YouTubeSearchAgent for intelligent search"""
    print("\n" + "=" * 80)
    print("Example 4: Intelligent Video Search with Agent")
    print("=" * 80)

    await mcp_manager.initialize()

    # Create agent
    agent = YouTubeSearchAgent()

    # Execute search
    context = {
        "session_id": "example_session",
        "user_id": "example_user",
        "detected_language": "en",
        "max_videos": 3
    }

    result = await agent.execute(
        query="best Python async programming tutorials",
        context=context
    )

    if result.get("success", False):
        results = result.get("results", [])
        print(f"\nFound {len(results)} recommended videos:")

        for i, search_result in enumerate(results, 1):
            print(f"\n{i}. {search_result.title}")
            print(f"   Source: {search_result.source}")
            print(f"   Relevance Score: {search_result.relevance_score:.2f}")
            print(f"   Summary:")
            # Print summary with indentation
            for line in search_result.content.split('\n'):
                print(f"   {line}")
            print(f"   Duration: {search_result.metadata.get('duration')}")
            print(f"   Views: {search_result.metadata.get('view_count', 0):,}")
            print(f"   URL: {search_result.url}")
    else:
        print(f"Error: {result.get('error')}")


async def example_5_compare_videos():
    """Example 5: Compare multiple videos"""
    print("\n" + "=" * 80)
    print("Example 5: Video Comparison")
    print("=" * 80)

    await mcp_manager.initialize()

    agent = YouTubeSearchAgent()

    # Compare videos (replace with real video IDs)
    video_ids = [
        "video_id_1",
        "video_id_2",
        "video_id_3"
    ]

    result = await agent.compare_videos(
        video_ids=video_ids,
        comparison_context="Python asyncio tutorials comparison",
        session_id="example_session",
        user_id="example_user",
        detected_language="en"
    )

    if result.get("success", False):
        print(f"\nCompared {result['video_count']} videos")
        print(f"\nAnalysis:")
        print(result['analysis'])
    else:
        print(f"Error: {result.get('error')}")


async def example_6_analyze_playlist():
    """Example 6: Analyze a playlist"""
    print("\n" + "=" * 80)
    print("Example 6: Playlist Analysis")
    print("=" * 80)

    await mcp_manager.initialize()

    # Get playlist info first
    playlist_id = "PLeo1K3hjS3uv5U-Lmlnucd7gqF-3ehIh0"  # Example playlist

    result = await mcp_manager.execute_tool(
        "youtube_mcp",
        {
            "operation": "get_playlist_info",
            "playlist_id": playlist_id,
        }
    )

    if result.success:
        info = result.data
        print(f"\nPlaylist: {info['title']}")
        print(f"Channel: {info['channel_title']}")
        print(f"Videos: {info['video_count']}")
        print(f"URL: {info['url']}")


async def example_7_playlist_learning_path():
    """Example 7: Create learning path from playlist"""
    print("\n" + "=" * 80)
    print("Example 7: Playlist Learning Path")
    print("=" * 80)

    await mcp_manager.initialize()

    agent = YouTubeSearchAgent()

    # Analyze playlist and create learning path
    playlist_id = "PLeo1K3hjS3uv5U-Lmlnucd7gqF-3ehIh0"  # Example playlist

    result = await agent.analyze_playlist(
        playlist_id=playlist_id,
        session_id="example_session",
        user_id="example_user",
        detected_language="en"
    )

    if result.get("success", False):
        print(f"\nPlaylist: {result['playlist_info']['title']}")
        print(f"Total Videos: {result['video_count']}")
        print(f"Total Duration: {result['total_duration_formatted']}")
        print(f"\nLearning Path Analysis:")
        print(result['analysis'])
    else:
        print(f"Error: {result.get('error')}")


async def example_8_get_playlist_videos():
    """Example 8: Get all videos from a playlist"""
    print("\n" + "=" * 80)
    print("Example 8: Get Playlist Videos")
    print("=" * 80)

    await mcp_manager.initialize()

    playlist_id = "PLeo1K3hjS3uv5U-Lmlnucd7gqF-3ehIh0"  # Example playlist

    result = await mcp_manager.execute_tool(
        "youtube_mcp",
        {
            "operation": "get_playlist_videos",
            "playlist_id": playlist_id,
            "max_results": 10,
        }
    )

    if result.success:
        data = result.data
        videos = data.get("videos", [])

        print(f"\nPlaylist ID: {data['playlist_id']}")
        print(f"Total Videos: {data['total_videos']}")
        print(f"\nVideos:")

        for i, video in enumerate(videos, 1):
            print(f"\n{i}. {video['title']}")
            print(f"   Duration: {video['duration_formatted']}")
            print(f"   Views: {video['view_count']:,}")
            print(f"   URL: {video['url']}")
    else:
        print(f"Error: {result.error}")


async def example_9_custom_comparison():
    """Example 9: Custom video comparison with configuration"""
    print("\n" + "=" * 80)
    print("Example 9: Custom Video Comparison")
    print("=" * 80)

    await mcp_manager.initialize()

    agent = YouTubeSearchAgent()

    # Import configuration classes
    from neos.agents.search_agents.youtube_search import (
        ComparisonConfig,
        ComparisonFocus
    )

    # Create custom comparison config
    config = ComparisonConfig(
        focus=ComparisonFocus.BEGINNER_FRIENDLY,
        include_timestamps=True,
        emphasize_differences=True,
        max_summary_length="long"
    )

    # Compare videos with custom config
    video_ids = ["video_id_1", "video_id_2"]

    result = await agent.compare_videos(
        video_ids=video_ids,
        comparison_context="Python beginner tutorials",
        session_id="example_session",
        user_id="example_user",
        detected_language="en",
        config=config
    )

    if result.get("success", False):
        print(f"\nComparison with focus on: {config.focus.value}")
        print(f"\nAnalysis:")
        print(result['analysis'])
    else:
        print(f"Error: {result.get('error')}")


async def example_10_playlist_with_duplicates():
    """Example 10: Playlist analysis with duplicate detection"""
    print("\n" + "=" * 80)
    print("Example 10: Playlist Analysis with Duplicate Detection")
    print("=" * 80)

    await mcp_manager.initialize()

    agent = YouTubeSearchAgent()

    # Import configuration classes
    from neos.agents.search_agents.youtube_search import (
        PlaylistAnalysisConfig,
        PlaylistOrderStrategy
    )

    # Create config with duplicate detection
    config = PlaylistAnalysisConfig(
        detect_duplicates=True,
        suggest_order=PlaylistOrderStrategy.OPTIMAL_LEARNING,
        analyze_progression=True,
        identify_gaps=True
    )

    playlist_id = "PLeo1K3hjS3uv5U-Lmlnucd7gqF-3ehIh0"  # Example

    result = await agent.analyze_playlist(
        playlist_id=playlist_id,
        session_id="example_session",
        user_id="example_user",
        detected_language="en",
        config=config
    )

    if result.get("success", False):
        print(f"\nPlaylist: {result['playlist_info']['title']}")
        print(f"Videos: {result['video_count']}")

        # Show duplicate information
        if "duplicates" in result:
            dup_info = result["duplicates"]
            print(f"\nDuplicates found:")
            print(f"  Exact: {dup_info['duplicate_count']}")
            print(f"  Similar: {dup_info['similar_count']}")

            if dup_info['exact_duplicates']:
                print("\n  Exact duplicates:")
                for dup in dup_info['exact_duplicates'][:3]:
                    print(f"    - {dup['video1_title']}")

        # Show ordering information
        if "order_strategy" in result:
            print(f"\nSuggested order: {result['order_strategy']}")
            print("\nOptimized viewing order (first 5):")
            for i, video in enumerate(result['suggested_order'][:5], 1):
                print(f"  {i}. {video['title']} (originally #{video.get('original_index', 0) + 1})")

        print(f"\nLearning Path Analysis:")
        print(result['analysis'])
    else:
        print(f"Error: {result.get('error')}")


async def example_11_technical_comparison():
    """Example 11: Technical depth focused comparison"""
    print("\n" + "=" * 80)
    print("Example 11: Technical Depth Comparison")
    print("=" * 80)

    await mcp_manager.initialize()

    agent = YouTubeSearchAgent()

    from neos.agents.search_agents.youtube_search import (
        ComparisonConfig,
        ComparisonFocus
    )

    # Focus on technical depth
    config = ComparisonConfig(
        focus=ComparisonFocus.TECHNICAL_DEPTH,
        include_production_quality=False,  # Less emphasis on production
        emphasize_differences=True
    )

    video_ids = ["video_id_1", "video_id_2", "video_id_3"]

    result = await agent.compare_videos(
        video_ids=video_ids,
        comparison_context="Advanced Python asyncio patterns",
        session_id="example_session",
        user_id="example_user",
        detected_language="en",
        config=config
    )

    if result.get("success", False):
        print("\nTechnical Depth Analysis:")
        print(result['analysis'])
    else:
        print(f"Error: {result.get('error')}")


async def example_12_semantic_duplicate_detection():
    """Example 12: Semantic similarity-based duplicate detection"""
    print("\n" + "=" * 80)
    print("Example 12: Semantic Duplicate Detection")
    print("=" * 80)

    await mcp_manager.initialize()

    agent = YouTubeSearchAgent()

    from neos.agents.search_agents.youtube_search import (
        PlaylistAnalysisConfig,
        PlaylistOrderStrategy
    )

    # Enable semantic similarity detection using embeddings
    config = PlaylistAnalysisConfig(
        detect_duplicates=True,
        use_semantic_similarity=True,  # Uses OpenAI embeddings
        semantic_similarity_threshold=0.85,  # 85% similarity threshold
        suggest_order=PlaylistOrderStrategy.ORIGINAL
    )

    playlist_id = "PLeo1K3hjS3uv5U-Lmlnucd7gqF-3ehIh0"  # Example

    result = await agent.analyze_playlist(
        playlist_id=playlist_id,
        session_id="example_session",
        user_id="example_user",
        config=config
    )

    if result.get("success", False):
        print(f"\nPlaylist: {result['playlist_info']['title']}")

        if "duplicates" in result:
            dup_info = result["duplicates"]
            print(f"\nDuplicate Detection Results:")
            print(f"  Exact duplicates: {dup_info['duplicate_count']}")
            print(f"  Similar titles: {dup_info['similar_count']}")
            print(f"  Semantic matches: {dup_info.get('semantic_count', 0)}")

            if dup_info.get('semantic_duplicates'):
                print("\n  Semantically similar videos (concept duplicates):")
                for sem in dup_info['semantic_duplicates'][:5]:
                    print(f"    - '{sem['video1_title']}'")
                    print(f"      ≈ '{sem['video2_title']}'")
                    print(f"      Similarity: {sem['semantic_similarity']:.1%}")
    else:
        print(f"Error: {result.get('error')}")


async def example_13_topic_clustered_order():
    """Example 13: Topic-clustered playlist ordering"""
    print("\n" + "=" * 80)
    print("Example 13: Topic-Clustered Ordering")
    print("=" * 80)

    await mcp_manager.initialize()

    agent = YouTubeSearchAgent()

    from neos.agents.search_agents.youtube_search import (
        PlaylistAnalysisConfig,
        PlaylistOrderStrategy
    )

    # Use topic-based clustering
    config = PlaylistAnalysisConfig(
        detect_duplicates=False,  # Skip for faster results
        suggest_order=PlaylistOrderStrategy.TOPIC_CLUSTERED,  # Group by topic
        analyze_progression=True
    )

    playlist_id = "PLeo1K3hjS3uv5U-Lmlnucd7gqF-3ehIh0"  # Example

    result = await agent.analyze_playlist(
        playlist_id=playlist_id,
        session_id="example_session",
        user_id="example_user",
        config=config
    )

    if result.get("success", False):
        print(f"\nPlaylist: {result['playlist_info']['title']}")
        print(f"Order strategy: {result.get('order_strategy', 'N/A')}")

        if "suggested_order" in result:
            print("\nTopic-Clustered Order (first 10):")
            for video in result['suggested_order'][:10]:
                original = video.get('original_index', 'N/A')
                new = video.get('suggested_order', 'N/A')
                print(f"  {new}. {video['title'][:50]}... (was #{original + 1 if isinstance(original, int) else original})")

        print(f"\nAnalysis:")
        print(result['analysis'][:1000] + "..." if len(result.get('analysis', '')) > 1000 else result.get('analysis', ''))
    else:
        print(f"Error: {result.get('error')}")


async def example_14_prerequisite_chain_order():
    """Example 14: Prerequisite chain ordering"""
    print("\n" + "=" * 80)
    print("Example 14: Prerequisite Chain Ordering")
    print("=" * 80)

    await mcp_manager.initialize()

    agent = YouTubeSearchAgent()

    from neos.agents.search_agents.youtube_search import (
        PlaylistAnalysisConfig,
        PlaylistOrderStrategy
    )

    # Use prerequisite-based ordering
    config = PlaylistAnalysisConfig(
        detect_duplicates=False,
        suggest_order=PlaylistOrderStrategy.PREREQUISITE_CHAIN,  # Order by dependencies
        include_prerequisites=True,
        identify_gaps=True
    )

    playlist_id = "PLeo1K3hjS3uv5U-Lmlnucd7gqF-3ehIh0"  # Example

    result = await agent.analyze_playlist(
        playlist_id=playlist_id,
        session_id="example_session",
        user_id="example_user",
        config=config
    )

    if result.get("success", False):
        print(f"\nPlaylist: {result['playlist_info']['title']}")
        print(f"Order strategy: {result.get('order_strategy', 'N/A')}")

        if "suggested_order" in result:
            print("\nPrerequisite-Based Order (first 10):")
            print("(Foundation → Building → Advanced)")
            for video in result['suggested_order'][:10]:
                original = video.get('original_index', 'N/A')
                new = video.get('suggested_order', 'N/A')
                duration = video.get('duration_formatted', '')
                print(f"  {new}. [{duration}] {video['title'][:45]}...")

        print(f"\nLearning Path Analysis:")
        print(result['analysis'][:1500] + "..." if len(result.get('analysis', '')) > 1500 else result.get('analysis', ''))
    else:
        print(f"Error: {result.get('error')}")


async def main():
    """Run all examples"""
    print("\n" + "=" * 80)
    print("YouTube Integration Examples")
    print("=" * 80)
    print("\nThese examples demonstrate various YouTube integration features.")
    print("Note: Replace example video IDs and playlist IDs with real ones to test.")
    print("\nRunning examples...\n")

    # Run examples
    try:
        # Basic operations
        await example_1_basic_video_search()
        await example_2_get_transcript()
        await example_3_analyze_video()

        # Agent-based operations
        await example_4_search_with_agent()

        # Advanced features
        # await example_5_compare_videos()  # Uncomment with real video IDs
        # await example_6_analyze_playlist()  # Uncomment with real playlist ID
        # await example_7_playlist_learning_path()  # Uncomment with real playlist ID
        await example_8_get_playlist_videos()

        # Enhanced features with configuration
        # await example_9_custom_comparison()  # Uncomment to test custom comparison configs
        # await example_10_playlist_with_duplicates()  # Uncomment to test duplicate detection
        # await example_11_technical_comparison()  # Uncomment to test technical depth focus

        # Advanced features (require API calls)
        # await example_12_semantic_duplicate_detection()  # Uses OpenAI embeddings
        # await example_13_topic_clustered_order()  # LLM-based topic clustering
        # await example_14_prerequisite_chain_order()  # LLM-based prerequisite detection

        print("\n" + "=" * 80)
        print("Examples completed!")
        print("=" * 80)
        print("\nNote: Examples 9-11 demonstrate enhanced configuration options:")
        print("  - Example 9: Custom comparison focus (beginner-friendly, technical depth, etc.)")
        print("  - Example 10: Playlist duplicate detection and optimal ordering")
        print("  - Example 11: Technical depth focused comparison")
        print("\nAdvanced features (Examples 12-14):")
        print("  - Example 12: Semantic duplicate detection (uses OpenAI embeddings)")
        print("  - Example 13: Topic-clustered ordering (LLM-based)")
        print("  - Example 14: Prerequisite chain ordering (LLM-based)")

    except Exception as e:
        print(f"\nError running examples: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Run examples
    asyncio.run(main())

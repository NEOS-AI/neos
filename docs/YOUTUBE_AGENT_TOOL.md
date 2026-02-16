# YouTube Search and Summarization Agent Implementation Plan

## Overview

This document outlines the implementation plan for adding YouTube video search, transcript analysis, and summarization capabilities to the neos workflow system.

## Requirements

1. **YouTube Transcript Processing**: Extract and analyze video transcripts
2. **Video Content Summarization**: Generate concise summaries of video content
3. **Intelligent Video Search**: Search YouTube videos and analyze transcripts to find relevant content
4. **Video Recommendations**: Recommend appropriate videos based on search results and transcript analysis

## Architecture Overview

### Components to Implement

```
┌─────────────────────────────────────────────────────────┐
│                  YouTube Integration                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌────────────────────┐      ┌─────────────────────┐    │
│  │  YouTubeMCPTool    │      │  YouTubeAgent       │    │
│  │  (Tool Layer)      │◄─────┤  (Agent Layer)      │    │
│  └────────────────────┘      └─────────────────────┘    │
│         │                              │                │
│         ├─ Search videos               ├─ Orchestrate   │
│         ├─ Get transcripts             │   searches     │
│         ├─ Extract metadata            └─ Analyze       │
│         └─ Fetch captions                  relevance    │
│                                                         │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
          ┌───────────────────────────────┐
          │  Workflow Integration         │
          │  - SearchOrchestrator         │
          │  - Agent Registry             │
          │  - Tool Manager               │
          └───────────────────────────────┘
```

## Phase 1: Tool Layer Implementation

### 1.1 YouTubeMCPTool Class

**File**: `/neos/tools/tools/youtube.py`

Inherit from `MCPTool` base class and implement:

**Core Methods**:
- `initialize()` - Setup YouTube clients and verify API access
- `execute(params)` - Main execution dispatcher
- `cleanup()` - Cleanup resources
- `check_availability()` - Verify dependencies are available

**Operations to Support**:
```python
operations = {
    "search": self._search_videos,           # Search YouTube videos
    "get_transcript": self._get_transcript,  # Get video transcript
    "get_video_info": self._get_video_info,  # Get video metadata
    "analyze_relevance": self._analyze_relevance, # Analyze transcript relevance
}
```

**Dependencies**:
- `youtube-transcript-api` - For fetching transcripts (no API key needed)
- `google-api-python-client` - For YouTube Data API v3 (requires API key)
- `isodate` - For parsing ISO 8601 durations

**Configuration**:
```python
# In settings.py
YOUTUBE_API_KEY: Optional[str] = None  # YouTube Data API v3 key
YOUTUBE_MAX_RESULTS: int = 10          # Max search results
YOUTUBE_TRANSCRIPT_LANGUAGES: List[str] = ["en", "ko"]  # Preferred languages
```

**Search Implementation Strategy**:
```python
async def _search_videos(self, query: str, max_results: int = 10) -> List[Dict]:
    """
    Search YouTube videos using YouTube Data API v3

    Returns:
        List of video metadata including:
        - video_id
        - title
        - description
        - channel_title
        - publish_date
        - duration
        - view_count
        - thumbnail_url
    """
```

**Transcript Extraction Strategy**:
```python
async def _get_transcript(self, video_id: str, languages: List[str] = None) -> Dict:
    """
    Get transcript using youtube-transcript-api

    Features:
    - Automatic language detection
    - Fallback to auto-generated captions
    - Timestamp preservation
    - Text cleaning and normalization

    Returns:
        {
            "video_id": str,
            "language": str,
            "text": str,  # Full transcript
            "segments": List[{"start": float, "duration": float, "text": str}],
            "is_auto_generated": bool
        }
    """
```

**Relevance Analysis Strategy**:
```python
async def _analyze_relevance(
    self,
    transcript: str,
    query: str,
    video_metadata: Dict
) -> Dict:
    """
    Analyze how relevant a video is to the query

    Multi-factor scoring:
    1. Keyword matching in transcript (TF-IDF or embedding similarity)
    2. Semantic similarity (using LLM embeddings)
    3. Metadata signals (title match, description match)
    4. Quality signals (views, likes, recency)

    Returns:
        {
            "relevance_score": float (0-1),
            "keyword_matches": List[str],
            "key_topics": List[str],
            "reasoning": str,
            "confidence": str (low/medium/high)
        }
    """
```

### 1.2 Error Handling

**Common Error Scenarios**:
- Transcript not available (disabled by uploader)
- API quota exceeded
- Invalid video ID
- Network timeouts
- API key not configured

**Fallback Strategy**:
```python
# Priority: Transcript API > Auto-generated captions > Description analysis
if transcript_unavailable:
    if auto_captions_available:
        use_auto_captions()
    else:
        # Fallback to video description + comments analysis
        use_metadata_only()
```

## Phase 2: Agent Layer Implementation

### 2.1 YouTubeSearchAgent Class

**File**: `/neos/agents/search_agents/youtube_search.py`

Inherit from `SearchAgent` base class.

**Agent Configuration**:
```python
name = "youtube_search"
role = "YouTube Video Search and Analysis Specialist"
goal = "Find and analyze relevant YouTube videos based on user queries"
backstory = """
Expert at searching YouTube content, analyzing video transcripts,
and identifying the most relevant videos for user queries.
Specializes in content quality assessment and recommendation.
"""
```

**Core Methods**:
```python
async def search(self, query: str, **kwargs) -> Dict:
    """
    Main search method implementing the agent's search strategy

    Workflow:
    1. Search YouTube for videos matching query
    2. Fetch transcripts for top N videos (parallel execution)
    3. Analyze relevance of each video using LLM
    4. Rank videos by relevance score
    5. Generate summaries for top K videos
    6. Return structured results with recommendations
    """
```

**Search Strategy**:
```
┌─────────────────────────────────────────────────────────┐
│ Step 1: Query Analysis                                   │
│ - Extract keywords                                       │
│ - Identify intent (tutorial, review, explanation, etc.)  │
│ - Determine quality requirements                         │
└──────────────────┬───────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ Step 2: YouTube Search                                   │
│ - Call YouTubeMCPTool.search()                          │
│ - Filter by duration, recency, views (optional)         │
│ - Get initial candidate set (10-20 videos)              │
└──────────────────┬───────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ Step 3: Transcript Analysis (Parallel)                   │
│ - Fetch transcripts for all candidates                   │
│ - Handle unavailable transcripts gracefully              │
│ - Extract key topics from each transcript                │
└──────────────────┬───────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ Step 4: Relevance Scoring (USER CONTRIBUTION POINT)     │
│ - Semantic similarity analysis                           │
│ - Keyword matching                                       │
│ - Quality signal weighting                               │
└──────────────────┬───────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ Step 5: Content Summarization (USER CONTRIBUTION POINT)  │
│ - Generate summaries for top 3-5 videos                  │
│ - Extract key insights and timestamps                    │
│ - Identify unique value of each video                    │
└──────────────────┬───────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────┐
│ Step 6: Recommendation Generation                        │
│ - Rank videos by relevance                               │
│ - Format results with summaries                          │
│ - Provide viewing recommendations                        │
└─────────────────────────────────────────────────────────┘
```

**User Contribution Points**:

1. **Relevance Scoring Logic** (5-10 lines)
   - Location: `youtube_search.py::calculate_relevance_score()`
   - Decision: How to weight different signals (transcript match vs. metadata vs. quality)
   - Trade-offs: Precision vs. recall, recency vs. popularity

2. **Summarization Strategy** (5-10 lines)
   - Location: `youtube_search.py::generate_video_summary()`
   - Decision: Summary length, focus areas, timestamp inclusion
   - Trade-offs: Brevity vs. detail, technical depth vs. accessibility

### 2.2 YouTubeAnalysisAgent Class (Optional)

**File**: `/neos/agents/analysis_agents/youtube_analysis.py`

For deep analysis of specific videos (when user provides video URL).

Inherit from `AnalysisAgent` base class.

**Capabilities**:
- Detailed transcript analysis
- Topic extraction
- Sentiment analysis
- Key moment identification
- Chapter/section generation
- Q&A extraction

## Phase 3: Workflow Integration

### 3.1 Tool Registration

**File**: `/neos/tools/manager/mcp_manager.py`

Register the YouTubeMCPTool:
```python
def _register_default_tools(self):
    default_tools = [
        # ... existing tools ...
        YouTubeMCPTool(),
    ]
```

### 3.2 Agent Registration

**File**: `/neos/workflow/agent_registry.py`

Register the YouTubeSearchAgent:
```python
agents = {
    # ... existing agents ...
    "youtube_search": YouTubeSearchAgent(),
}
```

### 3.3 Intent Classification Update

**File**: `/neos/workflow/query_classifier.py`

Add YouTube-related intent detection:
```python
intents = [
    # ... existing intents ...
    "youtube_search",  # Find YouTube videos
    "video_summary",   # Summarize specific video
]
```

**Intent Triggers**:
- Keywords: "youtube", "video", "tutorial", "watch", "review"
- Patterns: YouTube URL detection
- Context: Request for video recommendations

### 3.4 SearchOrchestrator Integration

**File**: `/neos/workflow/orchestrators/search_orchestrator.py`

Add YouTube search strategy:
```python
async def _select_agents(self, query_data: Dict) -> List[str]:
    """Select appropriate agents based on query type"""

    # Detect YouTube-related queries
    if self._is_youtube_query(query_data):
        agents.append("youtube_search")

    # Combine with other search agents if needed
    if query_data.get("combine_with_web_search"):
        agents.append("realtime_info_search")
```

## Phase 4: Configuration and Dependencies

### 4.1 Environment Configuration

**File**: `.env.template`

Add YouTube-related configuration:
```bash
# YouTube Integration
YOUTUBE_API_KEY=your_youtube_data_api_v3_key
YOUTUBE_MAX_RESULTS=10
YOUTUBE_TRANSCRIPT_LANGUAGES=en,ko
```

### 4.2 Settings Schema

**File**: `/neos/config/settings.py`

Add YouTube settings:
```python
class Settings(BaseSettings):
    # ... existing settings ...

    # YouTube Configuration
    YOUTUBE_API_KEY: Optional[str] = None
    YOUTUBE_MAX_RESULTS: int = Field(default=10, ge=1, le=50)
    YOUTUBE_TRANSCRIPT_LANGUAGES: List[str] = Field(default=["en", "ko"])
    YOUTUBE_MIN_RELEVANCE_SCORE: float = Field(default=0.5, ge=0.0, le=1.0)
    YOUTUBE_ENABLE_AUTO_CAPTIONS: bool = True

    # Agent Timeouts
    AGENT_TIMEOUTS: Dict[str, int] = {
        # ... existing timeouts ...
        "youtube_search": 45,  # Allow time for transcript fetching
    }
```

### 4.3 Python Dependencies

**File**: `pyproject.toml` or `requirements.txt`

Add required packages:
```toml
dependencies = [
    # ... existing dependencies ...
    "youtube-transcript-api>=0.6.2",  # No API key needed
    "google-api-python-client>=2.108.0",  # YouTube Data API v3
    "isodate>=0.6.1",  # Parse video durations
]
```

## Phase 5: Testing Strategy

### 5.1 Unit Tests

**File**: `/tests/tools/test_youtube_tool.py`

Test cases:
- Video search functionality
- Transcript extraction (with mocked API)
- Relevance scoring accuracy
- Error handling (no transcript, API errors)
- Rate limiting and retry logic

### 5.2 Integration Tests

**File**: `/tests/agents/test_youtube_agent.py`

Test cases:
- End-to-end search workflow
- Multi-video analysis
- Ranking and recommendation logic
- Integration with workflow orchestrator

### 5.3 E2E Tests

**File**: `/tests/workflow/test_youtube_integration.py`

Test cases:
- User query → YouTube results workflow
- Combined search (web + YouTube)
- Video URL analysis
- Error recovery and fallbacks

## Implementation Checklist

### Phase 1: Foundation
- [ ] Install YouTube-related dependencies
- [ ] Add YouTube configuration to settings.py
- [ ] Update .env.template with YouTube API key
- [ ] Create YouTubeMCPTool base structure

### Phase 2: Tool Implementation
- [ ] Implement YouTube video search
- [ ] Implement transcript fetching
- [ ] Implement relevance analysis
- [ ] Add error handling and fallbacks
- [ ] Write unit tests for tool

### Phase 3: Agent Implementation
- [ ] Create YouTubeSearchAgent class
- [ ] Implement search workflow
- [ ] **USER CONTRIBUTION**: Implement relevance scoring logic
- [ ] **USER CONTRIBUTION**: Implement summarization strategy
- [ ] Write integration tests for agent

### Phase 4: Workflow Integration
- [ ] Register YouTubeMCPTool in MCPManager
- [ ] Register YouTubeSearchAgent in AgentRegistry
- [ ] Update QueryClassifier for YouTube intents
- [ ] Integrate with SearchOrchestrator
- [ ] Write E2E tests

### Phase 5: Documentation and Examples
- [ ] Add usage examples
- [ ] Document API key setup
- [ ] Create example queries
- [ ] Update user documentation

## Technical Considerations

### YouTube Data API v3 Quotas

**Daily Quota**: 10,000 units/day (default free tier)

**Cost per operation**:
- Search: 100 units
- Video details: 1 unit
- Transcript: 0 units (uses youtube-transcript-api, no quota)

**Optimization strategies**:
- Cache search results (24 hours)
- Batch video detail requests
- Use transcript API primarily (no quota)
- Implement exponential backoff for quota errors

### Transcript Availability

**Challenges**:
- ~30% of videos have no transcripts
- Auto-generated captions may be inaccurate
- Multiple languages to handle
- Very long videos (>2 hours) need chunking

**Solutions**:
- Fallback chain: Manual transcript → Auto captions → Description
- Language preference order
- Transcript chunking for long videos
- Quality score based on transcript source

### Performance Optimization

**Parallel Execution**:
```python
# Fetch transcripts in parallel
async with asyncio.TaskGroup() as tg:
    tasks = [
        tg.create_task(self._get_transcript(video_id))
        for video_id in video_ids
    ]
results = [task.result() for task in tasks]
```

**Caching Strategy**:
- Video metadata: 24 hours
- Transcripts: 7 days (rarely change)
- Search results: 1 hour (for same query)

### LLM Usage Optimization

**Cost-conscious approaches**:
- Use embeddings for relevance (cheaper than full LLM)
- Batch summarization requests
- Use cheaper model for initial filtering (Haiku)
- Use better model for final summaries (Sonnet)

## Example Usage

### Example 1: Basic YouTube Search
```python
# User query
"Find YouTube tutorials about Python async programming"

# Agent workflow
1. YouTubeSearchAgent.search()
2. Search YouTube for "Python async programming tutorial"
3. Fetch transcripts for top 10 videos
4. Analyze relevance using LLM
5. Return top 3 videos with summaries

# Response format
{
    "results": [
        {
            "video_id": "xyz123",
            "title": "Python Asyncio Complete Tutorial",
            "channel": "Tech Academy",
            "duration": "45:23",
            "url": "https://youtube.com/watch?v=xyz123",
            "relevance_score": 0.92,
            "summary": "Comprehensive tutorial covering...",
            "key_topics": ["asyncio basics", "event loops", "coroutines"],
            "recommended_for": "Beginners to intermediate",
            "key_timestamps": [
                {"time": "5:30", "topic": "Event loop introduction"},
                {"time": "15:45", "topic": "Creating coroutines"}
            ]
        },
        # ... more videos ...
    ],
    "total_analyzed": 10,
    "query": "Python async programming tutorial"
}
```

### Example 2: Video URL Analysis
```python
# User query
"Summarize this video: https://youtube.com/watch?v=abc789"

# Agent workflow
1. Extract video ID from URL
2. Fetch video metadata
3. Get transcript
4. Generate detailed summary using LLM
5. Extract key insights and timestamps

# Response format
{
    "video_id": "abc789",
    "title": "...",
    "summary": "...",
    "key_insights": [...],
    "chapters": [
        {"start": "0:00", "title": "Introduction", "summary": "..."},
        # ...
    ]
}
```

## Future Enhancements

### Phase 2 Features (Future)
- **Channel analysis**: Analyze entire channels for content quality
- **Playlist summarization**: Summarize video playlists
- **Trending analysis**: Find trending videos in specific topics
- **Comment analysis**: Extract insights from top comments
- **Multi-language support**: Enhanced translation and analysis

### Phase 3 Features (Future)
- **Video comparison**: Compare multiple videos on same topic
- **Citation extraction**: Extract citable facts with timestamps
- **Learning path generation**: Create structured learning paths from videos
- **Quality scoring**: ML-based video quality assessment

## Success Metrics

### Tool Performance
- Transcript fetch success rate: >70%
- Average search latency: <5 seconds
- Relevance accuracy: >80% (human evaluation)

### Agent Performance
- User satisfaction: >4/5 stars
- Result relevance: >80% click-through on top result
- Summary quality: >4/5 stars (human evaluation)

### System Performance
- API quota usage: <80% of daily limit
- Cache hit rate: >60%
- Error rate: <5%

## Risk Mitigation

### Risk 1: API Quota Exhaustion
**Mitigation**: Implement aggressive caching, rate limiting, quota monitoring

### Risk 2: Poor Transcript Quality
**Mitigation**: Multi-source fallback, quality scoring, user feedback loop

### Risk 3: LLM Cost Escalation
**Mitigation**: Use embeddings, batch processing, model tiering

### Risk 4: Slow Response Times
**Mitigation**: Parallel execution, streaming results, progressive enhancement

---

## Advanced Features (Implemented)

### Customizable Configuration

Both video comparison and playlist analysis now support extensive customization through configuration classes.

#### ComparisonConfig Options

```python
from neos.agents.search_agents.youtube_search import (
    ComparisonConfig,
    ComparisonFocus
)

config = ComparisonConfig(
    focus=ComparisonFocus.TECHNICAL_DEPTH,  # or TEACHING_STYLE, PRACTICAL_APPLICATION, BEGINNER_FRIENDLY
    include_timestamps=True,  # Include key timestamps in analysis
    emphasize_differences=True,  # Highlight unique aspects
    include_production_quality=True,  # Evaluate video/audio quality
    max_summary_length="medium"  # short, medium, or long
)
```

**Comparison Focus Options**:
- `TECHNICAL_DEPTH`: Emphasizes accuracy, complexity, and technical details
- `TEACHING_STYLE`: Focuses on pedagogy, pacing, and learning approach
- `PRACTICAL_APPLICATION`: Prioritizes examples and real-world use
- `BEGINNER_FRIENDLY`: Evaluates clarity and learning curve
- `COMPREHENSIVE`: Balanced analysis of all factors

#### PlaylistAnalysisConfig Options

```python
from neos.agents.search_agents.youtube_search import (
    PlaylistAnalysisConfig,
    PlaylistOrderStrategy
)

config = PlaylistAnalysisConfig(
    detect_duplicates=True,  # Find duplicate/similar videos
    use_semantic_similarity=True,  # ⭐ NEW: Use embeddings for concept-level detection
    semantic_similarity_threshold=0.85,  # ⭐ NEW: Similarity threshold (0.0-1.0)
    suggest_order=PlaylistOrderStrategy.OPTIMAL_LEARNING,  # Reorder for best learning
    analyze_progression=True,  # Analyze knowledge building
    identify_gaps=True,  # Find missing topics
    max_videos_to_analyze=20,  # Limit analysis scope
    include_prerequisites=True  # Identify required background
)
```

**Playlist Order Strategies**:
- `ORIGINAL`: Keep playlist order as-is
- `DIFFICULTY`: Sort by estimated difficulty (easy → hard)
- `POPULARITY`: Sort by view count
- `DURATION`: Sort by video length (short → long)
- `OPTIMAL_LEARNING`: Smart ordering (overview → basics → advanced)
- `TOPIC_CLUSTERED` ⭐ NEW: LLM-based grouping by topic/theme
- `PREREQUISITE_CHAIN` ⭐ NEW: LLM-based ordering by knowledge dependencies

---

### Video Comparison

Compare multiple videos side-by-side to help users choose the best content for their needs.

**Features**:
- Compare 2-5 videos simultaneously
- Parallel transcript and metadata analysis
- LLM-powered comparative analysis
- Identifies unique strengths of each video
- Provides recommendations on which to watch first

**Usage**:
```python
from neos.agents.search_agents import YouTubeSearchAgent

agent = YouTubeSearchAgent()

result = await agent.compare_videos(
    video_ids=["video_id_1", "video_id_2", "video_id_3"],
    comparison_context="Python asyncio tutorials",
    session_id="session_123",
    user_id="user_123"
)

# Returns comparison analysis with:
# - Overview of each video
# - Unique strengths
# - Target audience
# - Depth & quality assessment
# - Viewing recommendations
```

**Comparison Analysis Includes**:
1. **Overview**: What each video covers
2. **Unique Strengths**: Distinctive value propositions
3. **Target Audience**: Beginner vs. advanced, use case specific
4. **Depth & Quality**: Technical depth and production quality
5. **Recommendations**: Which videos to prioritize and why

**Use Cases**:
- Choosing between similar tutorials
- Evaluating different teaching approaches
- Finding the right depth level
- Discovering complementary content

---

### Playlist Analysis

Analyze entire YouTube playlists to create structured learning paths with advanced features.

**Features**:
- Extract all videos from a playlist (with pagination)
- **Duplicate Detection**: Identify exact and similar videos
- **Smart Ordering**: Suggest optimal viewing order
- Analyze playlist structure and progression
- Generate comprehensive learning paths
- Identify key videos and prerequisites
- Calculate total time commitment
- Detect knowledge gaps

**Usage**:
```python
from neos.agents.search_agents import YouTubeSearchAgent

agent = YouTubeSearchAgent()

result = await agent.analyze_playlist(
    playlist_id="PLeo1K3hjS3uv5U-Lmlnucd7gqF-3ehIh0",
    session_id="session_123",
    user_id="user_123"
)

# Returns learning path with:
# - Playlist overview and structure
# - Recommended learning order
# - Key videos to focus on
# - Prerequisites and gaps
# - Total time commitment
```

**Analysis Includes**:
1. **Overview**: What the playlist teaches
2. **Structure**: How content is organized
3. **Learning Path**: Recommended approach and order
4. **Key Videos**: Must-watch videos with reasoning
5. **Time Commitment**: Total duration and pacing suggestions
6. **Prerequisites**: Required background knowledge
7. **Gaps**: Missing topics for additional study

**Use Cases**:
- Course planning and curriculum review
- Self-paced learning optimization
- Identifying knowledge gaps
- Creating study schedules

---

### Duplicate Detection

Automatically identify redundant content in playlists to optimize learning time.

**Detection Methods**:
1. **Exact Duplicates**: Videos with identical titles
2. **Similar Videos**: Videos with 70%+ title similarity
3. **Semantic Duplicates** ⭐ NEW: Conceptually similar videos (using OpenAI embeddings)

#### Semantic Duplicate Detection

When `use_semantic_similarity=True`, the system uses OpenAI embeddings to find videos that cover the same concepts even if their titles are different.

```python
config = PlaylistAnalysisConfig(
    detect_duplicates=True,
    use_semantic_similarity=True,
    semantic_similarity_threshold=0.85  # 85% concept similarity
)
```

**How it works**:
1. Combines video title + description for each video
2. Generates embeddings using OpenAI's embedding model
3. Calculates cosine similarity between all video pairs
4. Flags pairs above the threshold as semantic duplicates

**Example Output**:
```python
{
    "semantic_duplicates": [
        {
            "video1_index": 2,
            "video2_index": 7,
            "video1_title": "Python Functions Tutorial",
            "video2_title": "How to Define Functions in Python",
            "semantic_similarity": 0.912,
            "detection_type": "semantic"
        }
    ],
    "semantic_count": 1
}
```

**Note**: Semantic detection requires an OpenAI API key and incurs embedding API costs.

**Output Format**:
```python
{
    "exact_duplicates": [
        {
            "video1_index": 5,
            "video2_index": 12,
            "video1_title": "Python Basics Part 1",
            "video2_title": "Python Basics Part 1",
            "reason": "Identical title"
        }
    ],
    "similar_videos": [
        {
            "video1_index": 3,
            "video2_index": 8,
            "video1_title": "Introduction to Python Programming",
            "video2_title": "Python Programming Introduction",
            "similarity_score": 0.85
        }
    ],
    "duplicate_count": 1,
    "similar_count": 1
}
```

**Use Cases**:
- Saving time by skipping redundant content
- Identifying re-uploads or updated versions
- Cleaning up messy playlists
- Curriculum optimization

---

### Optimal Viewing Order

Intelligently reorder playlist videos for better learning outcomes.

**Ordering Strategies**:

1. **OPTIMAL_LEARNING** (Recommended)
   - Phase 1: Short overviews (< 10 min)
   - Phase 2: Core content (10-30 min)
   - Phase 3: Deep dives (> 30 min)

2. **DIFFICULTY**
   - Sorts by estimated difficulty
   - Shorter, popular videos first (assumed easier)
   - Longer, detailed videos last (assumed advanced)

3. **POPULARITY**
   - Most viewed videos first
   - Useful for finding highest-quality content

4. **DURATION**
   - Shortest videos first
   - Good for quick wins and momentum

5. **ORIGINAL**
   - Maintains creator's intended order
   - Respects playlist structure

6. **TOPIC_CLUSTERED** ⭐ NEW (LLM-based)
   - Groups videos by topic/theme
   - Uses LLM to analyze video titles and cluster related content
   - Within each cluster, orders from overview to detail
   - Ideal for playlists covering multiple related topics

7. **PREREQUISITE_CHAIN** ⭐ NEW (LLM-based)
   - Orders videos by knowledge dependencies
   - Uses LLM to detect concept dependencies
   - Places foundational videos before advanced ones
   - Ideal for learning progressions and skill building

```python
# Topic clustering example
config = PlaylistAnalysisConfig(
    suggest_order=PlaylistOrderStrategy.TOPIC_CLUSTERED
)

# Prerequisite chain example
config = PlaylistAnalysisConfig(
    suggest_order=PlaylistOrderStrategy.PREREQUISITE_CHAIN,
    include_prerequisites=True
)
```

**Example Output**:
```python
{
    "suggested_order": [
        {
            "video_id": "abc123",
            "title": "Quick Overview",
            "original_index": 5,  # Was 6th in playlist
            "suggested_order": 1,  # Now 1st
            "duration_seconds": 480
        },
        # ... more videos
    ],
    "order_strategy": "optimal_learning"
}
```

**USER CONTRIBUTION POINT**: The `_calculate_optimal_order()` method can be customized to implement domain-specific ordering logic (e.g., prerequisite chains, topic clustering).

---

### Implementation Details

**New Tool Operations**:
```python
# Get playlist metadata
await mcp_manager.execute_tool(
    "youtube_mcp",
    {
        "operation": "get_playlist_info",
        "playlist_id": "playlist_id"
    }
)

# Get all videos in playlist
await mcp_manager.execute_tool(
    "youtube_mcp",
    {
        "operation": "get_playlist_videos",
        "playlist_id": "playlist_id",
        "max_results": 50
    }
)

# Compare videos
await mcp_manager.execute_tool(
    "youtube_mcp",
    {
        "operation": "compare_videos",
        "video_ids": ["id1", "id2", "id3"],
        "include_transcripts": True
    }
)
```

**Agent Methods**:
- `YouTubeSearchAgent.compare_videos()` - Intelligent video comparison
- `YouTubeSearchAgent.analyze_playlist()` - Learning path generation

---

## Complete Example Usage

See [examples/youtube_integration_examples.py](../examples/youtube_integration_examples.py) for comprehensive usage examples including:

**Basic Operations**:
1. **Basic Video Search** - Find videos by keywords
2. **Transcript Extraction** - Get video transcripts
3. **Video Analysis** - Complete metadata + transcript analysis
4. **Intelligent Search** - Agent-powered search with relevance ranking

**Advanced Features**:
5. **Video Comparison** - Compare multiple videos
6. **Playlist Info** - Get playlist metadata
7. **Learning Path** - Generate structured learning paths
8. **Playlist Videos** - Extract all videos from playlists

**Enhanced Configuration**:
9. **Custom Comparison** - Use ComparisonConfig for focused analysis
10. **Duplicate Detection** - Find redundant content in playlists
11. **Technical Depth Focus** - Customize comparison criteria

**Advanced AI Features** ⭐ NEW:
12. **Semantic Duplicate Detection** - Uses OpenAI embeddings to find concept-level duplicates
13. **Topic-Clustered Ordering** - LLM-based grouping by topic/theme
14. **Prerequisite Chain Ordering** - LLM-based ordering by knowledge dependencies

---

## Next Steps

1. **Review this plan** and provide feedback on approach
2. **Prioritize features** - which to implement first?
3. **Begin Phase 1** - Set up foundation and dependencies
4. **Implement Tool Layer** with your participation on scoring/summarization logic
5. **Test and iterate** based on real-world usage

## Questions for Discussion

1. **API Key**: Do you have a YouTube Data API v3 key, or should we optimize for transcript-only usage?
2. **Language Priority**: Which languages should we prioritize (English, Korean, both)?
3. **Use Cases**: What are the primary use cases? (research, learning, entertainment)
4. **Integration Level**: Should this be tightly integrated with existing search, or standalone capability?
5. **Summary Style**: Prefer technical deep dives or concise overviews?

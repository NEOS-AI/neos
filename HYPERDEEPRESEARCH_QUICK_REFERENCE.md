# HyperDeepResearch Agent - Quick Reference Guide

## Quick Facts

| Aspect | Details |
|--------|---------|
| **Location** | `/home/user/neos/neos/agents/search_agents/hyper_deep_research/` |
| **Main File** | `agent.py` (1424 lines) |
| **Class** | `HyperDeepResearchAgent` (extends `SearchAgent`) |
| **Total Code** | ~2,150 lines across 4 packages |
| **Phases** | 8 sequential research phases |
| **Languages** | English, Korean, Japanese |
| **Tavily Integration** | Yes (rate-limited at 3 concurrent, 0.5s min interval) |

---

## 8-Phase Research Process

```
Phase 1: Topic Analysis          → Extract research questions
Phase 2: Research Planning       → Define methodology
Phase 3: Data Collection         → Gather 100-200 sources
Phase 4: Deep Analysis (3x)      → Iterative insights
Phase 5: Gap Analysis            → Identify & fill knowledge gaps
Phase 6: Cross-Validation        → Triangulate findings
Phase 7: Critical Analysis       → Multi-perspective review
Phase 8: Report Synthesis        → Generate final report
```

**Estimated Total Time:** 60-90 minutes

---

## Key Strengths

✅ **Modular Architecture** - Clean separation (prompts, repository, utils, agent)
✅ **Multilingual Support** - Strategy pattern for language-specific prompts
✅ **Comprehensive** - 100-200+ sources, 8 analysis phases
✅ **Quality Assurance** - Criticism feedback integration
✅ **Database Persistence** - Complete research tracking
✅ **Rate Limiting** - Intelligent API throttling
✅ **Memory Optimized** - Batch storage with limited RAM footprint

---

## Core Components

| Component | Purpose | Lines |
|-----------|---------|-------|
| **agent.py** | Main orchestration | 1424 |
| **prompts/** | Multilingual templates | 1055 |
| **repository/** | Database access (Repository pattern) | 429 |
| **utils/** | Language detection & data processing | 221 |

---

## Main Methods

### Entry Point
```python
async def execute(query: str, context: Dict) -> Dict[str, Any]
```

### Core Research
```python
async def _run_research_process(...)  # Main orchestrator

# Phase implementations
async def _analyze_topic()             # Phase 1
async def _plan_research()             # Phase 2
async def _collect_initial_data()      # Phase 3
async def _perform_deep_analysis()     # Phase 4
async def _analyze_gaps()              # Phase 5
async def _cross_validate_sources()    # Phase 6
async def _perform_critical_analysis() # Phase 7
async def _synthesize_final_report()   # Phase 8
```

---

## Research Configuration

```python
{
    "multi_query_expansion": 20,       # Query variations
    "parallel_search_batches": 5,      # Batch groups
    "target_total_sources": 200,       # Target sources
    "analysis_iterations": 3,          # Deep analysis rounds
    "cross_validation_rounds": 2,      # Validation passes
    "max_sections": 15,                # Report sections
    "quality_threshold": 0.9           # Quality score needed
}
```

---

## Top Limitations

| # | Limitation | Impact | Fix Difficulty |
|---|-----------|--------|-----------------|
| 1 | Language support (3 only) | Limited reach | ⭐ Easy |
| 2 | Rough token estimation | Cost accuracy | ⭐ Easy |
| 3 | No source credibility scoring | Quality varies | ⭐⭐ Medium |
| 4 | Limited content extraction | Detail loss | ⭐⭐ Medium |
| 5 | No retry logic | Lost data | ⭐⭐ Medium |
| 6 | Fixed batch size | Suboptimal performance | ⭐⭐ Medium |
| 7 | Mix of print/logging | Hard to debug | ⭐⭐ Medium |
| 8 | Limited unit tests | Risk of regression | ⭐⭐⭐ Hard |
| 9 | Code organization | Large agent.py | ⭐⭐⭐ Hard |
| 10 | No streaming support | Long wait time | ⭐⭐⭐ Hard |

---

## Top Improvement Opportunities

### Quick Wins (1-2 hours each)
- [ ] Add Chinese language support
- [ ] Implement tiktoken for accurate token counting
- [ ] Add source domain authority ranking
- [ ] Implement exponential backoff retry logic

### Medium-term (1-2 days each)
- [ ] Adaptive batch sizing
- [ ] Content extraction/summarization service
- [ ] Database query optimization & indexing
- [ ] Comprehensive logging system

### Long-term (1+ weeks)
- [ ] Server-Sent Events (SSE) streaming
- [ ] Multi-source search integration (Google, Bing, etc.)
- [ ] Knowledge graph construction
- [ ] Human-in-the-loop refinement

---

## Database Schema

4 Tables:
- `hyper_research_reports` - Report metadata
- `hyper_research_sections` - Report sections
- `hyper_research_data_collection` - Search queries
- `hyper_research_criticism_feedback` - Quality feedback

---

## Integration Points

### API Routes
```
POST   /api/v1/deep-research/start
GET    /api/v1/deep-research/{report_id}/stream
GET    /api/v1/deep-research/{report_id}
GET    /api/v1/conversations/{conv_id}/deep-research
```

### CLI
```bash
neos research "your query"
```

### Web UI
- Deep Research chat mode
- Real-time progress streaming
- Report display

---

## File Locations Summary

```
Main Implementation:
  /home/user/neos/neos/agents/search_agents/hyper_deep_research/

Sub-agents Used:
  - PlanningAgent
  - MultiQuerySearchAgent
  - CriticismFeedbackAgent

Integration Files:
  - neos/cli.py (CLI)
  - neos/api/handlers/deep_research_handlers.py (API)
  - neos/api/models/deep_research_models.py (Data models)
  - neos/api/deep_research_routes.py (Routes)

Database:
  - db/hyper_deep_research.sql
  - db/migrations/001_add_conversation_to_deep_research.sql
```

---

## How to Use

### Basic Python
```python
from neos.agents.search_agents.hyper_deep_research import HyperDeepResearchAgent

agent = HyperDeepResearchAgent()
result = await agent.execute(
    query="Your research topic",
    context={
        "session_id": "session_123",
        "user_id": "user_456"
    }
)
```

### Via Web UI
1. Select "Deep Research" mode
2. Enter research topic
3. Watch real-time progress
4. Get comprehensive markdown report

---

## Performance Profile

| Metric | Value |
|--------|-------|
| **Average Runtime** | 60-90 minutes |
| **Typical Sources Collected** | 100-200+ |
| **API Calls** | 150-200 |
| **LLM Tokens** | 50,000-100,000 |
| **Database Size** | ~1 MB per report |
| **Memory Usage** | 50-100 MB |
| **Report Sections** | 12-15 |

---

## Design Patterns Used

- **Repository Pattern** - Database abstraction layer
- **Strategy Pattern** - Language-specific prompt selection
- **Builder Pattern** - Report construction
- **Singleton** - LLM initialization
- **Async/Await** - Concurrent operations

---

## Next Steps for Enhancement

1. **Read Full Analysis:** `/home/user/neos/HYPERDEEPRESEARCH_ANALYSIS.md`
2. **Review Code:** Start with `/home/user/neos/neos/agents/search_agents/hyper_deep_research/agent.py`
3. **Check Integration:** Look at `deep_research_handlers.py` for API integration
4. **Explore Prompts:** Review language-specific prompts in `prompts/` directory
5. **Plan Improvements:** Use limitations and opportunities sections as roadmap

---

Generated: 2025-11-16
Analysis Version: 1.0


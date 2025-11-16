# HyperDeepResearch Agent - Code Map & Quick Lookup

## Complete File Structure

```
/home/user/neos/
├── neos/agents/search_agents/hyper_deep_research/
│   ├── __init__.py                                    (14 lines)
│   │   └─ Exports: HyperDeepResearchAgent
│   │
│   ├── agent.py                                       (1424 lines)  ⭐ MAIN FILE
│   │   └─ Class: HyperDeepResearchAgent
│   │     ├─ __init__()
│   │     ├─ execute() [Entry point]
│   │     ├─ _run_research_process() [8 phases]
│   │     │
│   │     ├─ PHASE METHODS
│   │     │ ├─ _analyze_topic()
│   │     │ ├─ _plan_research()
│   │     │ ├─ _collect_initial_data()
│   │     │ ├─ _perform_deep_analysis()
│   │     │ ├─ _analyze_gaps()
│   │     │ ├─ _cross_validate_sources()
│   │     │ ├─ _perform_critical_analysis()
│   │     │ └─ _synthesize_final_report()
│   │     │
│   │     ├─ DATA COLLECTION
│   │     │ ├─ _generate_query_variations()
│   │     │ ├─ _execute_complex_searches()
│   │     │ ├─ _execute_parallel_searches()
│   │     │ ├─ _search_batch_parallel()
│   │     │ └─ _single_tavily_search()
│   │     │
│   │     ├─ ANALYSIS
│   │     │ ├─ _summarize_collected_data()
│   │     │ ├─ _execute_analysis_round()
│   │     │ ├─ _synthesize_analysis_rounds()
│   │     │ └─ _identify_knowledge_gaps()
│   │     │
│   │     ├─ GAPS
│   │     │ ├─ _investigate_gaps()
│   │     │ ├─ _generate_gap_queries()
│   │     │ └─ _summarize_gap_investigation()
│   │     │
│   │     ├─ FEEDBACK & QUALITY
│   │     │ ├─ _process_criticism_feedback()
│   │     │ └─ _conduct_feedback_research()
│   │     │
│   │     ├─ REPORT
│   │     │ ├─ _plan_report_structure()
│   │     │ ├─ _generate_final_section()
│   │     │ └─ _assemble_report()
│   │     │
│   │     └─ UTILITIES
│   │       ├─ _store_sources_batch()
│   │       ├─ _get_all_sources_sample()
│   │       ├─ _track_llm_call()
│   │       ├─ _update_report_metadata()
│   │       └─ _print_research_summary()
│   │
│   ├── prompts/                                       (1055 lines total)
│   │   ├── __init__.py
│   │   ├── analysis_prompts.py             (270 lines)
│   │   │   └─ Class: AnalysisPrompts
│   │   │     ├─ get_data_summary_prompt()
│   │   │     ├─ get_gap_identification_prompt()
│   │   │     ├─ get_iterative_analysis_prompt()
│   │   │     ├─ get_synthesis_prompt()
│   │   │     └─ get_gap_summary_prompt()
│   │   │
│   │   ├── query_generation_prompts.py    (116 lines)
│   │   │   └─ Class: QueryGenerationPrompts
│   │   │     ├─ get_multi_query_prompt()
│   │   │     └─ get_gap_query_prompt()
│   │   │
│   │   ├── research_planning_prompts.py   (133 lines)
│   │   │   └─ Class: ResearchPlanningPrompts
│   │   │     └─ get_prompt()
│   │   │
│   │   ├── topic_analysis_prompts.py      (136 lines)
│   │   │   └─ Class: TopicAnalysisPrompts
│   │   │     └─ get_prompt()
│   │   │
│   │   └── validation_prompts.py          (385 lines)
│   │       └─ Class: ValidationPrompts
│   │         ├─ get_cross_validation_prompt()
│   │         ├─ get_critical_thinking_prompt()
│   │         ├─ get_report_structure_prompt()
│   │         └─ get_final_section_prompt()
│   │
│   ├── repository/                                    (429 lines)
│   │   ├── __init__.py
│   │   └── hyper_research_repository.py   (429 lines)  ⭐ DATA ACCESS
│   │       └─ Class: HyperResearchRepository
│   │         ├─ TABLE MANAGEMENT
│   │         │ ├─ ensure_tables_exist()
│   │         │ └─ _create_tables()
│   │         │
│   │         ├─ REPORT OPERATIONS
│   │         │ ├─ create_report()
│   │         │ ├─ update_report_status()
│   │         │ └─ update_report_metadata()
│   │         │
│   │         ├─ SECTION OPERATIONS
│   │         │ └─ create_section()
│   │         │
│   │         ├─ DATA COLLECTION
│   │         │ └─ record_data_collection()
│   │         │
│   │         └─ FEEDBACK OPERATIONS
│   │           └─ record_criticism_feedback()
│   │
│   └── utils/                                        (221 lines)
│       ├── __init__.py
│       ├── language_detector.py           (97 lines)
│       │   └─ Class: LanguageDetector
│       │     ├─ detect()       [detects en/ko/ja]
│       │     └─ get_language_name()
│       │
│       └── data_processor.py              (124 lines)
│           └─ Class: DataProcessor
│             ├─ deduplicate_sources()
│             ├─ extract_domain()
│             ├─ extract_research_questions()
│             ├─ extract_search_strategies()
│             └─ extract_unique_domains()
│
├── db/
│   ├── hyper_deep_research.sql
│   └── migrations/
│       └── 001_add_conversation_to_deep_research.sql
│
└── neos/api/
    ├── handlers/
    │   └── deep_research_handlers.py                  (API Integration)
    │       └─ start_deep_research()
    │       └─ deep_research_stream_generator()
    │       └─ get_deep_research_report()
    │       └─ list_conversation_deep_research()
    │
    ├── models/
    │   └── deep_research_models.py                   (Pydantic Models)
    │       ├─ DeepResearchRequest
    │       ├─ DeepResearchEvent
    │       ├─ DeepResearchReport
    │       └─ [5+ other models]
    │
    ├── deep_research_routes.py                       (FastAPI Routes)
    │   └─ POST /api/v1/deep-research/start
    │   └─ GET /api/v1/deep-research/{report_id}/stream
    │   └─ GET /api/v1/deep-research/{report_id}
    │   └─ GET /api/v1/conversations/{conv_id}/deep-research
    │
    └── cli.py                                         (CLI Integration)
        └─ research command
```

---

## Key Code Locations by Use Case

### Want to understand the main workflow?
**File:** `/home/user/neos/neos/agents/search_agents/hyper_deep_research/agent.py`
**Lines:** 157-372 (`execute()` and `_run_research_process()`)

### Want to see database schema?
**Files:** 
- `/home/user/neos/neos/agents/search_agents/hyper_deep_research/repository/hyper_research_repository.py` (Lines 20-130)
- `/home/user/neos/db/hyper_deep_research.sql`

### Want to understand query generation?
**Files:**
- `/home/user/neos/neos/agents/search_agents/hyper_deep_research/agent.py` (Lines 719-763)
- `/home/user/neos/neos/agents/search_agents/hyper_deep_research/prompts/query_generation_prompts.py`

### Want to see Tavily integration?
**File:** `/home/user/neos/neos/agents/search_agents/hyper_deep_research/agent.py`
**Lines:** 
- Initialization: 97-119
- Single search: 863-928
- Batch execution: 816-843

### Want to understand multilingual support?
**Files:**
- Language detection: `/home/user/neos/neos/agents/search_agents/hyper_deep_research/utils/language_detector.py` (Lines 29-79)
- All prompt files in `/home/user/neos/neos/agents/search_agents/hyper_deep_research/prompts/`

### Want to understand data collection process?
**File:** `/home/user/neos/neos/agents/search_agents/hyper_deep_research/agent.py`
**Lines:** 469-516 (`_collect_initial_data()`)

### Want to see deep analysis implementation?
**File:** `/home/user/neos/neos/agents/search_agents/hyper_deep_research/agent.py`
**Lines:** 518-547 (`_perform_deep_analysis()`)

### Want to understand gap analysis?
**File:** `/home/user/neos/neos/agents/search_agents/hyper_deep_research/agent.py`
**Lines:** 549-595 (`_analyze_gaps()`)

### Want to understand API integration?
**Files:**
- Routes: `/home/user/neos/neos/api/deep_research_routes.py`
- Handlers: `/home/user/neos/neos/api/handlers/deep_research_handlers.py`
- Models: `/home/user/neos/neos/api/models/deep_research_models.py`

### Want to understand database operations?
**File:** `/home/user/neos/neos/agents/search_agents/hyper_deep_research/repository/hyper_research_repository.py`

---

## Important Configuration Details

### Research Configuration (agent.py, lines 74-95)
```python
self.config = {
    "multi_query_expansion": 20,           # Line 76
    "parallel_search_batches": 5,          # Line 77
    "max_queries_per_phase": 30,           # Line 80
    "results_per_query": 10,               # Line 81
    "min_total_sources": 100,              # Line 82
    "target_total_sources": 200,           # Line 83
    "analysis_iterations": 3,              # Line 86
    "cross_validation_rounds": 2,          # Line 87
    "critical_thinking_passes": 2,         # Line 88
    "max_sections": 15,                    # Line 91
    "min_sources_per_section": 5,          # Line 92
    "timeout_per_phase": 900,              # Line 93
    "quality_threshold": 0.9               # Line 94
}
```

### Research Metadata Tracking (agent.py, lines 126-140)
```python
self.research_metadata = {
    "total_queries_executed": 0,           # Line 127
    "total_sources_collected": 0,          # Line 128
    "unique_domains": set(),               # Line 129
    "analysis_iterations_completed": 0,    # Line 130
    "critical_reviews_completed": 0,       # Line 131
    "multi_query_searches": 0,             # Line 132
    "criticism_feedbacks_generated": 0,    # Line 133
    "additional_research_triggered": 0,    # Line 134
    "api_rate_limit_hits": 0,              # Line 135
    "llm_calls": 0,                        # Line 137
    "estimated_total_tokens": 0,           # Line 138
    "llm_calls_by_phase": {}               # Line 139
}
```

### Rate Limiting (agent.py, lines 114-118)
```python
self.tavily_rate_limiter = asyncio.Semaphore(
    settings.DEEP_RESEARCH_MAX_CONCURRENT_REQUESTS  # Max 3
)
self.min_request_interval = settings.DEEP_RESEARCH_MIN_REQUEST_INTERVAL  # 0.5s
self.last_request_time = 0
```

---

## 8-Phase Process Implementation Map

| Phase | Method | File | Lines | Key Steps |
|-------|--------|------|-------|-----------|
| 1 | `_analyze_topic()` | agent.py | 376-424 | Topic analysis, extract questions |
| 2 | `_plan_research()` | agent.py | 426-467 | Create methodology, extract strategies |
| 3 | `_collect_initial_data()` | agent.py | 469-516 | Generate queries, execute searches |
| 4 | `_perform_deep_analysis()` | agent.py | 518-547 | 3 iterations, synthesize insights |
| 5 | `_analyze_gaps()` | agent.py | 549-595 | Identify gaps, fill with research |
| 6 | `_cross_validate_sources()` | agent.py | 596-634 | Triangulate, verify claims |
| 7 | `_perform_critical_analysis()` | agent.py | 636-669 | Multi-perspective, identify biases |
| 8 | `_synthesize_final_report()` | agent.py | 671-715 | Plan structure, generate sections |

---

## Database Tables Reference

### hyper_research_reports
**Location:** repository.py, lines 40-61
**Key columns:** report_id, user_id, session_id, research_topic, research_status, quality_score

### hyper_research_sections
**Location:** repository.py, lines 64-86
**Key columns:** section_id, report_id, section_order, section_type, section_content

### hyper_research_data_collection
**Location:** repository.py, lines 89-104
**Key columns:** collection_id, report_id, query_text, search_phase, results

### hyper_research_criticism_feedback
**Location:** repository.py, lines 107-123
**Key columns:** feedback_id, report_id, section_type, severity, has_issues, suggested_queries

---

## Sub-Agent Dependencies

The agent uses three sub-agents:

1. **PlanningAgent**
   - Used in: Phase 2 (`_plan_research()`)
   - Purpose: Create research methodology

2. **MultiQuerySearchAgent**
   - Used in: Phases 3, 5, and feedback research
   - Purpose: Execute complex multi-query searches
   - Location: `neos/agents/search_agents/multi_query_search.py`

3. **CriticismFeedbackAgent**
   - Used in: After phases 4, 6
   - Purpose: Review quality, identify issues
   - Location: `neos/agents/search_agents/criticism_feedback_agent.py`

---

## API Endpoints Quick Reference

```
POST /api/v1/deep-research/start
  Input: user_id, conversation_id, research_topic, session_id
  Output: report_id, status
  Handler: deep_research_handlers.py, start_deep_research()

GET /api/v1/deep-research/{report_id}/stream
  Purpose: SSE stream of research progress
  Handler: deep_research_handlers.py, deep_research_stream_generator()

GET /api/v1/deep-research/{report_id}
  Output: Complete report with all sections
  Handler: deep_research_handlers.py, get_deep_research_report()

GET /api/v1/conversations/{conversation_id}/deep-research
  Output: List of all research reports for conversation
  Handler: deep_research_handlers.py, list_conversation_deep_research()
```

---

## Code Statistics

| Metric | Value |
|--------|-------|
| Total lines of code | ~2,150 |
| Main agent file | 1,424 lines |
| Prompt templates | 1,055 lines |
| Repository/DB layer | 429 lines |
| Utility functions | 221 lines |
| Number of methods | 40+ |
| Database tables | 4 |
| Languages supported | 3 (en, ko, ja) |

---

## Quick Navigation

**For understanding workflow:** Start with `agent.py` lines 157-372
**For API integration:** Check `deep_research_handlers.py`
**For database schema:** See `repository.py` lines 20-130
**For language support:** Review all files in `prompts/` directory
**For data processing:** Look at `utils/data_processor.py`
**For language detection:** Check `utils/language_detector.py`

---

Generated: 2025-11-16
Version: 1.0


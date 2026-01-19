# NEOS Evaluation Framework - Implementation Plan

**Version:** 1.0
**Date:** 2026-01-11
**Status:** Planning Phase

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Framework Architecture](#framework-architecture)
3. [Evaluation Types](#evaluation-types)
4. [Grader Design](#grader-design)
5. [Metrics & Scoring](#metrics--scoring)
6. [Task Dataset Design](#task-dataset-design)
7. [Implementation Plan](#implementation-plan)
8. [File Structure](#file-structure)
9. [Technology Stack](#technology-stack)
10. [Timeline & Phases](#timeline--phases)

---

## Executive Summary

### Objective
Build an automated evaluation framework for the NEOS Hyper Deep Research Agent that measures:
- Research quality and completeness
- Citation accuracy and source quality
- Iterative refinement effectiveness
- End-to-end workflow performance

### Key Principles (From Anthropic)
1. **Start small**: Begin with 20-50 real-world tasks
2. **Multi-turn evaluation**: Evaluate across all 8 research phases
3. **Layered grading**: Combine code-based, model-based, and human graders
4. **Outcome-focused**: Grade final reports, not intermediate steps
5. **Unambiguous specifications**: Clear success criteria for each task

### Success Metrics
- Automated evaluation for 80% of common research tasks
- <5% false positive rate (incorrect failures)
- Evaluation runtime: <10 minutes per task
- Cost: <$0.50 per evaluation

---

## Framework Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Evaluation Orchestrator                     │
│                    (Main Entry Point)                           │
└─────────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│   Task       │   │   Trial      │   │   Grader     │
│   Manager    │   │   Runner     │   │   Manager    │
└──────────────┘   └──────────────┘   └──────────────┘
        │                   │                   │
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Task Store  │   │  Transcript  │   │  Grader      │
│  (JSON/DB)   │   │  Capture     │   │  Registry    │
└──────────────┘   └──────────────┘   └──────────────┘
                                              │
                    ┌─────────────────────────┼─────────────┐
                    │                         │             │
                    ▼                         ▼             ▼
            ┌──────────────┐       ┌──────────────┐ ┌──────────────┐
            │ Code-Based   │       │ Model-Based  │ │    Human     │
            │   Graders    │       │   Graders    │ │   Graders    │
            └──────────────┘       └──────────────┘ └──────────────┘
                    │                         │             │
                    └─────────────────────────┴─────────────┘
                                      │
                                      ▼
                            ┌──────────────────┐
                            │  Results Store   │
                            │  & Analytics     │
                            └──────────────────┘
```

### Core Components

#### 1. **Task**
Represents a single evaluation scenario.

```python
@dataclass
class EvalTask:
    """Single evaluation task."""

    task_id: str                      # Unique identifier
    name: str                         # Human-readable name
    query: str                        # Research query

    # Expected outcomes
    expected_sections: List[str]      # Required section titles
    required_topics: List[str]        # Must-cover topics
    min_sources: int                  # Minimum source count
    quality_threshold: float          # Overall quality bar

    # Success criteria
    graders: List[str]                # Grader IDs to use
    pass_threshold: float             # Pass@k threshold (0-1)

    # Metadata
    difficulty: str                   # "easy", "medium", "hard"
    category: str                     # "technical", "policy", etc.
    estimated_runtime: int            # Seconds
```

#### 2. **Trial**
Single execution attempt of a task.

```python
@dataclass
class EvalTrial:
    """Single trial of a task."""

    trial_id: str
    task_id: str
    trial_number: int                 # 1, 2, 3 for pass@k

    # Execution
    started_at: datetime
    completed_at: datetime
    status: str                       # "running", "completed", "failed"

    # Agent output
    final_report: str
    metadata: ResearchMetadata        # From agent
    transcript: Dict[str, Any]        # Full execution log

    # Grading results
    grader_scores: Dict[str, float]   # grader_id → score
    overall_score: float              # Weighted average
    passed: bool                      # Met threshold?
```

#### 3. **Grader**
Evaluates trial outcomes.

```python
class BaseGrader(ABC):
    """Base class for all graders."""

    grader_id: str
    grader_type: str  # "code", "model", "human"
    weight: float     # Contribution to overall score

    @abstractmethod
    async def grade(
        self,
        task: EvalTask,
        trial: EvalTrial
    ) -> GraderResult:
        """Grade the trial."""
        pass

@dataclass
class GraderResult:
    """Result from a single grader."""

    grader_id: str
    score: float                      # 0.0 - 1.0
    passed: bool
    feedback: str                     # Human-readable explanation
    details: Dict[str, Any]           # Detailed metrics
```

---

## Evaluation Types

### 1. Capability Evaluations
**Purpose:** Measure what the agent *can* achieve

**Characteristics:**
- Start with low pass rates (20-30%)
- Challenging edge cases
- Track improvement over time

**Example Tasks:**
- "Research quantum computing impact on post-quantum cryptography"
- "Compare regulatory approaches to AI across 5 countries"
- "Analyze contradictory climate change studies"

### 2. Regression Evaluations
**Purpose:** Prevent quality degradation

**Characteristics:**
- High pass rates (95-100%)
- Real user queries from production
- Must maintain performance

**Example Tasks:**
- "What is machine learning?" (basic query)
- "Compare Python vs JavaScript" (comparison)
- "History of the internet" (factual)

### 3. Component Evaluations
**Purpose:** Test individual research phases

**Characteristics:**
- Isolated phase testing
- Faster than full workflow
- Debugging and optimization

**Example Tasks:**
- "Phase 1: Topic analysis quality"
- "Phase 3: Source diversity"
- "Phase 8: Citation accuracy"

---

## Grader Design

### Grader Type 1: Code-Based Graders
**Use Cases:** Objective, deterministic checks

#### CitationAccuracyGrader
```python
class CitationAccuracyGrader(BaseGrader):
    """Check citation format and validity."""

    def grade(self, task, trial) -> GraderResult:
        report = trial.final_report

        # 1. Extract citations: [1], [2,3], etc.
        citations = self._extract_citations(report)

        # 2. Check format validity
        invalid_citations = self._check_format(citations)

        # 3. Verify all citations have sources
        missing_sources = self._check_sources(
            citations,
            trial.metadata
        )

        # 4. Calculate score
        total_citations = len(citations)
        valid_citations = total_citations - len(invalid_citations) - len(missing_sources)
        score = valid_citations / max(total_citations, 1)

        return GraderResult(
            grader_id="citation_accuracy",
            score=score,
            passed=score >= 0.95,
            feedback=f"{valid_citations}/{total_citations} citations valid",
            details={
                "invalid_citations": invalid_citations,
                "missing_sources": missing_sources
            }
        )
```

#### SourceDiversityGrader
```python
class SourceDiversityGrader(BaseGrader):
    """Check source variety and quality."""

    def grade(self, task, trial) -> GraderResult:
        metadata = trial.metadata

        # 1. Extract unique domains
        unique_domains = len(metadata.unique_domains)

        # 2. Check source types (academic, news, etc.)
        source_types = self._classify_sources(metadata)

        # 3. Score diversity
        diversity_score = self._calculate_diversity(
            unique_domains=unique_domains,
            source_types=source_types,
            min_sources=task.min_sources
        )

        return GraderResult(
            grader_id="source_diversity",
            score=diversity_score,
            passed=diversity_score >= 0.7,
            feedback=f"{unique_domains} unique domains, {len(source_types)} source types",
            details={
                "unique_domains": unique_domains,
                "source_types": source_types
            }
        )
```

#### StructureCompletenessGrader
```python
class StructureCompletenessGrader(BaseGrader):
    """Check report has all required sections."""

    def grade(self, task, trial) -> GraderResult:
        report = trial.final_report

        # 1. Extract section titles
        actual_sections = self._extract_sections(report)

        # 2. Check for required sections
        expected = set(task.expected_sections)
        actual = set(actual_sections)
        missing = expected - actual

        # 3. Score
        score = len(actual & expected) / len(expected)

        return GraderResult(
            grader_id="structure_completeness",
            score=score,
            passed=len(missing) == 0,
            feedback=f"{len(actual & expected)}/{len(expected)} required sections present",
            details={
                "missing_sections": list(missing),
                "extra_sections": list(actual - expected)
            }
        )
```

### Grader Type 2: Model-Based Graders

#### TopicCoverageGrader
```python
class TopicCoverageGrader(BaseGrader):
    """LLM-based check for topic coverage."""

    async def grade(self, task, trial) -> GraderResult:
        report = trial.final_report
        required_topics = task.required_topics

        # LLM prompt
        prompt = f"""
You are evaluating a research report for topic coverage.

Required Topics:
{chr(10).join(f"- {t}" for t in required_topics)}

Report:
{report[:5000]}  # Truncate if too long

For each required topic, determine if it is adequately covered (1) or not (0).
Return JSON: {{"topic": "score", ...}}
"""

        # Call LLM
        response = await self._call_llm(prompt)
        coverage = json.loads(response)

        # Score
        score = sum(coverage.values()) / len(coverage)

        return GraderResult(
            grader_id="topic_coverage",
            score=score,
            passed=score >= 0.9,
            feedback=f"{sum(coverage.values())}/{len(coverage)} topics covered",
            details={"topic_coverage": coverage}
        )
```

#### QualityAssessmentGrader
```python
class QualityAssessmentGrader(BaseGrader):
    """LLM-based overall quality assessment."""

    async def grade(self, task, trial) -> GraderResult:
        report = trial.final_report

        # Multi-dimensional quality check
        dimensions = [
            "factual_accuracy",
            "logical_coherence",
            "depth_of_analysis",
            "clarity",
            "objectivity"
        ]

        prompt = f"""
Rate this research report on the following dimensions (0.0-1.0):

{chr(10).join(f"- {d}" for d in dimensions)}

Report:
{report[:8000]}

Return JSON: {{"dimension": score, ...}}
"""

        response = await self._call_llm(prompt)
        scores = json.loads(response)

        # Weighted average
        overall_score = sum(scores.values()) / len(scores)

        return GraderResult(
            grader_id="quality_assessment",
            score=overall_score,
            passed=overall_score >= task.quality_threshold,
            feedback=f"Overall quality: {overall_score:.2f}",
            details={"dimension_scores": scores}
        )
```

### Grader Type 3: Human Graders

#### HumanReviewGrader
```python
class HumanReviewGrader(BaseGrader):
    """Human expert review (for gold-standard evaluation)."""

    async def grade(self, task, trial) -> GraderResult:
        # 1. Generate review interface
        review_data = {
            "task": task,
            "trial": trial,
            "report": trial.final_report
        }

        # 2. Submit for human review
        review_id = await self._submit_for_review(review_data)

        # 3. Wait for review (or mark as pending)
        if self.blocking:
            result = await self._wait_for_review(review_id)
        else:
            return GraderResult(
                grader_id="human_review",
                score=0.0,
                passed=False,
                feedback="Pending human review",
                details={"review_id": review_id, "status": "pending"}
            )

        return result
```

---

## Metrics & Scoring

### Evaluation Metrics

#### 1. pass@k
**Definition:** Probability of at least one success in k trials

```python
def calculate_pass_at_k(trials: List[EvalTrial], k: int) -> float:
    """
    If any trial in k attempts passes, consider task passed.

    Example:
    - 3 trials: [fail, pass, fail]
    - pass@3 = 1.0 (at least one success)
    """
    passed_trials = [t for t in trials[:k] if t.passed]
    return 1.0 if len(passed_trials) > 0 else 0.0
```

**Use Case:** One-time tasks (e.g., "generate a report")

#### 2. pass^k (Consistency)
**Definition:** All k trials must pass

```python
def calculate_pass_all_k(trials: List[EvalTrial], k: int) -> float:
    """
    All trials must pass for consistency.

    Example:
    - 3 trials: [pass, pass, pass]
    - pass^3 = 1.0

    - 3 trials: [pass, pass, fail]
    - pass^3 = 0.0
    """
    passed_trials = [t for t in trials[:k] if t.passed]
    return 1.0 if len(passed_trials) == k else 0.0
```

**Use Case:** Customer-facing agents requiring reliability

#### 3. Average Score
**Definition:** Mean score across trials

```python
def calculate_avg_score(trials: List[EvalTrial]) -> float:
    """Average score across all trials."""
    return sum(t.overall_score for t in trials) / len(trials)
```

**Use Case:** Regression detection, performance tracking

### Grader Weights

Different graders contribute differently to overall score:

```python
GRADER_WEIGHTS = {
    # Code-based graders (40% total)
    "citation_accuracy": 0.15,
    "source_diversity": 0.10,
    "structure_completeness": 0.15,

    # Model-based graders (50% total)
    "topic_coverage": 0.20,
    "quality_assessment": 0.20,
    "factual_accuracy": 0.10,

    # Human graders (10% total)
    "human_review": 0.10,
}

def calculate_overall_score(grader_results: List[GraderResult]) -> float:
    """Weighted average of grader scores."""
    total_weight = 0.0
    weighted_score = 0.0

    for result in grader_results:
        weight = GRADER_WEIGHTS.get(result.grader_id, 0.0)
        weighted_score += result.score * weight
        total_weight += weight

    return weighted_score / total_weight if total_weight > 0 else 0.0
```

---

## Task Dataset Design

### Task Categories

#### Category 1: Factual Research
**Example:**
```json
{
  "task_id": "fact_001",
  "name": "Basic Factual Query",
  "query": "What is quantum computing?",
  "expected_sections": [
    "Introduction",
    "Technical Principles",
    "Current State",
    "Applications"
  ],
  "required_topics": [
    "quantum bits (qubits)",
    "superposition",
    "entanglement",
    "quantum gates"
  ],
  "min_sources": 50,
  "quality_threshold": 0.8,
  "graders": [
    "citation_accuracy",
    "source_diversity",
    "structure_completeness",
    "topic_coverage",
    "quality_assessment"
  ],
  "pass_threshold": 0.8,
  "difficulty": "easy",
  "category": "factual"
}
```

#### Category 2: Comparative Analysis
**Example:**
```json
{
  "task_id": "comp_001",
  "name": "Technology Comparison",
  "query": "Compare TensorFlow vs PyTorch for deep learning",
  "expected_sections": [
    "Introduction",
    "TensorFlow Overview",
    "PyTorch Overview",
    "Feature Comparison",
    "Performance Comparison",
    "Use Case Recommendations",
    "Conclusion"
  ],
  "required_topics": [
    "ease of use",
    "performance",
    "community support",
    "deployment",
    "debugging"
  ],
  "min_sources": 80,
  "quality_threshold": 0.85,
  "graders": [
    "citation_accuracy",
    "source_diversity",
    "structure_completeness",
    "topic_coverage",
    "quality_assessment",
    "comparison_balance"
  ],
  "pass_threshold": 0.85,
  "difficulty": "medium",
  "category": "comparative"
}
```

#### Category 3: Controversial Topics
**Example:**
```json
{
  "task_id": "contro_001",
  "name": "Controversial Topic Analysis",
  "query": "Analyze the debate around AI safety and existential risk",
  "expected_sections": [
    "Introduction",
    "Arguments For AI Safety Concerns",
    "Arguments Against Overstated Risks",
    "Technical Challenges",
    "Governance Approaches",
    "Conclusion"
  ],
  "required_topics": [
    "multiple perspectives",
    "opposing viewpoints",
    "evidence quality",
    "uncertainty acknowledgment"
  ],
  "min_sources": 100,
  "quality_threshold": 0.9,
  "graders": [
    "citation_accuracy",
    "source_diversity",
    "structure_completeness",
    "topic_coverage",
    "quality_assessment",
    "bias_detection",
    "perspective_balance"
  ],
  "pass_threshold": 0.85,
  "difficulty": "hard",
  "category": "controversial"
}
```

### Dataset Structure

```
neos_evals/
├── tasks/
│   ├── factual/
│   │   ├── fact_001_quantum_computing.json
│   │   ├── fact_002_machine_learning.json
│   │   └── ...
│   ├── comparative/
│   │   ├── comp_001_tensorflow_pytorch.json
│   │   ├── comp_002_react_vue.json
│   │   └── ...
│   ├── controversial/
│   │   ├── contro_001_ai_safety.json
│   │   ├── contro_002_climate_policy.json
│   │   └── ...
│   └── regression/
│       ├── reg_001_basic_query.json
│       └── ...
```

---

## Implementation Plan

### Phase 1: Core Infrastructure (Week 1)
**Goal:** Build foundational evaluation framework

**Tasks:**
1. ✅ Design architecture and data models
2. ⬜ Implement core classes:
   - `EvalTask`
   - `EvalTrial`
   - `BaseGrader`
   - `GraderResult`
3. ⬜ Create `EvaluationOrchestrator`
4. ⬜ Implement `TaskManager` (load/store tasks)
5. ⬜ Implement `TrialRunner` (execute agent)
6. ⬜ Create transcript capture system

**Deliverables:**
- Core evaluation engine
- Basic task execution pipeline
- Transcript logging

### Phase 2: Code-Based Graders (Week 2)
**Goal:** Implement deterministic graders

**Tasks:**
1. ⬜ `CitationAccuracyGrader`
2. ⬜ `SourceDiversityGrader`
3. ⬜ `StructureCompletenessGrader`
4. ⬜ `MetadataValidationGrader`
5. ⬜ `PerformanceGrader` (runtime, token usage)

**Deliverables:**
- 5 code-based graders
- Grader registry system
- Unit tests for each grader

### Phase 3: Model-Based Graders (Week 3)
**Goal:** Implement LLM-powered graders

**Tasks:**
1. ⬜ `TopicCoverageGrader`
2. ⬜ `QualityAssessmentGrader`
3. ⬜ `FactualAccuracyGrader`
4. ⬜ `BiasDetectionGrader`
5. ⬜ `PerspectiveBalanceGrader`
6. ⬜ LLM grader calibration system

**Deliverables:**
- 5 model-based graders
- Calibration framework
- Cost tracking

### Phase 4: Task Dataset (Week 4)
**Goal:** Create evaluation task dataset

**Tasks:**
1. ⬜ Collect 50 real user queries from production logs
2. ⬜ Create 20 factual tasks
3. ⬜ Create 15 comparative tasks
4. ⬜ Create 10 controversial tasks
5. ⬜ Create 5 regression tasks
6. ⬜ Write reference solutions for each task

**Deliverables:**
- 50 evaluation tasks
- Task specification format
- Reference solutions

### Phase 5: Metrics & Analytics (Week 5)
**Goal:** Build reporting and analysis tools

**Tasks:**
1. ⬜ Implement pass@k calculation
2. ⬜ Implement pass^k calculation
3. ⬜ Results storage (database)
4. ⬜ Analytics dashboard
5. ⬜ Comparison tools (A/B testing)
6. ⬜ Regression detection alerts

**Deliverables:**
- Metrics calculation engine
- Results database schema
- Basic analytics dashboard

### Phase 6: Integration & Testing (Week 6)
**Goal:** End-to-end testing and refinement

**Tasks:**
1. ⬜ Run full evaluation suite
2. ⬜ Calibrate grader weights
3. ⬜ Tune thresholds
4. ⬜ Fix bugs and edge cases
5. ⬜ Performance optimization
6. ⬜ Documentation

**Deliverables:**
- Working evaluation framework
- Calibrated graders
- Complete documentation

---

## File Structure

```
neos_evals/
├── __init__.py
├── main.py                          # CLI entry point
├── README.md                        # User guide
├── EVALUATION_FRAMEWORK_PLAN.md     # This document
│
├── core/
│   ├── __init__.py
│   ├── task.py                      # EvalTask dataclass
│   ├── trial.py                     # EvalTrial dataclass
│   ├── orchestrator.py              # Main evaluation orchestrator
│   ├── task_manager.py              # Load/store tasks
│   ├── trial_runner.py              # Execute agent trials
│   └── transcript.py                # Capture execution logs
│
├── graders/
│   ├── __init__.py
│   ├── base.py                      # BaseGrader, GraderResult
│   ├── registry.py                  # Grader registration
│   │
│   ├── code_based/
│   │   ├── __init__.py
│   │   ├── citation_accuracy.py
│   │   ├── source_diversity.py
│   │   ├── structure_completeness.py
│   │   ├── metadata_validation.py
│   │   └── performance.py
│   │
│   ├── model_based/
│   │   ├── __init__.py
│   │   ├── topic_coverage.py
│   │   ├── quality_assessment.py
│   │   ├── factual_accuracy.py
│   │   ├── bias_detection.py
│   │   └── perspective_balance.py
│   │
│   └── human/
│       ├── __init__.py
│       └── human_review.py
│
├── metrics/
│   ├── __init__.py
│   ├── pass_at_k.py                 # pass@k calculation
│   ├── consistency.py               # pass^k calculation
│   ├── aggregation.py               # Score aggregation
│   └── statistics.py                # Statistical analysis
│
├── tasks/
│   ├── README.md                    # Task specification guide
│   ├── factual/
│   │   └── *.json
│   ├── comparative/
│   │   └── *.json
│   ├── controversial/
│   │   └── *.json
│   └── regression/
│       └── *.json
│
├── results/
│   ├── trials/                      # Individual trial results
│   ├── aggregated/                  # Aggregated results
│   └── reports/                     # HTML/PDF reports
│
├── storage/
│   ├── __init__.py
│   ├── database.py                  # Results database
│   ├── schemas.py                   # DB schemas
│   └── queries.py                   # DB queries
│
├── analytics/
│   ├── __init__.py
│   ├── dashboard.py                 # Analytics dashboard
│   ├── comparison.py                # A/B comparison tools
│   └── regression_detection.py     # Detect performance drops
│
├── utils/
│   ├── __init__.py
│   ├── text_extraction.py          # Extract sections, citations
│   ├── llm_client.py               # LLM API client for graders
│   └── logging.py                  # Evaluation logging
│
└── tests/
    ├── __init__.py
    ├── test_graders/
    ├── test_metrics/
    └── test_integration/
```

---

## Technology Stack

### Core Dependencies
```toml
[dependencies]
# Core framework
pydantic = "^2.0"              # Data validation
asyncio = "^3.4"               # Async execution

# Database
sqlalchemy = "^2.0"            # ORM
alembic = "^1.12"              # Migrations
sqlite = "^3.40"               # Local DB (dev)
postgresql = "^15"             # Production DB

# LLM for model-based graders
anthropic = "^0.18"            # Claude API
openai = "^1.0"                # Optional: GPT API

# Analytics
pandas = "^2.0"                # Data analysis
plotly = "^5.17"               # Visualizations
streamlit = "^1.28"            # Dashboard (optional)

# Testing
pytest = "^7.4"
pytest-asyncio = "^0.21"
pytest-cov = "^4.1"

# Utilities
rich = "^13.5"                 # CLI formatting
typer = "^0.9"                 # CLI framework
```

### Database Schema

```sql
-- Evaluation tasks
CREATE TABLE eval_tasks (
    task_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    query TEXT NOT NULL,
    expected_sections JSON,
    required_topics JSON,
    min_sources INTEGER,
    quality_threshold REAL,
    graders JSON,
    pass_threshold REAL,
    difficulty TEXT,
    category TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Evaluation trials
CREATE TABLE eval_trials (
    trial_id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES eval_tasks(task_id),
    trial_number INTEGER,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT,
    final_report TEXT,
    metadata JSON,
    transcript JSON,
    grader_scores JSON,
    overall_score REAL,
    passed BOOLEAN
);

-- Grader results
CREATE TABLE grader_results (
    result_id TEXT PRIMARY KEY,
    trial_id TEXT REFERENCES eval_trials(trial_id),
    grader_id TEXT,
    score REAL,
    passed BOOLEAN,
    feedback TEXT,
    details JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Evaluation runs (multiple trials)
CREATE TABLE eval_runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES eval_tasks(task_id),
    k_value INTEGER,                    -- Number of trials
    pass_at_k REAL,
    pass_all_k REAL,
    avg_score REAL,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);
```

---

## Timeline & Phases

### 6-Week Implementation Plan

| Week | Phase | Deliverables | Status |
|------|-------|--------------|--------|
| 1 | Core Infrastructure | Evaluation engine, task execution | 🔵 Planning |
| 2 | Code-Based Graders | 5 deterministic graders | 🔵 Planning |
| 3 | Model-Based Graders | 5 LLM graders, calibration | 🔵 Planning |
| 4 | Task Dataset | 50 evaluation tasks | 🔵 Planning |
| 5 | Metrics & Analytics | Dashboard, reporting | 🔵 Planning |
| 6 | Integration & Testing | End-to-end testing, docs | 🔵 Planning |

### Success Criteria

**Week 1:**
- ✅ Can load and execute a simple task
- ✅ Captures full execution transcript
- ✅ Basic grader interface works

**Week 2:**
- ✅ 5 code-based graders implemented
- ✅ All graders have unit tests
- ✅ Citation and structure checks working

**Week 3:**
- ✅ 5 model-based graders implemented
- ✅ LLM grader calibration system
- ✅ Cost tracking for LLM calls

**Week 4:**
- ✅ 50 diverse evaluation tasks
- ✅ Tasks cover factual, comparative, controversial
- ✅ Reference solutions documented

**Week 5:**
- ✅ pass@k and pass^k metrics
- ✅ Results stored in database
- ✅ Basic analytics dashboard

**Week 6:**
- ✅ Full evaluation suite runs end-to-end
- ✅ Grader weights calibrated
- ✅ Documentation complete

---

## Next Steps

### Immediate Actions

1. **Review this plan** - Discuss and refine architecture
2. **Prioritize phases** - Adjust timeline based on needs
3. **Collect sample tasks** - Gather 10-20 real queries to start
4. **Set up repository** - Initialize `neos_evals/` structure
5. **Begin Phase 1** - Implement core evaluation engine

### Questions to Resolve

1. **Database choice?** SQLite for dev, PostgreSQL for prod?
2. **LLM for graders?** Claude, GPT-4, or both?
3. **Human review system?** Build UI or use external tool?
4. **Dashboard framework?** Streamlit, Dash, or custom?
5. **Integration testing?** How to test against live agent?

### Resources Needed

- **Development time**: 6 weeks (1 developer)
- **LLM API budget**: ~$100-200 for development
- **Human review budget**: Optional, for calibration
- **Database hosting**: PostgreSQL instance (if prod)

---

## References

1. **Anthropic Blog Post**
   - URL: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
   - Key concepts: Multi-turn evals, grader types, pass@k

2. **NEOS Codebase**
   - Agent: `neos/agents/search_agents/hyper_deep_research/`
   - Config: `neos/agents/search_agents/hyper_deep_research/config.py`
   - Metadata: `ResearchMetadata` tracking

3. **Related Work**
   - SWE-bench: Code evaluation benchmark
   - HumanEval: Code generation evaluation
   - WebArena: Web agent evaluation

---

**Document Version:** 1.0
**Last Updated:** 2026-01-11
**Author:** NEOS Evaluation Team
**Status:** ✅ Planning Complete - Ready for Review

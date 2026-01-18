# NEOS Evaluation Framework

Automated evaluation framework for the NEOS Hyper Deep Research Agent, based on Anthropic's best practices for AI agent evaluation.

## 📊 Status

**Current Phase:** ✅ Phase 1 - Core Infrastructure (COMPLETE)

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ **COMPLETE** | Core evaluation engine, task management, trial execution |
| Phase 2 | 🔜 Next | Code-based graders implementation |
| Phase 3 | ⏳ Planned | Model-based graders implementation |
| Phase 4 | ⏳ Planned | Task dataset creation (50 tasks) |
| Phase 5 | ⏳ Planned | Metrics & analytics dashboard |
| Phase 6 | ⏳ Planned | Integration & testing |

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              Evaluation Orchestrator                        │
│              (Coordinates evaluation pipeline)              │
└─────────────────────────────────────────────────────────────┘
                          │
      ┌───────────────────┼───────────────────┐
      │                   │                   │
      ▼                   ▼                   ▼
┌──────────┐      ┌──────────────┐     ┌──────────┐
│   Task   │      │    Trial     │     │  Grader  │
│ Manager  │      │    Runner    │     │ Registry │
└──────────┘      └──────────────┘     └──────────┘
```

### Core Components (Phase 1 ✅)

#### 1. **EvalTask** - Task Definition
Represents a single evaluation scenario with:
- Input query
- Expected outcomes (sections, topics, sources)
- Success criteria (graders, thresholds)
- Metadata (difficulty, category)

#### 2. **EvalTrial** - Trial Execution
Represents one execution attempt with:
- Agent outputs (report, metadata)
- Execution transcript
- Grading results
- Performance metrics

#### 3. **BaseGrader** - Grader Interface
Abstract base for all graders:
- Code-based: Deterministic checks (citations, structure)
- Model-based: LLM-powered evaluation (quality, coverage)
- Human: Expert review for calibration

#### 4. **TaskManager** - Task Loading/Storage
Manages evaluation tasks:
- Load tasks from JSON files
- Organize by category (factual, comparative, controversial)
- Validate task definitions
- Create example tasks

#### 5. **TrialRunner** - Agent Execution
Executes research agent:
- Runs agent with timeout
- Captures full transcript
- Handles errors gracefully
- Records metadata

#### 6. **TranscriptCapture** - Execution Logging
Records detailed execution logs:
- Phase transitions
- LLM API calls
- Search queries
- Timing information

#### 7. **EvaluationOrchestrator** - Main Coordinator
Coordinates entire pipeline:
- Load tasks
- Execute trials
- Run graders
- Calculate metrics (pass@k, pass^k)
- Store results

## 🚀 Quick Start

### Installation

```bash
# From the neos root directory
cd neos_evals

# Install dependencies (using uv or pip)
uv pip install -e .
# or
pip install -e .
```

### Basic Usage

```bash
# Show framework information
python main.py info

# Create example tasks for testing
python main.py create-example-tasks --num 5

# List available tasks
python main.py list-tasks

# List tasks by category
python main.py list-tasks --category factual
```

## 📝 Task Definition Example

```json
{
  "task_id": "task_001",
  "name": "Quantum Computing Basics",
  "query": "What is quantum computing?",
  "expected_sections": [
    "Introduction",
    "Technical Principles",
    "Applications"
  ],
  "required_topics": [
    "qubits",
    "superposition",
    "entanglement"
  ],
  "min_sources": 50,
  "quality_threshold": 0.8,
  "graders": [
    "citation_accuracy",
    "source_diversity",
    "structure_completeness",
    "topic_coverage"
  ],
  "pass_threshold": 0.8,
  "difficulty": "easy",
  "category": "factual"
}
```

## 💻 Python API Usage

### Example: Create and Save a Task

```python
from core import TaskManager, EvalTask

# Initialize task manager
task_manager = TaskManager("tasks/")

# Create a task
task = EvalTask(
    name="Basic ML Research",
    query="What is machine learning?",
    expected_sections=["Introduction", "Techniques", "Applications"],
    required_topics=["supervised learning", "neural networks"],
    min_sources=50,
    quality_threshold=0.8,
    graders=["citation_accuracy", "topic_coverage"],
    pass_threshold=0.8,
    difficulty="easy",
    category="factual"
)

# Save task
task_manager.save_task(task, category="factual")

# Load task back
loaded_task = task_manager.load_task("factual/basic_ml_research.json")
```

### Example: Execute a Trial (Requires Phase 2+)

```python
from core import TrialRunner, EvalTrial
from neos.agents.search_agents.hyper_deep_research import HyperDeepResearchAgent

# Initialize runner
runner = TrialRunner(
    agent_class=HyperDeepResearchAgent,
    default_timeout=900  # 15 minutes
)

# Create trial
trial = EvalTrial(
    task_id=task.task_id,
    trial_number=1
)

# Execute
await runner.execute_trial(task, trial)

# Check results
print(f"Status: {trial.status}")
print(f"Report length: {len(trial.final_report)}")
print(f"Duration: {trial.duration_seconds}s")
```

## 📊 Evaluation Metrics

### pass@k (Capability)
**Definition:** Probability of at least one success in k trials

**Use Case:** Measure what the agent *can* achieve

```python
# If any trial passes, task passes
pass_at_3 = 1.0  # At least one success in 3 trials
```

### pass^k (Consistency)
**Definition:** All k trials must succeed

**Use Case:** Measure reliability for production use

```python
# All trials must pass
pass_all_3 = 1.0  # All 3 trials succeeded
```

### Average Score
**Definition:** Mean score across all graders and trials

```python
# Weighted average of grader scores
avg_score = 0.87  # 87% average quality
```

## 🗂️ Directory Structure

```
neos_evals/
├── core/                        # ✅ Core framework (Phase 1)
│   ├── __init__.py
│   ├── task.py                  # EvalTask data model
│   ├── trial.py                 # EvalTrial data model
│   ├── task_manager.py          # Task loading/storage
│   ├── trial_runner.py          # Agent execution
│   ├── transcript.py            # Execution logging
│   └── orchestrator.py          # Main coordinator
│
├── graders/                     # 🔜 Phase 2-3
│   ├── __init__.py
│   ├── base.py                  # BaseGrader, GraderResult
│   ├── registry.py              # Grader management
│   ├── code_based/              # 🔜 Phase 2
│   │   ├── citation_accuracy.py
│   │   ├── source_diversity.py
│   │   └── structure_completeness.py
│   └── model_based/             # 🔜 Phase 3
│       ├── topic_coverage.py
│       ├── quality_assessment.py
│       └── factual_accuracy.py
│
├── tasks/                       # 🔜 Phase 4
│   ├── factual/
│   ├── comparative/
│   └── controversial/
│
├── main.py                      # ✅ CLI interface
├── pyproject.toml               # ✅ Dependencies
└── README.md                    # ✅ This file
```

## 🔮 Next Steps

### Immediate (You are here!)

The core infrastructure (Phase 1) is complete. You can now:

1. **Explore the codebase**: Review the implemented classes in `core/`
2. **Create example tasks**: Use the CLI to generate sample tasks
3. **Plan Phase 2**: Decide which graders to implement first

### Phase 2: Implement Code-Based Graders

Create deterministic graders:
- `CitationAccuracyGrader`: Validate citation format
- `SourceDiversityGrader`: Check source variety
- `StructureCompletenessGrader`: Verify report structure
- `MetadataValidationGrader`: Validate metadata

### Phase 3: Implement Model-Based Graders

Create LLM-powered graders:
- `TopicCoverageGrader`: Check topic coverage
- `QualityAssessmentGrader`: Overall quality evaluation
- `FactualAccuracyGrader`: Fact-checking
- `BiasDetectionGrader`: Detect bias

### Phase 4: Create Task Dataset

Build 50 evaluation tasks:
- 20 factual tasks
- 15 comparative tasks
- 10 controversial tasks
- 5 regression tasks

## 📖 Key Concepts

### Task Categories

1. **Factual**: Straightforward information gathering
   - Example: "What is quantum computing?"

2. **Comparative**: Balanced analysis of alternatives
   - Example: "Compare TensorFlow vs PyTorch"

3. **Controversial**: Multi-perspective research
   - Example: "Analyze AI safety debate"

4. **Regression**: Maintain baseline performance
   - Example: Real user queries from production

### Grader Types

1. **Code-Based** (40% weight)
   - Fast, cheap, objective
   - Citations, structure, metadata
   - No LLM API calls

2. **Model-Based** (50% weight)
   - Flexible, subjective
   - Quality, coverage, accuracy
   - Uses LLM API

3. **Human** (10% weight)
   - Gold standard
   - Calibration reference
   - Manual review

## 📚 References

- **Anthropic Blog**: [Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- **NEOS Agent**: `neos/agents/search_agents/hyper_deep_research/`
- **Implementation Plan**: [EVALUATION_FRAMEWORK_PLAN.md](EVALUATION_FRAMEWORK_PLAN.md)

---

**Version:** 0.1.0 (Phase 1 Complete)
**Last Updated:** 2026-01-11
**Status:** ✅ Core Infrastructure Ready

# NEOS Thinking Engine

**Status:** Implemented foundation and runtime wiring  
**Last updated:** 2026-06-20  
**Related documents:** `docs/HARNESS_WHITEPAPER.md`, `docs/CONFIGURATION.md`

---

## 1. Overview

NEOS Thinking Engine is not a second agent runtime. It is a contract-backed
orchestration layer built on the systems that already exist in NEOS:

- Research Harness contracts, checkers, verdicts, repair plans, and runtime
  gates.
- Standard workflow state and response finalization.
- Direct Deep Research report generation.
- HyperDeepResearch candidate report generation and iterative refinement.
- ROMA recursive task decomposition and verification.
- Mission plans and validation contracts.
- Evidence graph memory.

The implementation goal is simple:

```text
plan / classify
  -> produce a candidate artifact
  -> run a contract-backed harness gate
  -> repair or fail when the gate blocks
  -> finalize only after an allowed verdict
  -> keep enough trace data to explain the decision later
```

The important shift is lifecycle control. A generated research artifact is no
longer assumed to be final just because generation finished. It becomes a
candidate first, and completion is a separate trust decision.

---

## 2. Runtime Invariant

Research-like artifacts should follow these rules:

1. Generated artifacts start as candidates.
2. Candidates become completed only after a selected `HarnessContract` returns
   a finalization-allowed verdict.
3. `gate + pass` can finalize.
4. `gate + needs_repair` should repair and revalidate while repair attempts
   remain; otherwise it blocks finalization.
5. `gate + fail` blocks finalization.
6. Blocked gate outputs must not be treated as successfully completed outputs.
7. The harness run, failed checks, score, artifact reference, and task state
   should be traceable.
8. Long-lived evidence should support replacement without deleting history.

The Research Harness already provides the verdict language:

| Verdict | Meaning |
| --- | --- |
| `pass` | Checks met the contract. Gate-mode artifacts may finalize. |
| `advisory_pass` | Non-blocking mode completed with advisory semantics. |
| `needs_repair` | Repairable failures remain. Gate-mode artifacts should not finalize until repair/revalidation succeeds. |
| `fail` | Non-repairable or exhausted failure. Gate-mode artifacts must not finalize. |
| `skipped` | Harness was disabled or explicitly off. |

Thinking Engine extends this verdict language across more runtime surfaces.

---

## 3. Implementation Map

| Area | Files | Implemented behavior |
| --- | --- | --- |
| Strategy classification | `neos/workflow/thinking_strategy.py`, `neos/workflow/utils/query_classifier.py`, `neos/workflow/state.py` | Adds deterministic problem type, branch policy, effort budget, and `requires_gate` hints to workflow state. |
| Contract compilation | `neos/workflow/harness/contract_compiler.py`, `neos/workflow/harness/contract_builder.py` | Expands checker dependencies, upgrades to gate when strategy requires it, and annotates compiled contracts. |
| Trace shape | `neos/workflow/harness/trace.py`, `neos/workflow/harness/runner.py`, `neos/workflow/processors/research_harness_processor.py` | Defines compact trace events and appends harness run completion events to `thinking_trace`. |
| Task DAG runtime model | `neos/workflow/harness/task_dag.py` | Adds an in-memory DAG model with dependency readiness, done/fail marking, rollback, and state round-trip. |
| Task persistence schema | `db/migrations/033_add_thinking_engine_tables.sql` | Adds `thinking_engine_traces` and `thinking_engine_task_nodes` tables. |
| Mission task state | `neos/workflow/mission/models.py`, `neos/workflow/harness/adapters/mission.py` | Mission tasks can carry artifact refs, attempts, and harness run ids; mission validation contracts map to harness config. |
| Recursive task state | `neos/workflow/recursive/models.py`, `neos/workflow/recursive/orchestrator.py`, `neos/workflow/recursive/verifier.py` | Recursive tasks can carry dependencies/artifact refs/harness run ids; verifier treats gate verdicts as stronger evidence than heuristic/LLM checks. |
| HyperDeep candidate lifecycle | `neos/agents/search_agents/hyper_deep_research/agent.py`, `neos/agents/search_agents/hyper_deep_research/repository/hyper_research_repository.py` | HyperDeep finalization now defaults to `candidate_ready`; `completed` is reserved for explicitly verified paths. |
| HyperDeep task-level gate | `neos/workflow/hyper_deep/executor.py` | HyperDeep leaf output runs through a task-level harness gate when enabled and stores the harness result on the task. |
| HyperDeep refinement checks | `neos/workflow/harness/adapters/hyper_deep.py` | Converts section refinement quality into `HarnessCheckResult` metadata. |
| Direct Deep Research finalization | `neos/api/handlers/deep_research_handlers.py`, `neos/api/services/deep_research_harness_service.py` | Marks reports `validating`, runs harness validation, optionally repairs/revalidates, then marks `completed` or `failed`. |
| Evidence validity | `db/migrations/034_add_bitemporal_evidence_claims.sql`, `neos/services/evidence_graph_service.py` | Adds claim validity intervals and replacement lineage. |
| Configuration | `neos/config/schema.py`, `config/neos.default.yaml`, `docs/CONFIGURATION.md` | Adds conservative Thinking Engine config defaults and HyperDeep task-level harness config. |
| Regression tests | `tests/workflow/*`, `tests/workflow/harness/*`, `tests/api/*`, `tests/db/*`, `tests/config/*`, `tests/unit/agents/*` | Covers strategy, DAG behavior, candidate status, task-level harness, recursive verifier, migrations, config, and finalization gating. |

---

## 4. Strategy Classification

`neos/workflow/thinking_strategy.py` defines a small deterministic strategy
model:

```python
class ProblemType(str, Enum):
    CONVERGENT = "convergent"
    DIVERGENT = "divergent"
    EXPLORATORY = "exploratory"
    STRUCTURAL = "structural"

class BranchPolicy(str, Enum):
    SINGLE_PATH = "single_path"
    BOUNDED_BRANCHING = "bounded_branching"
    PLAN_THEN_EXECUTE = "plan_then_execute"
```

The strategy object stores:

- `problem_type`
- `branch_policy`
- `effort_budget_tokens`
- `max_branches`
- `requires_gate`
- `reason`

`QueryClassifierProcessor` attaches the strategy to both:

- `state["thinking_strategy"]`
- `state["query_classification"]["thinking_strategy"]`

Current rules:

| Input pattern | Strategy |
| --- | --- |
| Architecture/refactor/system design request | `STRUCTURAL`, `PLAN_THEN_EXECUTE`, 1200 token budget, gate when complexity is at least 0.6 |
| `deep_research`, `hyper_deep_research`, `recursive_research` | `EXPLORATORY`, `BOUNDED_BRANCHING`, gate required |
| Comparison or complex/financial analysis | `DIVERGENT`, bounded branching, gate when complexity/freshness warrants it |
| Freshness-required or very high complexity query | `EXPLORATORY`, gate required |
| Default low-complexity query | `CONVERGENT`, `SINGLE_PATH`, no gate required |

This keeps the first decision cheap and reproducible. The model does not ask an
LLM to invent a runtime architecture; it turns the existing classifier output
into operational hints that contracts can consume.

---

## 5. Workflow State Additions

`AgentState` now includes:

```python
thinking_strategy: Optional[Dict[str, Any]]
thinking_trace: Optional[List[Dict[str, Any]]]
task_dag: Optional[Dict[str, Any]]
```

The workflow graph initializes them as:

```python
thinking_strategy=None
thinking_trace=[]
task_dag=None
```

These fields are deliberately generic:

- `thinking_strategy` records the plan-level policy hint.
- `thinking_trace` records compact runtime events.
- `task_dag` can hold serialized task graph state when a workflow uses the DAG
  model.

---

## 6. Harness Contract Compilation

`build_harness_contract()` still constructs the base contract from workflow
state, profile presets, and Mission validation contracts. The new
`compile_harness_contract()` post-processes the contract before execution.

Current compiler behavior:

1. Expands required checker dependencies.
2. Expands optional checker dependencies without duplicating required checks.
3. Upgrades mode to `gate` when `thinking_strategy.requires_gate` is true.
4. Copies strategy metadata such as `problem_type` and `effort_budget_tokens`
   into contract metadata.
5. Requires `source_diversity` when blocked domains are configured.
6. Marks metadata with `compiled_contract: true`.

Checker dependencies:

| Requested check | Added dependencies |
| --- | --- |
| `citation_validity` | `citation_coverage` |
| `factuality` | `citation_validity`, `citation_coverage` |
| `freshness` | `source_count` |

This preserves the main harness advantage: callers can request a high-level
validation goal, while the compiler turns it into an executable checker set.

---

## 7. Trace Events

`neos/workflow/harness/trace.py` provides:

- `TraceEvent`
- `trace_event()`
- `compact_trace_event()`

The compaction helper truncates large strings, caps lists, and recursively
compacts nested dictionaries. The default text budget is aligned with
`thinking_engine.max_trace_text_length`.

Current runtime trace wiring:

1. `HarnessRunner._build_run()` adds a compact run-completed event to
   `HarnessRun.metadata["trace_events"]`.
2. `ResearchHarnessProcessor` appends those events into workflow
   `thinking_trace`.
3. `db/migrations/033_add_thinking_engine_tables.sql` prepares a persistence
   table named `thinking_engine_traces`.

Current trace event shape from harness runs:

```json
{
  "node_id": "research_harness",
  "run_id": "...",
  "event_type": "harness.run.completed",
  "score": 0.92,
  "verdict": "pass",
  "failed_checks": []
}
```

Important implementation boundary: the persistence table exists, and
state-level trace collection is wired for the standard workflow harness path.
Full trace repository writes are intentionally separate from the schema and
remain controlled by rollout work.

---

## 8. Task DAG Runtime Model

`neos/workflow/harness/task_dag.py` defines:

```python
@dataclass
class TaskDAGNode:
    node_id: str
    description: str
    parent_id: str | None = None
    status: str = "pending"
    attempts: int = 0
    depends_on: list[str] = field(default_factory=list)
    artifact_ref: str | None = None
    harness_run_id: str | None = None
    rollback_generation: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
```

`TaskDAG` supports:

- `ready_nodes()`: returns pending nodes whose dependencies are done.
- `mark_done()`: stores artifact and harness run references.
- `mark_failed()`: increments attempts and records error metadata.
- `rollback_subtree()`: resets a node and descendants to pending and clears
  artifact/harness references.
- `to_state()` / `from_state()`: serializes and restores graph state.

The persistence schema adds `thinking_engine_task_nodes` with:

- `task_node_id`
- `parent_task_node_id`
- `run_id`
- `session_id`
- `report_id`
- `user_id`
- `description`
- `status`
- `attempts`
- `depends_on`
- `artifact_ref`
- `harness_run_id`
- `rollback_generation`
- `metadata`

As with traces, the schema is ready while persistence rollout remains
feature-gated.

---

## 9. Mission Integration

Mission models now carry the fields needed to join task execution with harness
validation:

```python
artifact_ref: Optional[str] = None
attempts: int = 0
harness_run_id: Optional[str] = None
```

Mission `ValidationContract` is mapped to harness config by
`neos/workflow/harness/adapters/mission.py`.

Examples:

| Mission contract field | Harness config effect |
| --- | --- |
| `required_sources` | `min_sources` |
| `min_quality_score` | `min_score` |
| `allowed_repair_attempts` | `max_repair_attempts` |
| `freshness_requirement` | `freshness_required`, optional freshness window |
| `citation_requirement` | `citation_validity`, `citation_coverage` |
| `factuality_checks` | `factuality` |
| `coverage_checks` | `topic_coverage` |
| `safety_checks` | `bias_perspective` |
| `failure_policy=return_partial` | `failure_policy=partial` |

This means Mission planning can describe the validation contract in Mission
language, while the runtime harness receives executable checks and thresholds.

---

## 10. Recursive / ROMA Integration

Recursive task nodes now include:

- `depends_on`
- `artifact_ref`
- `attempts`
- `harness_run_id`

`RecursiveOrchestrator` records artifact references after execution:

```text
recursive-task://<task_id>/result
recursive-task://<task_id>/aggregated
```

`RecursiveVerifier` now treats harness metadata as stronger evidence than its
LLM or length-based verifier:

```python
harness = original_task.metadata.get("harness", {})
if harness.get("mode") == "gate":
    if verdict == "pass":
        satisfied = True
    if verdict in {"fail", "needs_repair"}:
        satisfied = False
```

This lets recursive execution consume a task-level harness result when one is
attached to the node.

Implementation boundary: Recursive verification currently respects gate
metadata when present. A dedicated recursive harness runner path can be layered
on top of this without changing the verifier contract.

---

## 11. HyperDeep Candidate Lifecycle

HyperDeepResearch previously marked internally generated reports as completed at
the end of generation. That made it too easy to treat an unverified artifact as
final.

`HyperDeepResearchAgent._finalize_report()` now defaults to:

```python
status = "candidate_ready"
```

Only an explicit verified call uses:

```python
status = "completed"
timestamp_field = "completed_at"
quality_score = 0.95
```

The repository status documentation now accepts:

- `pending`
- `in_progress`
- `candidate_ready`
- `validating`
- `completed`
- `failed`

This aligns HyperDeep with the Thinking Engine invariant:

```text
generation finished != validation passed
```

---

## 12. HyperDeep Task-Level Harness

`HyperDeepExecutor` wraps HyperDeepResearch for ROMA leaf tasks. It now accepts
an optional harness runner:

```python
HyperDeepExecutor(harness_runner=None)
```

When `HYPER_DEEP_TASK_LEVEL_HARNESS_ENABLED` is true, it:

1. Runs HyperDeepResearch for the leaf task.
2. Extracts the report content from the returned search result.
3. Extracts sources from result metadata.
4. Builds a `direct_deep_research` gate contract.
5. Runs `HarnessRunner.arun()`.
6. Stores harness metadata on the `RecursiveTaskNode`.
7. Fails the task when a gate verdict is `fail` or `needs_repair`.

Stored task metadata:

```json
{
  "harness": {
    "mode": "gate",
    "verdict": "pass",
    "score": 0.91,
    "failed_checks": []
  }
}
```

This is the most direct example of the Thinking Engine design: a leaf agent can
produce a candidate artifact, but the task is not considered successful until
the harness gate allows it.

---

## 13. HyperDeep Refinement Metrics as Checks

`neos/workflow/harness/adapters/hyper_deep.py` converts HyperDeep metadata into
harness-shaped checks.

Current check:

| Check | Threshold | Behavior |
| --- | --- | --- |
| `hyperdeep_section_quality` | `average_section_quality >= 0.80` | Passes good refinement metrics; returns a repairable warning when section quality is below threshold. |

The agent stores these in:

```python
self.research_metadata["harness_candidate_checks"]
```

This keeps HyperDeep's internal refinement signal compatible with the same
`HarnessCheckResult` shape used by runtime gates and offline eval bridges.

---

## 14. Direct Deep Research Finalization

Direct Deep Research now has an explicit validation phase.

Flow:

```text
generate report sections
  -> assemble report metadata
  -> update report status to validating
  -> DeepResearchHarnessService.validate_report()
  -> persist harness run
  -> if needs_repair and attempts remain: repair and revalidate
  -> if blocked: mark failed and emit HARNESS_FAILED
  -> otherwise: mark completed and attach harness metadata
```

`DeepResearchHarnessService` is responsible for:

1. Fetching report sections.
2. Fetching collected source rows.
3. Combining sections into markdown.
4. Extracting normalized sources.
5. Building a `direct_deep_research` gate contract.
6. Running the harness.
7. Returning the run, contract, report, and sources.

The handler stores final message metadata like:

```json
{
  "research_status": "completed",
  "quality_score": 0.91,
  "harness": {
    "mode": "gate",
    "verdict": "pass",
    "score": 0.91,
    "failed_checks": [],
    "repair_attempts": 0
  }
}
```

If the gate remains blocked, the report is marked `failed` instead of
`completed`.

---

## 15. Evidence Graph Validity

`db/migrations/034_add_bitemporal_evidence_claims.sql` adds:

- `valid_from`
- `valid_to`
- `replaced_by_claim_id`
- `invalidation_reason`

It also adds indexes for current and ranged claim lookup.

`EvidenceGraphService` now has:

```python
async def supersede_claim(old_claim_id, new_claim_id, reason) -> None
```

This marks an old claim as no longer current without deleting it.

```python
async def find_current_relevant_evidence(...)
```

This searches only claims where:

```sql
valid_to IS NULL
```

This supports long-running memory where previous conclusions can be superseded
while preserving audit history.

---

## 16. Configuration

Default config:

```yaml
thinking_engine:
  enabled: true
  persist_traces: false
  persist_task_dag: false
  task_level_harness: true
  max_trace_text_length: 240

hyper_deep_agent:
  task_level_harness_enabled: true
```

Config meanings:

| Setting | Default | Meaning |
| --- | --- | --- |
| `thinking_engine.enabled` | `true` | Enables the contract orchestration configuration surface. Current behavior is mostly additive because core gates are still wired through existing harness paths. |
| `thinking_engine.persist_traces` | `false` | Intended rollout flag for storing compact trace events in `thinking_engine_traces`. |
| `thinking_engine.persist_task_dag` | `false` | Intended rollout flag for storing task nodes in `thinking_engine_task_nodes`. |
| `thinking_engine.task_level_harness` | `true` | General Thinking Engine setting for task-level gates. |
| `thinking_engine.max_trace_text_length` | `240` | Default trace text compaction length. |
| `hyper_deep_agent.task_level_harness_enabled` | `true` | Currently wired HyperDeep executor switch for leaf task harness validation. |

Implementation note: the schema and YAML config define the Thinking Engine
settings. Runtime paths that already existed continue to use their established
harness settings. HyperDeep leaf gating currently uses the
`hyper_deep_agent.task_level_harness_enabled` setting.

---

## 17. Persistence Tables

### `thinking_engine_traces`

Stores compact execution trace events.

Key columns:

- `trace_id`
- `run_id`
- `session_id`
- `report_id`
- `user_id`
- `event_type`
- `node_id`
- `sequence`
- `data`
- `created_at`

Indexes:

- `idx_thinking_engine_traces_run`
- `idx_thinking_engine_traces_session`
- `idx_thinking_engine_traces_event_type`

### `thinking_engine_task_nodes`

Stores persistent DAG node state.

Key columns:

- `task_node_id`
- `parent_task_node_id`
- `run_id`
- `session_id`
- `report_id`
- `user_id`
- `description`
- `status`
- `attempts`
- `depends_on`
- `artifact_ref`
- `harness_run_id`
- `rollback_generation`
- `metadata`
- `created_at`
- `updated_at`

Indexes:

- `idx_thinking_engine_task_nodes_run`
- `idx_thinking_engine_task_nodes_session`
- `idx_thinking_engine_task_nodes_status`
- `idx_thinking_engine_task_nodes_parent`

---

## 18. Harness Advantage in the Thinking Engine

The most important design choice is that Thinking Engine does not invent a new
validation vocabulary. It reuses the harness vocabulary everywhere:

- `HarnessContract`
- `HarnessCheckResult`
- `HarnessRun`
- `HarnessMode`
- `HarnessVerdict`
- repairability
- failed check names
- source/citation/factuality/freshness semantics

This gives several benefits:

1. Runtime gates and offline evals can share result shapes.
2. Existing deterministic checkers remain the first line of defense.
3. Model-based checks stay optional and feature-flagged.
4. Direct Deep Research, HyperDeep, Mission, and Recursive workflows can all
   talk in the same verdict language.
5. Repair loops can target failed check names instead of vague quality scores.
6. Finalization rules become auditable instead of implicit.

The Thinking Engine is therefore mostly a lifecycle and integration layer. The
intelligence is distributed across existing components; the harness supplies
the common decision boundary.

---

## 19. Testing Coverage

Focused coverage added or updated:

| Test file | Coverage |
| --- | --- |
| `tests/workflow/test_thinking_strategy.py` | Strategy classification rules. |
| `tests/workflow/harness/test_contract_compiler.py` | Contract dependency expansion and strategy metadata. |
| `tests/workflow/harness/test_trace.py` | Trace serialization and compaction. |
| `tests/db/test_thinking_engine_migration_sql.py` | Trace/task DAG migration shape. |
| `tests/workflow/harness/test_task_dag.py` | Ready nodes, rollback, failure attempts, state round-trip. |
| `tests/unit/agents/hyper_deep_research/test_candidate_status.py` | HyperDeep finalization defaults to `candidate_ready`. |
| `tests/workflow/hyper_deep/test_executor.py` | HyperDeep executor records task-level harness run metadata. |
| `tests/workflow/recursive/test_verifier.py` | Recursive verifier accepts/rejects gate verdict metadata. |
| `tests/workflow/harness/test_hyper_deep_adapter.py` | HyperDeep refinement metrics convert to harness checks. |
| `tests/db/test_bitemporal_evidence_migration_sql.py` | Evidence validity migration shape. |
| `tests/config/test_config_schema.py` | Thinking Engine config defaults. |
| `tests/workflow/test_thinking_engine_finalization.py` | Gate pass/fail finalization behavior. |
| `tests/api/test_deep_research_handler_harness_repair_flow.py` | Direct Deep Research status ordering and repair provenance. |
| `tests/api/test_deep_research_harness_service.py` | Service-level harness validation behavior. |
| `tests/workflow/test_harness_graph_repair.py` | Harness repair graph keeps thinking trace state. |

Recent focused verification command:

```bash
pytest tests/workflow/harness \
  tests/workflow/test_thinking_strategy.py \
  tests/workflow/test_thinking_engine_finalization.py \
  tests/workflow/recursive \
  tests/workflow/hyper_deep \
  tests/api/test_deep_research_harness_service.py \
  tests/api/test_deep_research_handler_harness_repair_flow.py \
  tests/db/test_thinking_engine_migration_sql.py \
  tests/db/test_bitemporal_evidence_migration_sql.py \
  tests/config/test_config_schema.py \
  tests/config/test_config_files.py -q
```

Expected result from the current implementation:

```text
123 passed
```

The local sandbox may log database initialization warnings such as
`Operation not permitted` during pytest setup/teardown. Those warnings are
environmental noise in the current test harness and did not fail the focused
suite.

---

## 20. Current Boundaries and Next Steps

Implemented now:

- Strategy classification and state propagation.
- Contract compilation and checker dependency expansion.
- Standard workflow harness trace append.
- Task DAG in-memory model.
- Trace/task DAG database schemas.
- Mission task fields and Mission contract-to-harness mapping.
- Recursive verifier consumption of harness verdicts.
- HyperDeep candidate lifecycle.
- HyperDeep task-level harness gate.
- HyperDeep refinement metric adapter.
- Direct Deep Research `validating` -> harness -> repair/revalidate ->
  `completed`/`failed` lifecycle.
- Evidence claim validity intervals and supersede/current lookup helpers.
- Config schema/defaults and regression tests.

Still intentionally bounded:

- `thinking_engine.persist_traces` and `thinking_engine.persist_task_dag`
  default to `false`.
- Trace and DAG persistence schemas exist, but a full repository/write path
  should be rolled out separately.
- Recursive verifier can consume gate metadata, but a dedicated recursive
  harness runner can still be added as a next layer.
- Mission has validation contract mapping and task references, but full Mission
  execution finalization can be tightened further around harness summaries.
- `thinking_engine.enabled` is currently a configuration surface; existing
  runtime behavior remains wired through the established harness and HyperDeep
  feature flags.

Recommended rollout order:

1. Keep trace and DAG persistence disabled in default development config.
2. Continue using task-level harness for HyperDeep leaf tasks.
3. Enable trace persistence first in internal staging with summary-only evidence
   storage.
4. Add repository writes for trace events and inspect payload size/privacy.
5. Enable task DAG persistence after task ids, artifact refs, and harness run
   refs are stable in staging.
6. Extend recursive and Mission execution paths so task-level harness runs are
   produced directly, not only consumed when metadata is attached.

---

## 21. Mental Model

The Thinking Engine should be read as a contract lifecycle:

```text
Question
  -> ThinkingStrategy
  -> candidate artifact
  -> HarnessContract
  -> HarnessRun
  -> verdict
  -> repair / fail / finalize
  -> trace + task metadata + evidence validity
```

The key product behavior is not that NEOS "thinks longer." The key behavior is
that NEOS can explain why a research artifact was allowed to become final.


# NEOS Research Harness Implementation

**Status:** Runtime harness, bounded repair, Direct Deep Research gate integration, persistence, and rollout controls implemented
**Last updated:** 2026-06-12
**Related documents:** `docs/HARNESS_WHITEPAPER.md`, `docs/HARNESS_STAGING_ROLLOUT.md`, `docs/HARNESS_EVAL_CALIBRATION.md`, `docs/CONFIGURATION.md`

---

## 1. Implementation Scope

The research harness is implemented as a runtime decision layer for research
artifacts. It converts validation checks into a contract-driven verdict and
uses that verdict to decide whether NEOS may finalize, cache, persist, or repair
an artifact.

Implemented runtime verdicts:

- `pass`
- `advisory_pass`
- `needs_repair`
- `fail`
- `skipped`

Implemented runtime surfaces:

- standard LangGraph workflow
- Direct Deep Research API completion path
- Mission validation summaries
- custom workflow builder processor execution
- offline `neos_evals` grader bridge
- optional persistence tables and repository
- OpenResponses-compatible harness progress events

The harness is not only metadata. In `gate` mode, `fail` and unresolved
`needs_repair` verdicts block normal completion.

---

## 2. Core Package Layout

The main runtime package lives under `neos/workflow/harness/`.

| File | Responsibility |
| --- | --- |
| `models.py` | Enums and dataclasses for contracts, check results, runs, and repair plans |
| `policy.py` | Selects mode, risk level, score threshold, repair budget, and harness profiles |
| `contract_builder.py` | Builds `HarnessContract` from workflow state, metadata, Mission contracts, and profiles |
| `runner.py` | Runs selected checkers, computes weighted score, and determines verdict |
| `repair.py` | Maps failed repairable checks to bounded repair actions |
| `events.py` | Defines shared harness event names and payload wrapper |
| `cache_policy.py` | Decides whether a result can be cached after harness validation |
| `privacy.py` | Applies evidence storage policy before persistence |
| `adapters/workflow_state.py` | Extracts final response text, sources, and operational context from workflow state |
| `adapters/deep_research_report.py` | Assembles Direct Deep Research report text and sources |
| `adapters/mission.py` | Maps Mission validation contracts into harness config |
| `adapters/neos_evals.py` | Converts offline grader results into harness check results |

Checker implementations live under `neos/workflow/harness/checkers/`.

| Checker | File | Notes |
| --- | --- | --- |
| source count, source diversity | `sources.py` | Deterministic source sufficiency and domain diversity |
| citation validity, citation coverage | `citations.py` | Numeric marker validation and sentence-level coverage |
| freshness | `freshness.py` | Requires dated sources when freshness is required |
| metadata integrity | `metadata.py` | Empty report and workflow error checks |
| topic coverage | `model_based.py` | Deterministic coverage string check |
| factuality | `model_based.py` | Feature-flagged async model judge |
| bias/perspective | `model_based.py` | Feature-flagged async model judge |
| performance budget | `performance.py` | Deterministic operational budget check |
| model judge | `model_judge.py` | LLM judge protocol, prompt builders, JSON parsing |

---

## 3. Policy and Contract Construction

Policy selection is implemented in `decide_harness_policy()`.

Decision order:

1. Respect global disable with `research_harness.enabled: false`.
2. Honor explicit request mode when allowed.
3. Apply a known `harness_profile`.
4. Gate research intents: `deep_research` and `hyper_deep_research`.
5. Gate high-risk, freshness-required, or high-complexity requests.
6. Fall back to configured default mode.
7. Use advisory mode for ordinary low-risk work.

Research-intent repair budget now uses
`research_harness.hyper_deep_repair_attempts`, so both `deep_research` and
`hyper_deep_research` receive the deeper research repair budget. Standard
workflow repair defaults remain controlled by
`research_harness.max_repair_attempts`.

Contract construction is implemented in `build_harness_contract()`.

Inputs:

- `query_intent` or `intent`
- `complexity_score` or `query_classification`
- `request_metadata`
- `harness_metadata`
- generic `metadata`
- `validation_contract`
- optional `harness_config`
- optional `harness_profile`

Profile presets are defined in `policy.py`. Current profiles include:

- `research_default`
- `freshness_sensitive`
- `mission_strict`
- `direct_deep_research`
- `agent_advisory`
- `agent_source_audit`
- `agent_factuality_audit`
- `agent_perspective_audit`

Direct Deep Research contract state defaults to the `direct_deep_research`
profile while preserving explicit `harness_mode: gate`.

---

## 4. Runner and Verdict Logic

`HarnessRunner` supports both synchronous and asynchronous execution:

- `run()` is used by deterministic tests and synchronous callers.
- `arun()` executes async checkers when available and falls back to sync
  checkers otherwise.

Default deterministic checker order:

1. `source_count`
2. `source_diversity`
3. `citation_validity`
4. `citation_coverage`
5. `freshness`
6. `metadata_integrity`
7. `performance_budget`

Optional/profile-selected checkers are appended when selected:

- `topic_coverage`
- `factuality`
- `bias_perspective`

Required missing checks materialize as failed `HarnessCheckResult` entries.
Optional missing checks do not fail the run. This prevents strict contracts from
silently passing when they request a checker the runtime cannot execute.

Verdict rules:

- `gate + required check failure + repairable + attempts remain` -> `needs_repair`
- `gate + required check failure + no attempts remain` -> `fail`
- critical repairable failure with attempts remaining -> `needs_repair`
- critical failure without repair path -> `fail`
- gate score meeting threshold -> `pass`
- advisory score meeting threshold -> `advisory_pass`
- disabled harness -> `skipped`

Skipped checks are excluded from weighted scoring so optional disabled model
checks do not dilute deterministic results.

---

## 5. Standard Workflow Integration

The standard workflow runs the harness after response generation so it validates
the artifact users would actually receive.

Current successful path:

```text
RESULT_INTEGRATOR
  -> FACT_CHECK
  -> QUALITY_VALIDATOR
  -> SELF_REFLECTION
  -> RESPONSE_GENERATOR
  -> RESEARCH_HARNESS
  -> END
```

Repairable gate path:

```text
RESPONSE_GENERATOR
  -> RESEARCH_HARNESS
  -> RESEARCH_HARNESS_REPAIR
  -> RESEARCH_HARNESS
  -> END
```

Key implementation files:

- `neos/workflow/processors/research_harness_processor.py`
- `neos/workflow/processors/research_harness_repair_processor.py`
- `neos/workflow/graph.py`
- `neos/workflow/processors/response_generator.py`

`ResearchHarnessProcessor`:

- builds the contract
- extracts report text and sources
- runs the harness
- emits progress events when an event handler exists
- optionally persists the run
- writes `harness_*` state fields
- adds compact harness metadata to `response_metadata`

`ResearchHarnessRepairProcessor`:

- reconstructs the contract from state
- reads failed check metadata
- creates a repair plan with `HarnessRepairPlanner`
- increments `harness_repair_attempts` only when a plan exists
- adds required agents for search-style repair actions
- emits repair progress events

`workflow/graph.py` enforces gate results:

- `gate + fail` blocks normal completion
- `gate + needs_repair` routes to repair while attempts remain
- blocked gate results return `success=false`
- blocked output is retained as `blocked_response`
- blocked gate sessions are recorded as failed
- failed or unresolved gate results are not cached

---

## 6. Direct Deep Research Integration

Direct Deep Research uses a dedicated service and handler integration.

Key implementation files:

- `neos/api/services/deep_research_harness_service.py`
- `neos/api/services/deep_research_repair_service.py`
- `neos/api/services/deep_research_repair_executor.py`
- `neos/api/services/deep_research_repair_sources.py`
- `neos/api/services/deep_research_section_regenerator.py`
- `neos/api/repositories/deep_research_repair_repository.py`
- `neos/api/handlers/deep_research_handlers.py`

`DeepResearchHarnessService`:

- fetches report sections
- fetches collection rows
- combines final report sections into report text
- extracts normalized sources
- builds a Direct Deep Research harness contract state
- runs `HarnessRunner.arun()`
- returns a validation envelope containing run, contract, report, and sources

Direct Deep Research completion behavior:

1. Run the agent and assemble the final report.
2. Emit `harness_started`.
3. Validate the report through `DeepResearchHarnessService`.
4. Persist the run when `research_harness.persistence.persist_runs: true`.
5. If verdict is `needs_repair`, emit repair events and call
   `DeepResearchRepairService`.
6. Refresh report totals after repair.
7. Revalidate with incremented repair attempt count.
8. Complete only when the gate is no longer blocked.
9. Mark the report failed and emit `harness_failed` when the gate remains
   blocked.

Direct repair mutation is disabled by default with:

```yaml
research_harness:
  direct_repair:
    enabled: false
```

When disabled, repair actions are explicitly skipped instead of mutating live
report sections or source collections.

Supported Direct repair actions:

- `request_more_sources`
- `search_independent_domains`
- `date_constrained_freshness_search`
- `rebuild_citation_map`
- `regenerate_cited_sections`
- `regenerate_unsupported_claims`
- `add_perspective_balancing_sources`

Search-style repair uses a pluggable search executor. The default Tavily-backed
searcher is bounded by:

```yaml
research_harness:
  direct_repair:
    search_timeout_seconds: 25
    search_retries: 1
```

Regeneration repair uses `DeepResearchSectionRegenerator`, which rewrites
targeted sections using provided sources and validates citation marker shape
before saving.

---

## 7. Mission, Custom Workflow, and Offline Eval Integration

Mission integration:

- `neos/workflow/harness/adapters/mission.py` maps Mission validation contract
  fields into harness config.
- `neos/workflow/mission/validators.py` includes harness verdict, mode, score,
  and failed checks in validation summaries when harness state exists.

Mapped Mission requirements include:

- required sources
- minimum quality score
- freshness
- citation requirements
- factuality
- topic coverage
- allowed repair attempts

Custom workflow integration:

- `neos/workflow/builder/executors.py` supports
  `processor_type="research_harness"`.
- `neos/workflow/builder/workflow_executor.py` initializes harness state and
  blocks gate failures.

Offline eval bridge:

- `neos/workflow/harness/adapters/neos_evals.py` converts offline grader
  results into `HarnessCheckResult`.
- `scripts/harness_calibration.py` compares runtime harness verdicts with
  offline grader outcomes.
- Calibration notes are tracked in `docs/HARNESS_EVAL_CALIBRATION.md`.

---

## 8. Events and Client Metadata

Shared event helpers live in `neos/workflow/harness/events.py`.

Standard workflow events are emitted as workflow progress messages containing
serialized harness payloads. The chat stream adapter parses these into
OpenResponses-compatible `neos:harness` events.

Key files:

- `neos/workflow/harness/events.py`
- `neos/api/adapters/stream_adapter.py`
- `neos/api/models/open_responses.py`
- `web/hooks/use-chat-stream.ts`
- `web/components/harness-status.tsx`

Supported client event names:

- `harness_started`
- `harness_check_started`
- `harness_check_completed`
- `harness_repair_started`
- `harness_repair_completed`
- `harness_completed`
- `harness_failed`

Response metadata includes a compact harness summary:

```json
{
  "harness": {
    "enabled": true,
    "mode": "gate",
    "verdict": "pass",
    "score": 0.87,
    "failed_checks": [],
    "repair_attempts": 0,
    "threshold": 0.82,
    "risk_level": "medium"
  }
}
```

The frontend renders available harness metadata through
`web/components/harness-status.tsx`.

---

## 9. Persistence and Privacy

Dedicated persistence is implemented behind a feature flag.

Migration:

- `db/migrations/032_add_research_harness_tables.sql`

Tables:

- `research_harness_runs`
- `research_harness_check_results`

Repository:

- `neos/database/repositories/harness_repository.py`

Enable persistence with:

```yaml
research_harness:
  persistence:
    persist_runs: true
```

Evidence storage policy:

```yaml
research_harness:
  persistence:
    evidence_storage_policy: summary_only
```

Supported policies:

- `summary_only`: clears raw evidence and stores failed item counts only
- `redacted`: hashes sensitive text fields and reduces `url` fields to domains
- `full`: stores raw evidence; use only in controlled eval environments

`HarnessRepository.save_run()` applies `sanitize_check_result()` before check
rows are written.

---

## 10. Configuration

Harness settings are defined in the typed YAML config schema:

- `neos/config/schema.py`
- `config/neos.default.yaml`
- `config/neos.staging.yaml`
- `config/neos.production.yaml`
- `config/neos.example.yaml`

Default YAML shape:

```yaml
research_harness:
  enabled: true
  allow_off: false
  default_mode: auto
  gate_threshold: 0.82
  advisory_threshold: 0.70
  high_risk_threshold: 0.90
  max_repair_attempts: 1
  hyper_deep_repair_attempts: 2
  model_checks:
    enabled: true
    timeout_seconds: 20
    max_claims: 8
    provider: ""
    model: ""
  persistence:
    persist_runs: false
    store_full_check_details: false
    evidence_storage_policy: summary_only
    cache_policy: passed_only
  direct_repair:
    enabled: false
    search_timeout_seconds: 25
    search_retries: 1
```

Legacy uppercase access is still translated by `neos.config.settings` for
compatibility. New non-secret runtime changes should be made through YAML
overlays rather than `.env.template`.

---

## 11. Verification

Focused verification command:

```bash
pytest tests/workflow/harness \
  tests/workflow/processors/test_research_harness_processor.py \
  tests/workflow/processors/test_research_harness_repair_processor.py \
  tests/workflow/test_harness_graph_routing.py \
  tests/workflow/test_harness_graph_repair.py \
  tests/workflow/test_harness_response_metadata.py \
  tests/workflow/mission \
  tests/api/test_deep_research_harness_service.py \
  tests/api/test_deep_research_harness_repair.py \
  tests/api/test_deep_research_repair_sources.py \
  tests/api/test_deep_research_repair_repository.py \
  tests/api/test_deep_research_section_regenerator.py \
  tests/api/test_deep_research_repair_executor.py \
  tests/api/test_deep_research_handler_harness_repair_flow.py \
  tests/workflow/builder/test_node_executor_harness.py \
  tests/workflow/builder/test_workflow_executor_harness_state.py \
  tests/workflow/builder/test_workflow_executor_harness_gate.py \
  tests/database/repositories/test_harness_repository.py \
  tests/db/test_research_harness_migration_sql.py -q
```

Recent focused alignment verification:

```bash
pytest tests/workflow/harness/test_policy.py \
  tests/workflow/harness/test_deep_research_adapter.py \
  tests/workflow/harness/test_contract_builder.py \
  tests/config/test_env_template_policy.py \
  tests/test_harness_settings_defaults.py -q
```

Observed result:

```text
25 passed
```

Compile check:

```bash
python -m compileall neos/workflow/harness/policy.py \
  neos/workflow/harness/adapters/deep_research_report.py
```

Observed result:

```text
completed with exit code 0
```

---

## 12. Remaining Work

Remaining work is operational rather than foundational:

- Run Direct Deep Research repair mutation in staging and inspect real provider
  behavior, retries, latency, and report mutation provenance.
- Calibrate model-based factuality and bias/perspective checks against offline
  eval fixtures.
- Improve detailed client UX for harness and repair progress.
- Keep `full` evidence persistence disabled outside approved eval
  environments.
- Record calibration runs and threshold decisions in
  `docs/HARNESS_EVAL_CALIBRATION.md`.

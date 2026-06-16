# Harness Staging Rollout

## YAML Configuration

Recommended staging defaults in `config/neos.staging.yaml` or a deployment-specific
YAML overlay:

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
  persistence:
    persist_runs: false
    evidence_storage_policy: summary_only
    cache_policy: passed_only
  direct_repair:
    enabled: false
    search_timeout_seconds: 25
    search_retries: 1
```

## Migration Order

1. Apply `db/migrations/032_add_research_harness_tables.sql`.
2. Deploy code with `research_harness.persistence.persist_runs: false`.
3. Run smoke tests for standard workflow gate mode and Direct Deep Research gate mode.
4. Enable `research_harness.persistence.persist_runs: true` in internal staging.
5. Inspect saved rows with `research_harness.persistence.evidence_storage_policy: summary_only`.
6. Enable `research_harness.direct_repair.enabled: true` only after repair events and report mutations are reviewed.

## Smoke Tests

```bash
pytest tests/workflow/harness -q
```

```bash
pytest \
  tests/workflow/processors/test_research_harness_processor.py \
  tests/workflow/processors/test_research_harness_repair_processor.py \
  tests/workflow/test_harness_graph_routing.py \
  tests/workflow/test_harness_graph_repair.py \
  tests/workflow/test_harness_response_metadata.py -q
```

```bash
pytest \
  tests/api/test_deep_research_harness_service.py \
  tests/api/test_deep_research_harness_repair.py \
  tests/api/test_deep_research_repair_sources.py \
  tests/api/test_deep_research_repair_repository.py \
  tests/api/test_deep_research_section_regenerator.py \
  tests/api/test_deep_research_repair_executor.py \
  tests/api/test_deep_research_handler_harness_repair_flow.py -q
```

## Rollback Controls

- Disable Direct repair mutations with `research_harness.direct_repair.enabled: false`.
- Disable all harness routing with `research_harness.enabled: false`.
- Disable persistence with `research_harness.persistence.persist_runs: false`.
- Keep gate thresholds unchanged during rollback unless calibration data specifically justifies a threshold change.

## Evidence Policy Review

1. Start with `summary_only`; store compact check summaries without raw evidence text.
2. Review redaction behavior in staging with `redacted`; verify sensitive text is hashed and URL domains are preserved.
3. Use `full` only in controlled eval environments with approved access controls.

## Dashboard Queries

Verdict distribution:

```sql
SELECT mode, verdict, COUNT(*)
FROM research_harness_runs
GROUP BY mode, verdict
ORDER BY mode, verdict;
```

Failed checks:

```sql
SELECT check_name, COUNT(*)
FROM research_harness_check_results
WHERE passed = false
GROUP BY check_name
ORDER BY COUNT(*) DESC;
```

Repair success by attempt:

```sql
SELECT repair_attempts, verdict, COUNT(*)
FROM research_harness_runs
GROUP BY repair_attempts, verdict
ORDER BY repair_attempts, verdict;
```

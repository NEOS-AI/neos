# NEOS Configuration Guide

This document describes the backend configuration system introduced by the config refactor checkpoint. It covers the currently implemented Python backend path: typed YAML config files, secret env overrides, legacy env compatibility, and the `settings.X` compatibility singleton.

## Implementation Status

Implemented in this checkpoint:

- `docs/CONFIG_INVENTORY.md` inventories current `settings.py` fields and `.env.template` keys.
- `neos/config/schema.py` defines the typed `AppConfig` Pydantic schema.
- `neos/config/loader.py` loads layered YAML, dotenv secrets, process env secrets, and Release 1 legacy env overrides.
- `neos/config/settings.py` keeps the existing `settings.X` access contract while backing it with `AppConfig`.
- `neos/main.py` and `neos/workflow/celery_app.py` bootstrap through `get_settings()`.
- `config/neos.default.yaml`, `config/neos.development.yaml`, `config/neos.staging.yaml`, `config/neos.production.yaml`, and `config/neos.example.yaml` provide backend YAML profiles.
- `config/neos.local.yaml` is ignored by git for local non-secret overrides.
- `.env.template` is limited to secrets, credential-bearing URLs, Compose-only infrastructure secrets, and bootstrap controls.
- Docker Compose application services mount `./config:/app/config:ro` and set `NEOS_ENV`/`NEOS_CONFIG_PATH`.
- `api_gateway/config.toml` no longer ships usable JWT/database secret defaults.
- `web/lib/server-config.ts` centralizes web server env access for backend URL and web secrets.

Still pending from the full refactor plan:

- Full-suite backend, gateway, web, and Compose verification in CI-like environments.
- Optional Rust gateway YAML parser support, if the gateway is later unified with backend YAML config.

## Source Policy

Use `.env`, `NEOS_SECRETS_PATH`, or real process env for secrets and credential-bearing URLs:

- Database, Redis, and Celery URLs.
- JWT secret.
- Provider API keys.
- OAuth secrets.
- Storage access keys.
- Channel adapter tokens.

Use YAML for non-secret runtime settings:

- Feature flags.
- Model names.
- Timeouts, thresholds, limits, and token budgets.
- CORS origins.
- Storage provider and non-secret endpoints.
- Source metadata such as SEC EDGAR user-agent and OpenAlex email.
- Observability and telemetry toggles.

Use process env only for bootstrap controls:

- `NEOS_ENV`
- `NEOS_CONFIG_PATH`
- `NEOS_SECRETS_PATH`
- `NEOS_MODEL_CONFIG_PATH`

## Loading Order

The backend loader applies config in this order:

1. Parse root `.env` as bootstrap dotenv without mutating `os.environ`.
2. Resolve bootstrap controls from dotenv plus real process env, with process env winning.
3. Load `config/neos.default.yaml`.
4. Load `config/neos.{NEOS_ENV}.yaml`, defaulting to `development`.
5. Load `NEOS_CONFIG_PATH`, if set.
6. Apply known legacy non-secret env overrides with warnings.
7. Apply secrets from `NEOS_SECRETS_PATH`, or root `.env` when no secrets path is set.
8. Apply real process env secrets, with process env winning over dotenv.
9. Validate the result as `AppConfig`.

Unknown non-secret env values are not used for config construction. Known legacy non-secret env keys still work during the Release 1 compatibility window but emit warnings and should be moved to YAML.

## Local Development

Create a local YAML overlay:

```bash
cp config/neos.example.yaml config/neos.local.yaml
```

Set bootstrap controls and secrets in `.env`:

```dotenv
NEOS_ENV=development
NEOS_CONFIG_PATH=config/neos.local.yaml
JWT_SECRET_KEY=replace-with-local-secret
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost/neos
REDIS_URL=redis://localhost:6379
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

Put non-secret runtime changes in `config/neos.local.yaml`:

```yaml
llm:
  provider: anthropic
  model: claude-sonnet-5

research_harness:
  enabled: true
  default_mode: advisory

api:
  cors:
    allowed_origins:
      - http://localhost:3000
```

### Thinking Engine

`thinking_engine.enabled` controls the Claude-like contract orchestration layer.
The default is enabled because it only strengthens existing harness behavior.

`thinking_engine.persist_traces` stores compact execution trace events in
`thinking_engine_traces`. The default is `false`; enable it first in internal
staging because trace payloads can contain operational evidence.

`thinking_engine.persist_task_dag` stores task DAG nodes in
`thinking_engine_task_nodes`. The default is `false`; the in-memory state path
remains active even when persistence is disabled.

`thinking_engine.task_level_harness` enables harness validation for recursive
and HyperDeep leaf artifacts. The default is `true`.

`thinking_engine.max_trace_text_length` controls text compaction in trace
payloads. The default is `240`.

### Model Routing

`model_routing` maps a provider and a workload role to a concrete model. It only
governs **automatic** workloads — a model the user picked is never overwritten.

```yaml
model_routing:
  anthropic:
    everyday: claude-sonnet-5
    powerful: claude-opus-5
  openai:
    everyday: gpt-5.6-terra
    powerful: gpt-5.6-sol
```

Resolution follows a strict precedence, and the winner is reported as
`ModelResolution.source`:

1. `user` — the model named in the current request
2. `conversation` — the model already stored on an existing conversation
3. `feature_override` — a deployment/feature setting (below)
4. `role_default` — the `model_routing` entry for that provider and role

The resolver itself never falls back across providers. An unknown provider or
role, or a blank mapping entry, raises `ValueError` rather than guessing.

Role assignments for automatic workloads:

| Workload | Role |
|---|---|
| New chat default, conversation titles, templates | `everyday` |
| Any `create_llm()` call that omits `model` (`llm.model`) | `everyday` |
| Routine coding executor (`coding_model.model`) | `everyday` |
| Deep-analysis scout and judge | `everyday` |
| Knowledge-graph extraction (`knowledge_graph.extraction.model`) | `everyday` |
| Tool-result summarization (`context_optimization.tool_result_summarization_model`) | `everyday` |
| Recursive planner (`recursive_agent.planner_model`) | `powerful` |
| Deep-analysis dig and synth | `powerful` |

Feature override fields are nullable, and `null` is meaningful: `llm.model`,
`coding_model.model`, `recursive_agent.planner_model`,
`knowledge_graph.extraction.model`,
`context_optimization.tool_result_summarization_model`, and every
`deep_analysis.models.*` field default to `null`, which means "use the role
default". Setting a string pins that workload to an explicit model.

`recursive_agent.atomizer_model` is deliberately *not* role-routed; it keeps its
own Haiku value so sub-root atomization stays cheap.

#### Provider fallback in `LLMFactory`

`create_llm()` may fall back to OpenAI when the configured provider cannot be
constructed (typically a missing API key). That fallback is **only** available
to fully automatic calls:

| Call | Behavior on provider failure |
|---|---|
| `create_llm(temperature=0.3)` | falls back to OpenAI `everyday` (`gpt-5.6-terra`) |
| `create_llm(model="claude-opus-5")` | raises — an explicit model is never replaced |
| `create_llm(provider="anthropic")` | raises — an explicit provider is never replaced |
| any `provider="ollama"` call | raises — Ollama is an explicit local service |

Passing `model=` or `provider=` therefore means "use exactly this, or fail".
Providers outside the routing policy (`gemini`, `ollama`) have no role mapping,
so they require an explicit `model=` or a configured `llm.model`; otherwise
`create_llm()` raises a `ValueError` naming the provider.

## Staging and Production

Select profile config with bootstrap env:

```bash
NEOS_ENV=staging \
NEOS_CONFIG_PATH=config/neos.staging.yaml \
JWT_SECRET_KEY=test-secret-for-dry-run \
uv run python -c "from neos.config.settings import settings; print(settings.LOG_LEVEL); print(settings.RESEARCH_HARNESS_ENABLED)"
```

Production should use `NEOS_ENV=production` and a deployment-specific YAML file. Keep secrets in the runtime environment or a separate dotenv file referenced by `NEOS_SECRETS_PATH`.

## Compatibility Singleton

Existing Python code can continue using:

```python
from neos.config.settings import settings

settings.LLM_MODEL
settings.RESEARCH_HARNESS_ENABLED
settings.CORS_ALLOWED_ORIGINS
```

Internally, `settings` is now backed by a validated `AppConfig`. Legacy uppercase names are translated to typed config paths, while constants such as `ARTIFACTS_SYSTEM_PROMPT`, `INLINE_VIS_SYSTEM_PROMPT`, `WORKFLOW_CRITICAL_NODES`, `ALLOWED_FILE_EXTENSIONS`, and `CELERY_ACCEPT_CONTENT` remain code-defined.

Tests can rebuild the singleton:

```python
from neos.config.settings import reload_settings_for_tests

reload_settings_for_tests(
    env="development",
    config_path="config/neos.local.yaml",
    secrets_path=".env.test",
)
```

The `Settings` class remains instantiable for compatibility with existing tests.

## Validation Behavior

The schema currently validates:

- Boolean strings such as `false`, `0`, `no`, and `off` parse as `False`.
- Boolean strings such as `true`, `1`, `yes`, and `on` parse as `True`.
- `research_harness.default_mode` must be `auto`, `advisory`, `gate`, or `off`.
- Harness evidence storage policy must be `summary_only`, `redacted`, or `full`.
- Harness cache policy must be `passed_only` or `allow_advisory_fail`.
- `execution_approval.default_autonomy_level` must be `0`, `1`, or `2`.
- Quality evaluator weight mismatch warns instead of failing.
- Context assembly ratio mismatch warns in development and fails in staging/production.

## Verification

The backend config checkpoint was verified with:

```bash
pytest tests/config/test_config_schema.py \
  tests/config/test_config_loader.py \
  tests/config/test_config_files.py \
  tests/config/test_settings_compat.py \
  tests/test_harness_settings_defaults.py \
  tests/workflow/harness/test_policy.py \
  tests/api/services/test_workflow_service.py \
  tests/test_gemini_embedding_provider.py -v
```

Additional follow-up verification:

```text
pytest tests/config -v
43 passed

pytest tests/test_harness_settings_defaults.py tests/workflow/harness/test_policy.py \
  tests/api/services/test_workflow_service.py tests/test_gemini_embedding_provider.py -v
27 passed

docker compose -f docker-compose.dev.yml config --quiet
passed

env POSTGRES_PASSWORD=test JWT_SECRET_KEY=test RUSTFS_ACCESS_KEY=test RUSTFS_SECRET_KEY=test \
  docker compose -f docker-compose.enterprise.yml config --quiet
passed

cd web && pnpm exec tsc --noEmit
passed
```

The current test suite emits existing database fixture setup logs in some focused tests, but those logs did not cause failures in the verification runs. `uv run` dry-run and web `pnpm test:source`/`pnpm lint` were blocked by sandbox/network restrictions in this local session, so they should still run in CI or an unrestricted local shell.

## Troubleshooting

### Invalid YAML

If startup fails with an invalid YAML error, validate the file referenced by `NEOS_CONFIG_PATH` first. The loader expects a mapping at the top level.

### Legacy Env Warnings

Warnings for values such as `LLM_MODEL`, `RESEARCH_HARNESS_ENABLED`, or `CORS_ALLOWED_ORIGINS` mean the old env key still works in Release 1 compatibility mode, but the value should move to YAML.

### Missing Secrets

Keep required secrets in `.env`, a `NEOS_SECRETS_PATH` dotenv file, or real process env. Do not place API keys, passwords, tokens, access keys, or credential-bearing URLs in committed YAML files.

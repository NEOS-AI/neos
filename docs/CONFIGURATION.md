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

### Rust API Gateway

`api_gateway/config.toml` follows the same policy and ships `secret_key = ""`
and `password = ""` rather than usable defaults. The gateway **refuses to
start** when `jwt.secret_key` is still empty after env overrides — an empty
HS256 key would validate tokens signed with an empty key, so failing fast is
the safe behavior. Set `JWT_SECRET_KEY` before running it.

`DATABASE_URL` replaces the whole `[database]` block. When it is absent, the
transitional `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`
overrides apply individually. `GATEWAY_PORT`, `UPSTREAM_HOST`, `UPSTREAM_PORT`,
`LOG_LEVEL`, and `CONFIG_PATH` cover the remaining runtime knobs.

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
# Only for identity-linked Anthropic keys. Leave empty otherwise --
# an empty value sends no header, which is what non-linked keys expect.
ANTHROPIC_WORKSPACE_ID=
```

> **Identity-linked Anthropic keys.** Such a key rejects every request with
> `400 invalid_request_error` unless `anthropic-workspace-id` accompanies it.
> Set `ANTHROPIC_WORKSPACE_ID` (Anthropic Console → Settings → Workspaces) and
> every Anthropic call carries it: all clients are built by
> `neos/utils/anthropic_client.py`, which is the only place in the repo that
> constructs one. Leaving it empty sends no header at all -- deployments with
> ordinary keys are unaffected.

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

### Model Catalog

`neos/config/models.yaml` is the single source of truth for facts *about*
models — which ones the pickers offer, which recommendation tier they fill,
which thinking contract they follow, and what they cost. Adding a new Claude or
GPT model is a `models.yaml` edit plus updating the two expected-value lists
that pin the catalog against transcription errors, both in
`tests/config/test_model_catalog_parity.py`:

- `ANTHROPIC_SELECTABLE` / `OPENAI_SELECTABLE`, asserted by
  `test_catalog_selectable_lists_match_expected_order`
- the unpriced-model set, asserted by
  `test_every_selectable_model_without_pricing_is_known`

Both are deliberate pins, not incidental test debt — they are what catches a
new model silently breaking `list_models()` order or landing with no price. Do
not delete or relax them when adding a model; update them alongside
`models.yaml`.

```yaml
models:
  claude-sonnet-5:
    provider: anthropic          # anthropic | openai | gemini | ollama
    tiers: [balanced]            # fast | balanced | powerful (a model may fill two)
    thinking: adaptive           # adaptive | budgeted | none
    selectable: true             # exposed by list_models() (default true)
    max_tokens: 8192
    pricing: {input: 3.00, output: 15.00, cache_creation: 3.75, cache_read: 0.30}
```

Declaration order is the `list_models()` order, so keep newest models first.

| Field | Consumer |
|---|---|
| `provider` + `selectable` | `AnthropicProvider.list_models()`, `OpenAIProvider.list_models()` |
| `tiers` | `get_recommended_models(provider)` |
| `thinking` | `normalize_anthropic_request()` |
| `pricing` | `CostCalculator._get_default_pricing()` |

`thinking` names the request *contract*, not the model generation. A future
Claude that uses adaptive thinking needs one line — `thinking: adaptive` — and
no code change:

| Value | Behavior |
|---|---|
| `adaptive` | sends `thinking={"type": "adaptive"}` and strips `temperature`, `top_p`, `top_k`. A caller-supplied `budget_tokens` raises `ValueError` |
| `budgeted` | legacy path — honors `THINKING_BLOCKS_ENABLED` / `MAX_THINKING_LENGTH` and forces `temperature=1.0` |
| `none` | no thinking support; the payload is left alone |

A model absent from the catalog defaults to `budgeted`, which preserves the
behavior unknown Anthropic models had before the catalog existed.

`selectable: false` marks models the system still knows a price or a legacy
alias for but does not offer in a picker — for example `gpt-4o`, which
`aliases.vision.gpt4o` resolves to. It exists because `list_models()` and the
pricing table used to disagree: models were selectable with no price, and their
cost silently aggregated as zero.

Derivation applies to Anthropic and OpenAI only. Gemini keeps a static
`list_models()` (out of routing-policy scope) and Ollama queries its live
server at `/api/tags`, so neither list can be derived. Their `tiers` still live
in the catalog so `get_recommended_models()` covers all four providers, and
their entries are marked `selectable: false` to make that split explicit.

#### The catalog is not an allowlist

An unlisted model passes through and only produces a warning, so a brand-new
model can be used before the catalog is updated:

- `create_llm(model=...)` logs a warning **once per model name**.
- Cost aggregation warns and records zero when no price is known.
- `model_routing` role defaults are checked at startup and warn only — they
  never raise. Feature override fields are not checked there because, when
  they flow through `create_llm(model=...)`, that call already warns.

  Two paths bypass **both** checks — they never call `create_llm()`, so a
  typo in their override surfaces only as a provider error at request time,
  not a warning:

  - deep_analysis (`deep_analysis.models.{scout,dig,synth,judge}`) — resolved
    in `synthesizer.py`, `orchestrator.py`, `service.py`, and `worker.py`, then
    passed to `neos/workflow/deep_analysis/llm.py`'s `call_llm`, which builds
    its own client in `_default_client` instead of using `create_llm`.
  - chat tool-streaming (`neos/services/chat_llm_service.py`) — instantiates
    `anthropic.AsyncAnthropic` directly.

Pricing resolves in three layers, and the database still wins:

```
llm_model_pricing DB (time-bounded)  →  models.yaml pricing  →  warn + no price
```

#### One price, every consumer

The catalog is the single source of model pricing. Every consumer reads it:

| Consumer | Purpose |
|---|---|
| `CostCalculator` (`neos/utils/cost_calculator.py`) | billing — records into `message_costs`; the DB layer above still wins |
| `estimate_cost_usd()` (`neos/utils/token_counter.py`) | estimation, shared by both `TokenCounter` classes |
| `QualityMetricsCollector` (HDR) | per-report cost estimate, blending input and output rates |

Each of those used to carry its own table. They had already drifted: the two
token counters priced `gpt-4-turbo` differently from each other, and both fell
back to GPT-4 rates for anything unrecognized — which priced `claude-sonnet-5`,
the current default model, at $30/$60 per 1M instead of $3/$15.

None of them guess any more. An unknown or unpriced model estimates as `0.0`
with a warning, because a plausible-looking wrong price is worse than a missing
one: nobody audits a number that looks reasonable.

**`coding_model` prices are the exception, deliberately.**
`coding_model.input_cost_micros_per_million` and its `output_` counterpart are
integer micros used as the coding loop's budget guard — operator policy, so a
negotiated rate must be allowed to differ, and the catalog never overwrites
them. But the same model's price then lives in two places and can silently
diverge, so startup logs a warning when they disagree
(`warn_coding_model_price_drift`). The check cannot live in
`neos/config/schema.py`: that module is pure schema and `model_config` imports
`StrictConfigModel` from it, so a validator reading the catalog would create an
import cycle.

#### Every selectable model is priced

A model with no price still works — the catalog is not an allowlist — but its
cost aggregates as **zero**, which silently makes `neos_llm_cost_usd`
under-report. So nothing offered in a picker may lack a price.

Six models used to violate that and were retired:

| Retired | Replaced by |
|---|---|
| `claude-sonnet-4-6` | `claude-sonnet-5` |
| `claude-opus-4-6` | `claude-opus-5` |
| `gpt-5-mini-2025-08-07`, `o3-mini` | `gpt-5.6-terra` |
| `gpt-5-2025-08-07`, `o3` | `gpt-5.6-sol` |

`gpt-5-mini-2025-08-07` held OpenAI's `fast` tier, which moved to
`gpt-5.6-terra` — so terra now fills both `fast` and `balanced`, the same
one-model-two-tiers shape Gemini and Ollama already use.

`test_every_selectable_model_is_priced` enforces the invariant, and
`test_retired_models_are_gone_from_the_catalog` stops the six coming back
without a `pricing:` block.

Should the invariant ever break — or should a stored conversation still name a
retired model — every unpriced lookup increments
`neos_llm_unpriced_calls_total{provider,model}`. Alert on it: a non-zero value
names exactly which model needs a price, and the fix is one row in
`llm_model_pricing` or one `pricing:` block in `neos/config/models.yaml`.

#### Which provider serves a model

`provider_for_model()` answers this from the catalog. Code used to guess from
the name — `"gpt" in model` / `model.startswith("claude")` — which mis-routed
any model whose name carries no provider hint. Retired `o3` was exactly that
case: an OpenAI model, offered in the OpenAI picker, that fell through to the
default provider (Anthropic).

Callers fall back to the old name heuristic when the catalog does not know the
model, so a brand-new model still works before the catalog is updated. In
`neos/workflow/deep_analysis/llm.py` the same predicate also selects the request
payload shape, so client choice and payload shape share one helper
(`_is_anthropic_model`) and cannot disagree.

#### When the catalog fails to load

A bad catalog never blocks boot, but it must never be mistaken for a good one
either — an empty catalog would send Claude 5 the legacy `budgeted` request
shape, empty every picker, and zero all pricing.

| Situation | Behavior |
|---|---|
| File missing or unparseable YAML | empty catalog, `logger.error` |
| Schema violation on the **first** load | empty catalog, `logger.error` naming what falls back to defaults |
| Schema violation on a **reload** | **the last-good catalog stays in effect**, `logger.error` says the reload was rejected |
| Catalog is empty at startup | `logger.error` from the lifespan check, before the database is touched |

A "schema violation" is anything Pydantic rejects: an unknown `provider:` value,
a mistyped field name, or two models claiming the same `(provider, tier)` pair.
`load_catalog()` itself still raises `ValidationError` — the graceful handling
lives in `ModelConfig.reload()`, so callers that want the error can still get it.

Malformed *legacy-shape* entries are skipped individually with a warning rather
than discarding the file, so one bad hand-edited alias does not take every other
model with it.

#### Legacy catalog files

`NEOS_MODEL_CONFIG_PATH` can point at a custom file. A file with no `models:`
key is read in the old shape (`vision_models` / `llm_models` /
`embedding_models`), converted in memory, and logged with a migration notice.
Converted entries have no tier and no price, and fall back to
`thinking: budgeted`. Provider `google` is normalized to `gemini`.

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

#### What is deliberately *not* role-routed

The policy has exactly two roles, `everyday` and `powerful`. There is no `fast`
role, so cheap workloads keep their own explicit settings:

- `recursive_agent.atomizer_model` keeps its Haiku value so sub-root
  atomization stays cheap.
- Query classification, expansion, and similar helpers keep their own
  `*_LLM_MODEL` settings.
- `get_recommended_models()` still reports a `fast` tier, but that is a manual
  reference list for operators, not a routing role.

Adding a `fast` role means extending `WorkloadRole` and
`ProviderModelRolesConfig` together, and needs a Haiku-tier policy designed
first. `tests/config/test_model_routing.py::test_policy_stays_at_two_roles`
pins the current decision.

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

### Anthropic prompt caching and Advisor

`llm.prompt_caching` enables Anthropic prompt caching on eligible request paths.
It is enabled by default with a `5m` TTL; operators can select `1h` when request
reuse justifies the longer cache lifetime.

`llm.advisor` configures Anthropic's Advisor tool and is disabled by default.
Advisor is injected only when the executor and Advisor model combination is
documented as compatible and the executor path supports the complete beta
server-tool protocol. Incompatible or unknown executor models continue without
Advisor while retaining prompt caching.

`llm.advisor.max_pause_turns` caps automatic `pause_turn` continuations and
defaults to `3`, preventing an indefinite server-tool loop. Advisor-side prompt
caching is separately disabled by default because `max_uses` defaults to `2`;
enable it only when observed requests regularly make at least three Advisor
calls, Anthropic's approximate cache break-even threshold.
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

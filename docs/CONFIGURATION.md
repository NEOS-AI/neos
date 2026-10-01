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

`neos/config/models.yaml` is the operator bump surface for facts, role-alias
current-pins, remaps, retirements, and picker projection. Roles in `schema.py`
point at `sonnet-5` / `opus-5.5`. The chat picker fetches
`GET /api/v1/models` at runtime, so a YAML deploy moves the live picker
without a web rebuild. Do **not** hand-edit `web/lib/ai/models.ts` maps or
`web/lib/ai/catalog.generated.ts`.

#### Point-release bump playbook (Sonnet / Opus 5.1 or 5.5)

1. Add the new pin under `models:` with `role_alias`, explicit `gateway_id`,
   `picker:` (name / description / group), thinking, vision, and pricing.
2. Move `role_aliases.<track>.current` to the new pin.
3. Retarget every `remaps:` value that previously landed on the old pin.
   Remap **values** are catalog pins, not gateway ids.
4. Remove `picker:` from the old pin so it drops off `GET /models`. Keep the
   row and leave `selectable: true` so stored pins and non-FE clients still
   pass `is_user_selectable_model`.
5. Update the parity lock lists in
   `tests/config/test_model_catalog_parity.py`:
   - `ANTHROPIC_SELECTABLE` / `OPENAI_SELECTABLE`
     (`test_catalog_selectable_lists_match_expected_order`)
   - the unpriced-model set
     (`test_every_selectable_model_without_pricing_is_known`)
6. Add an `anthropic_families:` prefix **only if** cache-minimum and advisor
   targets were measured. A 5.1 that shares the 5.0 contract inherits the
   existing `claude-sonnet-5` prefix (longest match). A distinct contract is
   a new `role_aliases.sonnet-5.5` plus one `model_routing` edit — not a
   guessed family row.
7. Regenerate the committed FE fallback. Do not hand-edit the file:

   ```bash
   python scripts/generate_catalog_fallback.py
   ```

   CI runs that script and fails on
   `git diff --exit-code -- web/lib/ai/catalog.generated.ts`.
8. Deploy the API. The live picker does **not** wait for a web rebuild.

Do **not** edit `schema.py` role defaults or handwritten FE maps. `getTitleModel`
/ `getArtifactModel` stay Haiku pins until an aux PR.

A new **Anthropic** model still has the generation-facts obligation in
*Generation facts* below — `test_anthropic_model_families.py` fails until
you record the answer (or add it to `_UNCOVERED`).

#### Live picker vs committed fallback

| Surface | When it moves |
|---|---|
| `GET /api/v1/models` | API deploy (live picker) |
| `web/lib/ai/catalog.generated.ts` | after the generator + web image |

Frontend dual-read is a Next **server** env var, not AppConfig (Next cannot
read `schema.py`):

- `CATALOG_API=1` — fetch `GET /api/v1/models` with `cache: "no-store"`.
  Requires `model_catalog.picker_api: true` on the API.
- Unset `CATALOG_API` — use `catalog.generated.ts`.
- API 404 / 503 / empty — same generated fallback. A 503 must not clear
  the picker.

`picker_api` production default stays **false** until soak. Staging that
wants the live picker must set **both**:

```yaml
# API env YAML
model_catalog:
  picker_api: true
```

```bash
# Next server
CATALOG_API=1
```

Rollback: unset `CATALOG_API`. The generated file is the last shipped
picker (still a valid selectable pin).

`selectable: true` is **not** picker membership. `picker:` present → one
`GET /models` row (plus `picker.extras`). `gpt-6-astra` and Gemini stay
selectable and out of the chat picker until someone adds a `picker:` block.

Cookie `chat-model` stores a gateway id. On page load the FE remaps it
in memory (`raw → gateway_id` still in `models[]`; else `default_id`)
and persists the new value after hydration via `saveChatModelAsCookie`
(a client-invoked Server Action — Next 16 cannot `cookies().set` during
RSC render). The next FE turn sends `metadata.model` as the remapped
catalog pin. Stored `conversations.model_name` is **not** rewritten;
backend-only paths stay on the stored / role pin.

Tests that hit `GET /api/v1/models` must enable `picker_api`. The
production default remains false.

Custom catalogs (`NEOS_MODEL_CONFIG_PATH`) must ship `role_aliases:` (the
schema defaults are now `sonnet-5` / `opus-5.5`, not dated pins). A file
without that block will not resolve those roles: boot logs the existing
unknown-routed-model warning and everyday traffic has no pin. The
alternative is a dated `model_routing` override in env YAML
(`everyday: claude-sonnet-5`). Legacy conversion does **not** invent role
aliases. `aliases.llm.*` stay pin-valued — moving
`role_aliases.sonnet-5.current` does not move `get_llm_model_id`.

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

#### Generation facts (Anthropic)

Two Anthropic features are defined by *generation*, not by model id: which
Advisor models an executor may pair with, and the minimum prompt length at
which caching becomes eligible. `anthropic_families:` carries both.

```yaml
anthropic_families:
  - prefix: claude-opus-4-7        # longest matching prefix wins
    family: opus-4.7               # omit -> this generation cannot use Advisor
    cache_minimum_tokens: 2048     # omit -> 1024
    advisor_targets: [opus-4.7, opus-4.8, fable-5, mythos-5]
```

| Field | Consumer |
|---|---|
| `family` | `canonical_model_family()` → `build_tool_policy()` |
| `advisor_targets` | `build_tool_policy()` — the executor→advisor compatibility check |
| `cache_minimum_tokens` | `normalize_anthropic_usage()` — decides `cache_status: ineligible` |

Matching is by **prefix** rather than by model id on purpose: a dated variant
such as `claude-opus-4-7-20260101` shares its generation's facts whether or not
the catalog lists it, and requiring each variant to be registered would make
those facts disappear silently the moment one is not. The loader rejects a
prefix nested inside another — in the Python table this replaced, declaration
order decided the winner and nothing said so.

`family` and `cache_minimum_tokens` are independent. An entry may carry cache
facts with no `family` (`claude-opus-4-5` does), which reproduces the state the
two separate Python tables were in: they used different prefix vocabularies,
and merging them preserved that asymmetry rather than inventing entries to
erase it.

> **Known gap — `claude-opus-5-5` has no generation facts** (inherited from
> the retired `claude-opus-5`). It is the deep
> analysis `powerful` worker and the `powerful` picker tier, but the table this
> block replaced only ever knew opus-4.5 through 4.8. With Advisor enabled it
> is skipped as `unknown_executor_model`, and its cache floor is the unverified
> 1024 default. No values are guessed here — measure them before filling the
> entry. `_UNCOVERED` in `tests/config/test_anthropic_model_families.py` pins
> the gap in both directions, so closing it also fails until that list is
> updated. This is harmless while `llm.advisor.enabled` is `false`.

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

#### 2026-09-24: Opus 5.5 and GPT-6

| Retired | Replaced by |
|---|---|
| `claude-opus-5` | `claude-opus-5-5` |
| `gpt-5.6-sol` | `gpt-6-sol` |
| `gpt-5.6-terra` | `gpt-6-sol` |

GPT-6 has no Terra-class model, so `gpt-6-sol` fills both OpenAI roles
(`everyday` and `powerful`) and the `balanced`/`powerful` tiers.
`gpt-6-luna` takes the `fast` tier. The role alias `opus-5` became `opus-5.5`.

Old picker cookies go through `remaps:`. Old **pins and role aliases** go
through `retired:`, which applies to every resolution source, including stored
conversation pins and feature overrides. `remaps:` apply only to user/cookie
strings. Without `retired:`, a conversation stored on `claude-opus-5` would
resolve as an unknown model. An unknown Claude model gets the `budgeted`
thinking contract, and Opus 5 rejects `budget_tokens` with a 400.

`claude-opus-5-5` and `claude-fable-5-1` declare `thinking_always_on: true`:
`{type: "disabled"}` is a 400 on them at every effort level, so
`normalize_anthropic_request` never sends it there (the search agents'
`DISABLE_THINKING_FOR_SEARCH` is on by default). Opus 5.5 also rejects forced
`tool_choice` (`any`/`tool`). The only forced call today
(`ui_frame_generator`, A2UI) runs on Haiku.

Prices are in the catalog and in `db/migrations/062_llm_pricing_opus55_gpt6.sql`
(the DB outranks the catalog). OpenAI rates are the short-context tier; input
over 272K tokens costs 2x and is not modelled.

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

Custom catalogs must ship `role_aliases:` (the schema defaults are now
`sonnet-5` / `opus-5.5`, not dated pins). A file without that block will not
resolve those roles: boot logs the existing unknown-routed-model warning and
everyday traffic has no pin. The alternative is a dated `model_routing`
override in env YAML (`everyday: claude-sonnet-5`). Legacy conversion does
**not** invent role aliases. `aliases.llm.*` stay pin-valued — moving
`role_aliases.sonnet-5.current` does not move `get_llm_model_id`.

### Model Routing

`model_routing` maps a provider and a workload role to a role alias or a
catalog pin. The resolver accepts either and returns the pin when the pick
is a known alias or pin; unknown values pass through. Remaps apply only to
USER/cookie strings — a stored conversation pin or a feature override is
not rewritten. Automatic workloads that omit a model still follow the
role default.

```yaml
model_routing:
  anthropic:
    everyday: sonnet-5
    powerful: opus-5.5
  openai:
    everyday: gpt-6-sol
    powerful: gpt-6-sol
```

Resolution follows a strict precedence, and the winner is reported as
`ModelResolution.source`:

1. `user` — the model named in the current request
2. `conversation` — the model already stored on an existing conversation
3. `feature_override` — a deployment/feature setting (below)
4. `role_default` — the `model_routing` entry for that provider and role

The resolver itself never falls back across providers. An unknown provider or
role, or a blank mapping entry, raises `ValueError` rather than guessing.

#### Reasoning effort

`output_config.effort` (Anthropic) is resolved through the **same chain** as the
model, with the same precedence and the same `ResolutionSource` vocabulary — a
second chain would reintroduce the "a fix lands in one caller only" failure.

```yaml
model_routing:
  effort:            # role defaults; null means "do not ask"
    everyday: null
    powerful: null

deep_analysis:
  model_effort:      # per-harness-role, consumed as the feature override
    scout: null
    dig: null
    synth: null
    judge: null

coding_model:
  effort: null       # the coding loop's feature override
```

Two things make effort different from the model:

- **A capability gate.** The resolved level is only sent when the catalog says
  the resolved model accepts it (`models.yaml` → `effort_levels`). A level the
  model does not take is **refused, never downgraded** — silently sending the
  nearest level would make the configured value and the value that actually ran
  differ, with nothing recording the difference. `EffortResolution.refused`
  carries the reason so an operator who set a level and saw nothing happen can
  tell a config mistake from a code one.
- **Every configured value is empty today.** The catalog now declares measured
  `effort_levels` (see *Effort (per model and per user)* below), but no role,
  harness role or model default asks for a level, so nothing is sent.

Deep analysis reads the chain once per harness role through
`resolve_harness_effort` (`neos/workflow/deep_analysis/model_roles.py`), with
`deep_analysis.model_effort.<role>` as the feature override and
`model_routing.effort.models[<resolved model>]` as the per-model default — the
same slot chat uses, so a per-model default is a deep analysis sample boundary.
Every deep analysis call site passes the resolved value as `effort=`; a test
walks the package's AST and fails on a call that omits it. The run manifest
records each role's `effort: {level, source, refused}`.

The coding loop reads the chain once per runtime through `resolve_coding_effort`
(`neos/config/coding_selection.py`): `coding_model.effort` as the feature
override, `model_routing.effort.models[<coding model>]` as the per-model
default, and `model_routing.effort.everyday` as the role default — the role the
coding loop picks its model with. So a per-model or `everyday` default applies
to chat, deep analysis **and** coding, and setting one is a coding-agent sample
boundary as well. The level rides on the loop's turns, on the preserving
compaction summary (not the legacy 512-token one, where thinking would eat the
summary), and on children, but only when the child runs on the model the level
was resolved for. A refused level is logged at runtime construction
(`coding effort not sent: ...`).

⚠️ `deep_analysis.model_effort` and `deep_analysis.effort` are **different
axes**. The latter is investigation depth (`token_cap`, `wall_clock_cap`); the
former is how much the model thinks.

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
| `create_llm(temperature=0.3)` | falls back to OpenAI `everyday` (`gpt-6-sol`) |
| `create_llm(model="claude-opus-5-5")` | raises — an explicit model is never replaced |
| `create_llm(provider="anthropic")` | raises — an explicit provider is never replaced |
| any `provider="ollama"` call | raises — Ollama is an explicit local service |

Passing `model=` or `provider=` therefore means "use exactly this, or fail".
Providers outside the routing policy (`gemini`, `ollama`) have no role mapping,
so they require an explicit `model=` or a configured `llm.model`; otherwise
`create_llm()` raises a `ValueError` naming the provider.

#### Effort (per model and per user)

Effort is the provider's thinking-depth parameter — Anthropic
`output_config.effort`, OpenAI `reasoning_effort`. It is not deep analysis
`Effort` (scout/dig/synth).

- **Which levels a model takes** is a catalog fact: `effort_levels` in
  `neos/config/models.yaml`, checked against each provider's SDK vocabulary
  (`EFFORT_VOCABULARY`). Anthropic levels come from the models API
  (`scripts/probe_anthropic_effort.py`); GPT-6 levels from OpenAI's models docs.
  Empty means unknown, and nothing is sent.
- **Per-model defaults** are policy: `model_routing.effort.models`
  (`{pin: level}`, empty in `config/neos.default.yaml`). An unknown pin or a
  level the model does not take fails boot. Setting one is a deep analysis
  sample boundary.
- **User choice** lives in `user_model_preferences` (migration 063), set via
  `PUT /api/v1/users/me/model-preferences/{model}` and the selector next to
  the chat picker. `{model}` accepts gateway ids and retired pins; they are
  stored as the canonical pin. `DELETE` returns the model to its default.

Precedence per chat turn: user × model → conversation → feature override →
model default → role default → nothing sent. Resolution happens once, in
`neos/services/chat_effort.py`, reading the preference with one query joined
on `conversation_id` (no owner lookup), and only for models that declare
levels. Translation to request fields happens once, in
`neos/providers/effort.py`; when nothing is resolved no key is sent. A stored
level the model no longer takes is refused with a warning and the next rung
applies. A failed preference lookup never fails the turn.
`neos_chat_effort_resolved_total{source}` counts turns by where their effort
came from. Automatic jobs that go through `generate_response` with a
non-`chat` `workflow_type` (title generation) get no effort at all — a
50-token title must not be spent on thinking.

On `thinking_always_on` models, a "thinking off" request becomes
`effort: low` when the model declares `low`, unless an explicit effort was
already resolved.

OpenAI `reasoning_effort` has not been verified live (the OpenAI key returned
401 when this shipped). Check that `temperature` is accepted alongside a
non-`none` effort before relying on it.

### Anthropic prompt caching and Advisor

`llm.prompt_caching` enables Anthropic prompt caching on eligible request paths.
It is enabled by default with a `5m` TTL; operators can select `1h` when request
reuse justifies the longer cache lifetime.

`llm.advisor` configures Anthropic's Advisor tool and is disabled by default.
Advisor is injected only when the executor and Advisor model combination is
documented as compatible and the executor path supports the complete beta
server-tool protocol. Incompatible or unknown executor models continue without
Advisor while retaining prompt caching.

That compatibility table lives in the catalog, not in code — see *Generation
facts (Anthropic)* above. **Before enabling this, check that the executor
models you actually route to have a `family` there.** `claude-opus-5-5` does not,
so with the default role routing turning Advisor on today changes nothing at
all: every deep analysis worker would be skipped as `unknown_executor_model`,
and a feature that silently does nothing is worse than one that is off.

`llm.advisor.max_pause_turns` caps automatic `pause_turn` continuations and
defaults to `3`, preventing an indefinite server-tool loop. Advisor-side prompt
caching is separately disabled by default because `max_uses` defaults to `2`;
enable it only when observed requests regularly make at least three Advisor
calls, Anthropic's approximate cache break-even threshold.
### Jev probabilistic risk banding

`jev` puts a probability from TypeSafe AI's System One model on top of the
static tool-approval policy. Everything is off by default; when off, the coding
loop takes the exact path it took before the feature existed.

```yaml
jev:
  enabled: false                   # master switch; sub-flags require it
  tool_risk_shadow_enabled: false  # score and record, change nothing
  tool_risk_gate_enabled: false    # actually narrow the outcome
  judge_shadow_enabled: false      # judge-side shadow (not yet wired)
  model: null                      # a resolved id, e.g. jev-1.13.0
  tool_risk_rubric: tool_risk_split  # neos/jev/rubrics/<name>.yaml
  question_thresholds: {}          # per question of a split rubric, no defaults:
  #   irreversible: {low_below: ..., high_at_or_above: ...}
  #   exfiltration: {low_below: ..., high_at_or_above: ...}
  low_below: null                  # single-question rubrics only
  high_at_or_above: null           #   (e.g. tool_risk_rubric: tool_risk)
  timeout_sec: 5.0
```

**The default rubric asks two questions** (`irreversible`, `exfiltration`).
Each question is banded against its own thresholds, and the call takes the
strictest resulting outcome. Probabilities are never combined into one number:
a combination rule would be one more unmeasured constant, and the ledger would
lose which axis was high. The keys of `question_thresholds` must match the
rubric's questions exactly -- a missing or extra key fails at assembly. Giving
both `question_thresholds` and the single `low_below`/`high_at_or_above` pair
is rejected, because the ledger could not tell which one was used.

The key is `TYPESAFE_API_KEY`, read from the process environment or `.env` with
the same precedence as every other secret (process wins).

**The band thresholds have no defaults.** Turning banding on without both of
them fails validation rather than falling back to a number nobody measured.
Pick them from a measured baseline, not from a vendor cookbook: the measured
run-to-run spread is widest exactly where the thresholds matter (see the Jev
section of `docs/DEEP_ANALYSIS_HARNESS_ROADMAP.md`), so a threshold placed
where real calls cluster makes the same call flip bands between runs.

**`model` must be a resolved id.** Validation rejects anything containing
`latest`: the SDK would otherwise default to the `jev-latest` alias, and a run
answered by an alias cannot say which model answered it.

Three properties are enforced rather than documented:

- **Narrowing only.** The probability can make an outcome stricter, never
  looser; `DENY` never becomes `ALLOW`. A static `DENY` does not call Jev at
  all, so no availability fallback can open it.
- **Loud fallback.** If Jev times out or errors, the static outcome stands and
  a `jev_unavailable` event records it. Watch that event's rate: making Jev
  unreachable is the cheapest way to remove the gate.
- **A provider block is not a fallback.** TypeSafe's edge WAF rejects request
  bodies containing strings it treats as attack payloads -- including text in a
  tool's input. Such a 403 (no `x-typesafe-request-id`, HTML body) is recorded
  as `jev_unavailable` with `reason: provider_blocked`, and when enforcing it
  narrows one step like the middle band instead of letting the static outcome
  stand. Otherwise anyone who can put that string into a tool input could turn
  the gate off for that call. Rubric text is sent with every request, so a
  rubric must not contain such strings either; a test checks the known ones.
- **Misconfiguration is not "off".** Enabling banding without a key, a pinned
  model, or thresholds raises at assembly time instead of quietly running
  ungated.

While enforcement is on, the loop stops speculatively prefetching read-only
tools: that path executes a tool before the decision and would outrun the gate.

#### Trajectory monitor (shadow)

`jev.monitor` judges a coding task's *flow* rather than one call: recent tool
calls, their outcomes, the denial reasons and the task mode. It is roadmap
track Q5 (`docs/OPENAI_DOTS_ANALYSIS_260930.md`). It is shadow-only: every
judgement is one `monitor.judged` ledger event with `enforced: false`, and no
task is paused.

```yaml
jev:
  enabled: true                    # required by the monitor too
  model: jev-1.13.0
  monitor:
    shadow_enabled: false
    rubric: trajectory_scope       # one noul question
    pause_at_or_above: null        # no default -- required when enabled
    every_n_tool_results: 5        # judge after this many tool results
    max_events: 2000               # most recent ledger events read
    # Fallback rules FB1-FB6. Defaults are also the loosest allowed values:
    user_only: 1                   # FB1 policy_user_only denials
    mode_ceiling: 2                # FB2 policy_mode_ceiling denials
    denial_window: 10              # FB3 window (may only grow)
    denials_in_window: 3           # FB3 denials within the window
    repeated_call: 3               # FB4 same tool + same preview
    refusals: 1                    # FB5 model.refused
    spend_multiple: 4.0            # FB6 turn tokens vs median of earlier turns
    spend_warmup_turns: 5          # FB6 turns before it judges
```

Jev is the judge. When it errors, times out, is blocked, or returns no
probability, the fallback rules judge that one time and the event says so
(`judge: fallback_rules`, `jev_unavailable: true`, `ruleset`). The rules read
only the ledger. **Config can only make them stricter**: each field's default is
its bound, so validation rejects a looser value. The monitor reads the ledger
through the event store's `list_after`; a sink without it is never judged, and a
monitor error is logged and never changes the run.

### Coding approval: USER_ONLY and background mode

`coding_model.approval_user_only_extra` adds argv prefixes (for example
`"gh workflow run"`) to `USER_ONLY_COMMANDS` in `neos/coding/domain/approvals.py`.
Those commands are refused even with approval, auto mode or allow lists, with
reason `policy_user_only`. The setting is merged as a union; there is no way to
remove a built-in entry.

A coding task created with `mode: background` is unattended and capped at the
validated risk `read_only`. Writes, commands and questions are refused as
`policy_mode_ceiling`, even when an allow list says allow.

### Standing agents

```yaml
standing_agents:
  enabled: false   # off: the /api/v1/standing-agents routes are not mounted at all
```

Roadmap track Q13 (`docs/Q13_STANDING_AGENT_DESIGN_260930.md`). One agent per
user, created explicitly with `POST /api/v1/standing-agents`; a second one is
`409 {"code": "one_per_owner"}`. Names have no length limit and must be unique
per owner, ignoring case and surrounding space. Someone else's agent answers
404, exactly like a missing one. `GET /api/v1/standing-agents/me` is an alias
for the only agent.

Creating an agent also opens one `background` coding task, its
self-introduction (the response carries `onboarding_task_id`; `null` if it could
not start -- the agent is still created). The prompt lists the enabled channels
the owner is mapped to and the model-invocable skills, by name and description
only. When that task completes, its final answer is stored as a **staged** memo
titled `자기소개`; a failed or cancelled introduction leaves none. This costs one
background model run per created agent.

`GET /api/v1/standing-agents/{agent_id}/activity?after=<next>&limit=` merges the
ledger events of every task the agent opened. The cursor is the writing
transaction id (`coding_events.xact_id`, migration 072) and the reader stops
below `pg_snapshot_xmin`, so a long-open transaction anywhere in the database
**delays** the feed (it never skips). If the feed looks stuck, look for
`idle in transaction` sessions in `pg_stat_activity`.

#### Webhook triggers (track Q4a)

```yaml
standing_agents:
  triggers:
    enabled: false                  # off: no trigger routes are mounted
    max_body_bytes: 65536           # larger deliveries are 413, before the signature is read
    timestamp_tolerance_seconds: 300
```

```bash
NEOS_TRIGGER_SIGNING_KEY=...        # required when triggers are on, >= 32 chars (openssl rand -hex 32)
```

Both `standing_agents.enabled` and `standing_agents.triggers.enabled` must be on.
With triggers on and the key missing or shorter than 32 characters, config
validation refuses to start. Design: `docs/Q4_Q10_TRIGGER_BUDGET_DESIGN_261001.md`.

`POST /api/v1/standing-agents/{agent_id}/triggers` with
`{"prompt_template": "...", "filters": [{"path": "action", "equals": "opened"}]}`
returns the trigger, its `delivery_path` and its `secret`. **The secret is shown
only here.** It is not stored: it is `HMAC(NEOS_TRIGGER_SIGNING_KEY, trigger_id)`,
so changing the master key changes every trigger's secret. Filters match the JSON
body by dotted path and exact JSON type (`1` is not `"1"` and not `true`); all must
match, and no filters means every delivery fires.

A sender delivers with:

```
POST /api/v1/standing-triggers/{trigger_id}/deliveries
X-Neos-Timestamp: <unix seconds>
X-Neos-Delivery:  <unique id, [A-Za-z0-9_:-]{1,128}>
X-Neos-Signature: v1=<hex HMAC-SHA256(secret, "<timestamp>.<delivery>." + raw body)>
```

```python
import hashlib, hmac, time
ts = str(int(time.time()))
sig = hmac.new(secret.encode(), f"{ts}.{delivery}.".encode() + body, hashlib.sha256).hexdigest()
headers = {"X-Neos-Timestamp": ts, "X-Neos-Delivery": delivery, "X-Neos-Signature": f"v1={sig}"}
```

Any authentication failure (unknown trigger, bad signature, clock off by more
than the tolerance, malformed headers) is the same `401`. An authenticated
delivery is always `202 {"status", "task_id", "reason"}` with status `fired`,
`duplicate` (same delivery id again: same `task_id`), `filtered`, or `refused`
(`trigger_disabled`, `agent_paused`, `agent_retired`, or a budget reason below).
A fired delivery opens one **background** (read-only) task of the agent; the
body is wrapped as an untrusted document after the owner's template. A refused
delivery leaves no idempotency record, so a retry after the agent is resumed
fires.

#### Budget envelope (track Q10a)

```yaml
standing_agents:
  budget:
    enabled: false
    monthly_limit_micros: 20000000   # per agent per UTC calendar month ($20)
    background_share: 0.5            # background tasks may spend only this share
    reserve_background_share: true   # false: autonomous work may also spend that share
```

Spend is not counted separately: it is the sum of the latest checkpoint's
cumulative `cost_micros` over every task the agent opened in the month (a task
belongs to the month it was opened in; archived tasks still count). An agent at
or over its limit opens no new task (`budget_envelope_exhausted`); background
work stops at its share (`budget_background_share_exhausted`) while work the
user handed over (`autonomous`) is held to the rest: by default the share is
**reserved**, so autonomous work stops once its own spend (total minus
background) reaches the envelope minus the share
(`budget_handed_over_share_exhausted`) and never starves the agent's background
work. With `reserve_background_share: false` autonomous work may spend the whole
envelope, share included. With `background_share: 1.0` and the reservation on,
autonomous work gets nothing. This applies to the self-introduction and to triggers alike.

Running tasks are **not** stopped yet. When one is over the envelope at a model
turn, the ledger gets one `budget.judged` event per run (`enforced: false`),
visible in the activity feed. Pausing a running task is a later step shared with
the trajectory monitor (Q5).

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

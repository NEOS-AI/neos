# Role-Based Model Routing Design

**Date:** 2026-07-25
**Status:** Approved for implementation planning

## Summary

NEOS will use one central role-based model policy for automatic model
selection. Everyday work will use Claude Sonnet 5 or GPT-5.6 Terra, while
high-performance work will use Claude Opus 5 or GPT-5.6 Sol. A model explicitly
selected by a user remains authoritative and bypasses automatic routing.

The migration will also update provider request construction for the Claude 5
API contract. Sonnet 5 and Opus 5 use adaptive thinking and reject manual
thinking budgets and non-default sampling parameters, so NEOS must not treat
this as a string-only model upgrade.

Official model IDs:

- Anthropic everyday: `claude-sonnet-5`
- Anthropic powerful: `claude-opus-5`
- OpenAI everyday: `gpt-5.6-terra`
- OpenAI powerful: `gpt-5.6-sol`

## Goals

- Make the requested Claude 5 and GPT-5.6 models the defaults for automatic
  work.
- Keep user-selected models unchanged for the lifetime of the request or
  conversation.
- Express workload intent as stable `everyday` and `powerful` roles rather than
  scattering provider-specific model IDs throughout the codebase.
- Route ordinary chat, routine coding, lightweight execution, scouting, and
  evaluation through the everyday role.
- Route planning, deep investigation, synthesis, and other complex agentic
  work through the powerful role.
- Preserve deployment-specific explicit overrides.
- Make Claude 5 requests compatible with adaptive thinking and sampling
  restrictions.
- Keep frontend display names, gateway IDs, and backend model IDs consistent.
- Cover routing precedence, role mappings, and provider compatibility with
  focused tests.

## Non-goals

- Selecting a provider on behalf of a user who explicitly chose one.
- Using an additional LLM call to classify the difficulty of every request.
- Replacing Gemini, xAI, embedding, reranking, or vision-specific models that
  are outside the requested Claude and GPT routing policy.
- Migrating historical conversation rows or rewriting a model already stored
  on an existing conversation.
- Adding Claude Fable 5, Mythos 5, or GPT-5.6 Luna to automatic routing.
- Introducing cost-based failover between providers.

## Considered Approaches

### 1. Replace model strings in place

Every old Sonnet, Opus, and GPT default could be replaced directly. This is
quick, but it preserves the current duplication across schema defaults, YAML
profiles, providers, frontend metadata, and workflow roles. The next model
upgrade would require another repository-wide replacement and could again
produce mismatched names and IDs.

### 2. Central role-based model profiles

A focused policy module will map provider plus workload role to a model ID.
Consumers will express intent as `everyday` or `powerful`, while explicit model
values remain overrides. This provides deterministic behavior, avoids an
extra inference call, and gives tests one authoritative mapping. This is the
selected approach.

### 3. Dynamic per-request difficulty classification

NEOS could classify each prompt before selecting a model. This could capture
nuance within ordinary chat, but it adds latency, cost, nondeterminism, and
another failure mode. Existing NEOS workflow roles already provide a reliable
signal for internal work, so dynamic classification is not justified.

## Routing Policy

The central policy exposes two workload roles:

| Role | Anthropic | OpenAI |
| --- | --- | --- |
| `everyday` | `claude-sonnet-5` | `gpt-5.6-terra` |
| `powerful` | `claude-opus-5` | `gpt-5.6-sol` |

Workload assignments:

| Workload | Role |
| --- | --- |
| New chat default | `everyday` |
| Routine coding executor | `everyday` |
| Lightweight execution and ordinary model-based evaluation | `everyday` |
| Deep-analysis scout and judge | `everyday` |
| Recursive planner | `powerful` |
| Deep-analysis dig worker | `powerful` |
| Deep-analysis synthesis | `powerful` |
| Explicitly marked complex agentic work | `powerful` |

The deep-analysis judge remains on a model different from the dig and synthesis
workers within the same provider family. This preserves the existing
worker-versus-judge separation while upgrading both roles.

## Resolution Precedence

Model resolution uses the following strict order:

1. A model explicitly supplied by the user in the current request.
2. A model already stored for an existing user-selected conversation.
3. An explicit deployment or feature configuration override.
4. The provider and workload role from the central model policy.

Only the fourth case is automatic routing. The resolver will return structured
resolution metadata containing the selected model, provider, role, and source
of the decision. Consumers may log this metadata, but it will not expose API
keys or prompt content.

A missing or unknown provider/role mapping is a configuration error. NEOS will
not silently choose a different provider or fall back to an older model.

## Configuration

Typed configuration will hold the central defaults in a small model-routing
section:

```yaml
model_routing:
  anthropic:
    everyday: claude-sonnet-5
    powerful: claude-opus-5
  openai:
    everyday: gpt-5.6-terra
    powerful: gpt-5.6-sol
```

Feature-specific model fields remain valid as explicit overrides. Their
defaults will be removed where the central resolver can supply a role-based
value, or updated to the corresponding current model where backward-compatible
field shapes require a concrete string.

Default, example, development, staging, and production YAML files must agree
with the typed schema. Environment-variable behavior will continue to follow
the existing settings loader; this change will not add unbounded legacy
environment aliases.

## Components and Data Flow

### Central routing policy

A pure policy module will own:

- Provider and role types.
- Default role-to-model mappings.
- Validation for complete Anthropic and OpenAI mappings.
- Resolution precedence.
- Structured resolution results.
- Helpers for identifying Claude 5 request constraints.

The module will not instantiate SDK clients or make network calls.

### Workflow consumers

Consumers will request a role instead of embedding a provider-specific model:

1. The workflow identifies its existing semantic role.
2. The workflow passes provider, workload role, and any explicit override to
   the resolver.
3. The resolver applies precedence and returns one model ID.
4. The provider factory creates the client with that model.

Existing public request shapes remain compatible. A selected model from the
frontend or API is passed as an explicit override, not reclassified.

### Frontend model metadata

The chat model list will show Sonnet 5, Opus 5, GPT-5.6 Terra, and GPT-5.6 Sol
with gateway IDs that map directly and unambiguously to backend IDs. Sonnet 5
becomes the default visible chat model. The picker remains available, and its
cookie continues to preserve a user's explicit choice.

Old entries may remain only if they are intentionally supported as manual
choices and have accurate labels and mappings. Incorrect combinations such as
an Opus 4.5 gateway ID displayed as Opus 4.6 will be removed.

## Claude 5 Runtime Compatibility

Claude Sonnet 5 and Opus 5 require adaptive thinking behavior:

- Do not send manual `thinking: {type: "enabled", budget_tokens: ...}`.
- Use adaptive thinking when thinking is enabled.
- Use `thinking: {type: "disabled"}` when a caller explicitly disables it.
- Do not send non-default `temperature`, `top_p`, or `top_k`.
- Revisit `max_tokens` handling because thinking tokens and visible output
  share the output limit.

The Anthropic provider will apply these rules only to models whose capabilities
require them. Older manually selected Claude models retain their compatible
request behavior.

OpenAI GPT-5.6 models will use the existing OpenAI provider path. Model support
lists and recommended mappings will be updated to Terra and Sol. Reasoning
effort is not inferred from the workload role in this change; existing explicit
effort settings remain authoritative.

## Error Handling

- Unknown provider or workload roles fail during configuration validation or
  model resolution with a clear message.
- Explicit user model IDs are preserved even when they are not automatic
  defaults; provider/API errors are surfaced normally rather than silently
  replacing the selection.
- Invalid Claude 5 sampling or manual-thinking combinations are normalized
  before the SDK call when produced by NEOS configuration.
- Callers that explicitly attempt an unsupported Claude 5 parameter receive a
  clear local validation error rather than an opaque upstream 400 where the
  distinction can be made safely.
- No cross-provider fallback occurs after an API error.

## Testing

Unit tests will verify:

- All four provider/role mappings.
- Resolution precedence for user selection, stored conversation choice,
  deployment override, and automatic role default.
- Unknown provider and role failures.
- Role assignments for chat, coding, recursive planning, and each deep-analysis
  stage.
- Claude 5 adaptive-thinking construction.
- Removal or rejection of unsupported Claude 5 sampling parameters.
- Preservation of older manually selected Claude request behavior.
- Provider model support lists and recommended model mappings.
- Frontend default, picker labels, and gateway-to-backend mappings.

Focused backend and frontend source tests will run before the broader affected
test suites. Tests must not require live Anthropic or OpenAI credentials.

## Rollout and Observability

Structured logs will record provider, role, selected model, and resolution
source. They will distinguish automatic defaults from user and deployment
overrides.

The change will be deployed through the normal environment profiles. Because
no automatic fallback is introduced, unavailable account access to a new model
will surface immediately during staging verification instead of silently
running an older model.

Existing conversations keep their stored explicit model. New conversations
without a model selection use the everyday default.

## Success Criteria

- New automatic Anthropic work uses Sonnet 5 for everyday roles and Opus 5 for
  powerful roles.
- New automatic OpenAI work uses GPT-5.6 Terra for everyday roles and GPT-5.6
  Sol for powerful roles.
- A user-selected model is never replaced by role-based routing.
- Claude 5 calls do not send unsupported manual-thinking or sampling
  parameters.
- The frontend shows accurate names and IDs.
- Configuration and routing tests pass without live API calls.

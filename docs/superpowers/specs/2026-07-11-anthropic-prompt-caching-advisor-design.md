# Anthropic Prompt Caching and Advisor Tool Design

**Date:** 2026-07-11  
**Status:** Approved for implementation planning

## Summary

NEOS will actively use Anthropic prompt caching where requests have a stable,
reusable prefix. Prompt caching will be enabled by default for multi-turn chat,
tool-enabled chat, and contextual document retrieval. It will not be applied
indiscriminately to one-off prompts where a cache write is unlikely to be read.

The Anthropic Advisor tool will be available behind typed configuration and
disabled by default. The first implementation will inject it only into the
multi-round tool-search loop, which can preserve server-tool blocks and resume
`pause_turn` responses correctly. Enabling Advisor will not change unrelated
single-turn or artifact-generation requests.

Primary references:

- [Anthropic prompt caching](https://platform.claude.com/docs/ko/build-with-claude/prompt-caching)
- [Anthropic Advisor tool](https://platform.claude.com/docs/ko/agents-and-tools/tool-use/advisor-tool)

## Goals

- Reduce repeated Anthropic input cost and time-to-first-token for growing
  conversations, stable tool definitions, and repeated document context.
- Make prompt caching the default on eligible NEOS conversational paths.
- Make Advisor injection an explicit, typed, default-off configuration choice.
- Support the Advisor beta protocol correctly, including beta routing,
  server-tool content preservation, and `pause_turn` continuation.
- Preserve correct token and cost accounting for uncached input, cache writes,
  cache reads, executor iterations, and Advisor iterations.
- Keep existing behavior unchanged when Advisor is disabled.

## Non-goals

- Adding Advisor to every LLM call in NEOS.
- Caching unique, single-turn prompts solely because they exceed the model's
  minimum cacheable token count.
- Refactoring the standard artifact-tool stream into a general client-tool
  continuation loop.
- Persisting raw Advisor guidance in a new database table.
- Changing the default chat model as part of this feature.

## Considered Approaches

### 1. Global unconditional injection

Apply top-level cache control and Advisor to every Anthropic request. This has
the smallest policy surface but creates cache writes for prompts that are never
reused, introduces Advisor into unsuitable single-turn work, and exposes paths
without server-tool continuation support to beta response blocks.

### 2. Central Anthropic runtime policy with targeted application

Create reusable request-policy helpers and apply them to paths with known reuse
or complete server-tool semantics. This keeps configuration, compatibility,
usage accounting, and content serialization consistent while avoiding
predictably wasteful cache writes. This is the selected approach.

### 3. Local changes only in `ChatLLMService`

Patch the two chat methods directly. This is initially small, but it leaves
contextual retrieval, configuration validation, usage accounting, and future
Anthropic integrations with different feature logic.

## Configuration

The typed configuration will be nested below `llm`:

```yaml
llm:
  prompt_caching:
    enabled: true
    ttl: 5m

  advisor:
    enabled: false
    model: claude-opus-4-8
    max_uses: 2
    max_tokens: 2048
    max_pause_turns: 3
    prompt_caching:
      enabled: false
      ttl: 5m
```

Validation rules:

- Cache TTL is `5m` or `1h`.
- `advisor.max_uses` is at least 1.
- `advisor.max_tokens` is at least 1024.
- `advisor.max_pause_turns` is non-negative.
- Advisor remains disabled by default because it is beta, has separate cost,
  and supports only specific executor/advisor model pairs.
- Advisor-side caching remains disabled by default because the configured
  request cap is two uses, while Anthropic documents an approximate break-even
  at three Advisor calls.

The committed default and example YAML profiles will document these settings.
Legacy uppercase access through `settings` will remain available for the new
fields so existing configuration conventions continue to work.

## Runtime Policy Component

A focused Anthropic runtime-policy module will own pure and testable behavior:

- Build top-level cache control from typed configuration.
- Add an explicit cache breakpoint to the last stable tool definition without
  mutating caller-owned tool dictionaries.
- Build the `advisor_20260301` tool definition.
- Select normal or beta Messages API routing.
- Check the documented executor/advisor compatibility matrix.
- Serialize Anthropic response content blocks without discarding unknown or
  beta block fields.
- Normalize usage into uncached input, cache creation, cache read, output, and
  per-iteration records.

The policy module will not execute network requests. Services remain
responsible for request lifecycle and streaming.

## Prompt Caching Application

### Multi-turn chat

`ChatLLMService.generate_response` and `generate_response_stream` will pass
top-level automatic cache control on Anthropic calls. Automatic caching moves
the cache boundary with the growing conversation and is Anthropic's recommended
starting point for multi-turn chat.

OpenAI and other provider calls remain unchanged.

### Tool-enabled chat

Direct Anthropic tool-stream requests will receive top-level automatic cache
control. When Advisor is disabled, they continue using the stable Messages API.

### Multi-round tool search

The tool-search loop has both stable and changing sections:

1. Copy core tools and the `search_tools` definition.
2. Append Advisor to the stable set only when it is enabled and compatible.
3. Mark the final tool in that stable set with explicit `cache_control`.
4. Append discovered tools after the stable checkpoint.
5. Also use top-level automatic caching for the growing transcript.

The explicit checkpoint preserves the reusable tool prefix when discovered
tools change. The automatic checkpoint handles messages when the full tool set
stays stable. Together they consume no more than two of Anthropic's four cache
breakpoint slots.

### Contextual retrieval

The existing full-document explicit cache breakpoint remains. The scheduling
will change so one chunk request completes before remaining chunk requests are
started concurrently. Anthropic makes a cache entry available only after the
first response begins; this warm-first ordering prevents the initial concurrent
batch from all paying cache-write cost.

### Intentionally uncached paths

Artifact generation, unique deep-analysis JSON calls, and vision requests will
not receive default cache writes in this change. Their request-specific content
normally changes completely, images invalidate message caches, and their stable
system prompts are generally below current model cache thresholds. These paths
can adopt caching later if usage data shows a reusable prefix.

## Advisor Injection and Data Flow

Advisor injection is limited initially to the multi-round tool-search loop.
That loop owns both assistant messages and tool results and can therefore obey
the complete server-tool protocol.

For each tool-search request:

1. Snapshot prompt-cache and Advisor configuration for the full request.
2. Build a copied stable tool prefix.
3. If Advisor is enabled, verify model compatibility.
4. If compatible, append the Advisor definition and route through
   `client.beta.messages` with `advisor-tool-2026-03-01`.
5. Stream executor text and thinking using the existing NEOS events.
6. Keep `server_tool_use` and `advisor_tool_result` internal; do not expose raw
   guidance as user-visible content.
7. Preserve every response content block with a full model dump before an
   internal continuation request.
8. On `pause_turn`, append the unchanged assistant response and resend the same
   messages, tools, and beta setting without adding a user message.
9. On client `tool_use`, execute or synthesize all required tool results, append
   them, and continue the existing loop.

Configuration is not re-read mid-loop. This prevents an Advisor tool from being
removed while its result blocks are still present in the in-memory transcript.

## Compatibility Policy

NEOS will encode the model combinations documented by Anthropic. If Advisor is
enabled for an executor that is known to be incompatible, the request will
continue without Advisor and record a structured skip reason. This protects
existing conversations that still select Claude Sonnet 4.5.

Unknown future model IDs are not assumed compatible. They will be skipped with
an `unknown_executor_model` reason until the compatibility map is updated.

Known-compatible requests that receive a 400 response from the beta API will
not be retried silently without Advisor. A retry could duplicate generated work
or server-side inference cost and would hide an invalid production setting.

## Error Handling

- Invalid configuration fails during Pydantic validation.
- Incompatible or unknown executor models skip Advisor before the API call and
  retain prompt caching.
- `advisor_tool_result_error` stays in the transcript so the executor can
  continue as Anthropic specifies; NEOS records its error code.
- `pause_turn` is resumed up to `advisor.max_pause_turns`. Exceeding the limit
  yields a clear stream error instead of looping indefinitely.
- A beta API 400 is surfaced with configuration context and is not downgraded
  to a non-Advisor retry.
- Cache-ineligible short prompts remain successful. They are classified from
  usage fields rather than treated as errors.
- Content block serialization uses the SDK's complete dump where available so
  Advisor result variants and future beta fields are not truncated.

## Usage and Cost Accounting

Normalized usage will expose:

- `prompt_tokens`: uncached input tokens after the final cache boundary.
- `cache_creation_tokens`: tokens written to cache.
- `cache_read_tokens`: tokens read from cache.
- `total_input_tokens`: the sum of the three input categories.
- `completion_tokens`: executor output tokens.
- `total_tokens`: total input plus executor output.
- Advisor iteration count and per-model input, cache, output, and cost details.

For beta responses, `usage.iterations` is the billing source of truth. Each
`message` iteration is priced with the executor model, and each
`advisor_message` iteration is priced with its declared Advisor model. The
composite `total_cost` includes both. Existing database cache-token fields are
used; Advisor details are stored in message metadata without adding a schema
migration.

Cache status is derived only from usage:

- `hit`: cache-read tokens are greater than zero.
- `write`: no read occurred and cache-creation tokens are greater than zero.
- `miss`: caching was requested but neither field is positive despite an
  otherwise eligible request.
- `ineligible`: the API reports no cache activity and local request context is
  below or unsuitable for known caching use.

## Observability

Completion metadata and structured logs will include:

- Cache status, creation tokens, and read tokens.
- Whether Advisor was configured and whether it was injected.
- A structured Advisor skip reason.
- Advisor call count, model, token usage, error codes, and cost.
- Composite executor-plus-Advisor cost.

Metrics must not include prompt text or raw Advisor guidance.

## Test Strategy

### Configuration tests

- Prompt caching defaults to enabled with `5m` TTL.
- Advisor defaults to disabled.
- Valid TTL and bound values pass; invalid values fail.
- Committed configuration profiles validate.
- Legacy settings aliases resolve new fields.

### Runtime-policy tests

- Cache control is built for enabled 5-minute and 1-hour configurations.
- Disabled cache control produces no request field.
- Tool breakpoint insertion preserves ordering and does not mutate inputs.
- Advisor is injected only when enabled and compatible.
- Compatible, incompatible, and unknown model IDs are classified explicitly.

### Chat and tool-loop tests

- Anthropic multi-turn invoke and stream calls receive automatic cache control.
- Other providers receive no Anthropic parameters.
- Advisor-disabled tool search uses the stable Messages API with no Advisor
  tool or beta header.
- Advisor-enabled compatible tool search uses the beta API and correct tool.
- `pause_turn` preserves complete content blocks and resends unchanged tools
  and betas.
- The pause limit terminates deterministically.
- Advisor result errors remain in the continuation transcript.

### Usage and cost tests

- Total input equals uncached plus cache-created plus cache-read tokens.
- Existing non-cached usage remains backward compatible.
- Executor and Advisor iteration costs use their respective model prices.
- Composite total cost includes Advisor cost exactly once.

### Contextual retrieval tests

- The first request completes before remaining concurrent calls start.
- Fallback behavior and result ordering remain unchanged.
- Cache usage is read from Anthropic usage fields.

### Regression verification

- Focused config, cost, chat service, tool-search, and contextual retrieval
  tests pass.
- Existing broader backend tests covering the edited modules pass.
- No live Anthropic credentials are required for automated tests.

## Acceptance Criteria

- Existing configuration changes only prompt-caching behavior; no Advisor field
  appears in an API request until `llm.advisor.enabled` is true.
- Eligible multi-turn chat requests include top-level automatic cache control.
- Tool search preserves a stable explicit tool prefix and growing-message cache.
- Contextual retrieval warms its document cache before parallel fan-out.
- Compatible Advisor requests use the beta endpoint and survive `pause_turn`.
- Incompatible models continue without Advisor and expose the skip reason.
- Cache and Advisor token usage are visible and costed correctly.
- All new and relevant regression tests pass.

## Rollout

Prompt caching ships enabled with a five-minute TTL. Operators can change the
TTL to one hour after evaluating reuse intervals and write cost.

Advisor ships disabled. Initial evaluation should enable it in a non-production
profile with a compatible executor, inspect invocation frequency, latency,
quality, and `usage.iterations`, and only then enable it for selected production
deployments. Advisor-side caching should be enabled only when observed requests
regularly make at least three Advisor calls.

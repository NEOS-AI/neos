# Role-Based Model Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route automatic NEOS workloads to Claude Sonnet 5/GPT-5.6 Terra for everyday work and Claude Opus 5/GPT-5.6 Sol for powerful work while preserving every explicit user model choice.

**Architecture:** Add a pure central resolver that maps provider and workload role to a configured model and records why that model won. Existing chat and workflow boundaries pass semantic roles or explicit overrides into the resolver. Provider adapters separately normalize Claude 5 request parameters so routing policy stays independent of SDK behavior.

**Tech Stack:** Python 3.12, Pydantic 2, PyYAML, pytest, TypeScript, Node test runner, LangChain Anthropic/OpenAI, Anthropic/OpenAI async SDKs

## Global Constraints

- Resolution precedence is user request, stored conversation choice, deployment/feature override, then automatic role default.
- Anthropic mappings are exactly `everyday=claude-sonnet-5` and `powerful=claude-opus-5`.
- OpenAI mappings are exactly `everyday=gpt-5.6-terra` and `powerful=gpt-5.6-sol`.
- Existing conversations keep their stored model.
- Do not add cross-provider fallback as part of routing.
- Claude 5 calls use adaptive thinking and omit non-default sampling parameters.
- Tests must not require live provider credentials.
- Preserve unrelated changes in `.env.template` and the existing untracked July 11 documents.

---

## File Map

- Create `neos/config/model_routing.py`: pure provider/role resolution and Claude 5 capability predicates.
- Create `tests/config/test_model_routing.py`: resolver mapping, precedence, and validation tests.
- Modify `neos/config/schema.py`: typed `model_routing` configuration and current role defaults.
- Modify `config/neos.{default,development,staging,production,example}.yaml`: committed routing maps and aligned feature defaults.
- Modify `neos/providers/anthropic.py`: Claude 5 model catalog and request normalization.
- Modify `neos/providers/openai.py`: GPT-5.6 model catalog.
- Modify `neos/utils/llm_factory.py`: current recommendations and role-aware default resolution.
- Modify `neos/workflow/deep_analysis/llm.py`: Claude 5 direct-SDK request normalization.
- Create `tests/providers/test_current_model_providers.py`: provider catalogs and Claude 5 construction tests.
- Modify `tests/workflow/deep_analysis/test_llm.py`: direct Anthropic Claude 5 payload tests.
- Modify `neos/services/chat_llm_service.py`: everyday default through the resolver.
- Modify `neos/api/models/chat_models.py`, `neos/api/services/chat_service.py`, and `neos/database/repositories/chat_repository.py`: make new-conversation defaults resolve to everyday without overwriting supplied/stored choices.
- Modify `neos/config/model_config.py` and `neos/config/models.yaml`: legacy model-config compatibility.
- Modify `neos/workflow/recursive/planner.py`: powerful planner selection through routing policy while retaining explicit config.
- Modify `neos/workflow/deep_analysis/service.py`, `worker.py`, `orchestrator.py`,
  and `synthesizer.py`: resolve scout/judge as everyday and dig/synth as
  powerful, with nullable feature overrides.
- Modify `neos/coding/loop/anthropic.py`: resolve the routine coding executor
  as everyday, with a nullable feature override.
- Modify `neos/utils/cost_calculator.py` and `tests/test_cost_calculator.py`: official current pricing.
- Modify `web/lib/ai/models.ts`: accurate current picker entries and backend mappings.
- Create `web/tests/source/ai-models.test.ts`: frontend model metadata regression tests.

---

### Task 1: Central Model Routing Contract

**Files:**
- Create: `tests/config/test_model_routing.py`
- Create: `neos/config/model_routing.py`
- Modify: `neos/config/schema.py`
- Modify: `tests/config/test_config_schema.py`
- Modify: `tests/config/test_config_files.py`

**Interfaces:**
- Produces: `ModelProvider = Literal["anthropic", "openai"]`
- Produces: `WorkloadRole = Literal["everyday", "powerful"]`
- Produces: `ResolutionSource` enum with `user`, `conversation`, `feature_override`, and `role_default`
- Produces: frozen `ModelResolution(model: str, provider: ModelProvider, role: WorkloadRole, source: ResolutionSource)`
- Produces: `resolve_model(*, config: ModelRoutingConfig, provider: ModelProvider, role: WorkloadRole, user_model: str | None = None, conversation_model: str | None = None, feature_override: str | None = None) -> ModelResolution`
- Produces: `is_claude_5(model: str) -> bool`

- [ ] **Step 1: Write failing resolver tests**

Add tests that assert all four exact mappings and precedence:

```python
def test_role_defaults_map_to_current_models() -> None:
    config = ModelRoutingConfig()
    assert resolve_model(config=config, provider="anthropic", role="everyday").model == "claude-sonnet-5"
    assert resolve_model(config=config, provider="anthropic", role="powerful").model == "claude-opus-5"
    assert resolve_model(config=config, provider="openai", role="everyday").model == "gpt-5.6-terra"
    assert resolve_model(config=config, provider="openai", role="powerful").model == "gpt-5.6-sol"


def test_explicit_selection_precedence_is_stable() -> None:
    result = resolve_model(
        config=ModelRoutingConfig(),
        provider="anthropic",
        role="powerful",
        user_model="claude-sonnet-4-6",
        conversation_model="claude-opus-4-8",
        feature_override="claude-opus-5",
    )
    assert result.model == "claude-sonnet-4-6"
    assert result.source is ResolutionSource.USER
```

Also cover conversation-over-feature, feature-over-role, unknown provider/role validation, incomplete mappings, and exact Claude 5 detection.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
pytest -q tests/config/test_model_routing.py tests/config/test_config_schema.py tests/config/test_config_files.py
```

Expected: collection/import failure because the routing types do not exist.

- [ ] **Step 3: Implement typed configuration and pure resolution**

Add nested strict Pydantic models:

```python
class ProviderModelRolesConfig(StrictConfigModel):
    everyday: str
    powerful: str


class ModelRoutingConfig(StrictConfigModel):
    anthropic: ProviderModelRolesConfig = Field(
        default_factory=lambda: ProviderModelRolesConfig(
            everyday="claude-sonnet-5",
            powerful="claude-opus-5",
        )
    )
    openai: ProviderModelRolesConfig = Field(
        default_factory=lambda: ProviderModelRolesConfig(
            everyday="gpt-5.6-terra",
            powerful="gpt-5.6-sol",
        )
    )
```

Attach `model_routing` to `AppConfig`. Implement the frozen resolution record
and choose the first non-empty override in the documented precedence order.
Do not infer or switch providers from a model string inside this pure resolver.

- [ ] **Step 4: Verify GREEN**

Run the Task 1 pytest command and expect all tests to pass.

- [ ] **Step 5: Commit**

```bash
git add neos/config/model_routing.py neos/config/schema.py tests/config/test_model_routing.py tests/config/test_config_schema.py tests/config/test_config_files.py
git commit -m "feat: add role-based model resolver"
```

---

### Task 2: Provider Catalogs, Claude 5 Payloads, and Pricing

**Files:**
- Create: `tests/providers/test_current_model_providers.py`
- Modify: `neos/providers/anthropic.py`
- Modify: `neos/providers/openai.py`
- Modify: `neos/utils/llm_factory.py`
- Modify: `neos/workflow/deep_analysis/llm.py`
- Modify: `tests/workflow/deep_analysis/test_llm.py`
- Modify: `neos/utils/cost_calculator.py`
- Modify: `tests/test_cost_calculator.py`

**Interfaces:**
- Consumes: `is_claude_5(model: str) -> bool`
- Produces: `normalize_anthropic_request(model: str, params: dict[str, Any], *, thinking_enabled: bool) -> dict[str, Any]`
- Provider catalogs include all four requested models without removing manually selectable supported legacy models.

- [ ] **Step 1: Write failing provider and payload tests**

Patch `ChatAnthropic` and assert:

```python
provider.create_llm(
    model="claude-sonnet-5",
    temperature=0.7,
    max_tokens=8192,
)
params = chat_anthropic.call_args.kwargs
assert "temperature" not in params
assert params["thinking"] == {"type": "adaptive"}
```

Add a disabled-thinking case expecting `{"type": "disabled"}`, an Opus 5 case,
and a legacy Sonnet 4.5 case that retains the existing compatible temperature
and manual-thinking behavior.

For `deep_analysis.llm._call_provider`, assert the mocked Anthropic Messages API
receives adaptive thinking and no `temperature` for Claude 5. Preserve the
cassette payload shape so existing golden recordings remain addressable.

Assert official per-million-token prices:

```python
assert anthropic["claude-sonnet-5"]["input"] == 3.00
assert anthropic["claude-sonnet-5"]["output"] == 15.00
assert anthropic["claude-opus-5"]["input"] == 5.00
assert anthropic["claude-opus-5"]["output"] == 25.00
assert openai["gpt-5.6-terra"]["input"] == 2.50
assert openai["gpt-5.6-terra"]["output"] == 15.00
assert openai["gpt-5.6-sol"]["input"] == 5.00
assert openai["gpt-5.6-sol"]["output"] == 30.00
```

Use Sonnet 5 standard pricing, not its temporary launch discount.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
pytest -q tests/providers/test_current_model_providers.py tests/workflow/deep_analysis/test_llm.py tests/test_cost_calculator.py
```

Expected: failures for missing catalogs, wrong Claude 5 payload fields, and
missing pricing.

- [ ] **Step 3: Implement minimal provider normalization**

For Claude 5:

```python
params.pop("temperature", None)
params.pop("top_p", None)
params.pop("top_k", None)
params["thinking"] = (
    {"type": "disabled"} if disable_thinking else {"type": "adaptive"}
)
```

Reject a caller-supplied manual `budget_tokens` object with a clear `ValueError`
instead of silently mutating it. Apply the same behavior to the direct
deep-analysis SDK call. Update catalogs, recommendations (`balanced` to
everyday, `powerful` to powerful), and prices.

- [ ] **Step 4: Verify GREEN and run focused regression**

Run:

```bash
pytest -q tests/providers/test_current_model_providers.py tests/workflow/deep_analysis/test_llm.py tests/test_cost_calculator.py tests/test_chat_llm.py
```

Expected: all pass without credentials.

- [ ] **Step 5: Commit**

```bash
git add neos/providers/anthropic.py neos/providers/openai.py neos/utils/llm_factory.py neos/workflow/deep_analysis/llm.py neos/utils/cost_calculator.py tests/providers/test_current_model_providers.py tests/workflow/deep_analysis/test_llm.py tests/test_cost_calculator.py
git commit -m "feat: support Claude 5 and GPT-5.6 providers"
```

---

### Task 3: Backend Role Assignments and Explicit-Choice Preservation

**Files:**
- Create: `tests/services/test_chat_model_resolution.py`
- Modify: `neos/services/chat_llm_service.py`
- Modify: `neos/api/models/chat_models.py`
- Modify: `neos/api/services/chat_service.py`
- Modify: `neos/database/repositories/chat_repository.py`
- Modify: `neos/config/model_config.py`
- Modify: `neos/config/models.yaml`
- Modify: `neos/config/schema.py`
- Modify: `config/neos.default.yaml`
- Modify: `config/neos.development.yaml`
- Modify: `config/neos.staging.yaml`
- Modify: `config/neos.production.yaml`
- Modify: `config/neos.example.yaml`
- Modify: `tests/test_chat_service.py`
- Modify: `tests/config/test_coding_model_config.py`
- Modify: `tests/workflow/routing/test_deep_analysis_routing.py`
- Modify: relevant deep-analysis configuration/default tests

**Interfaces:**
- Consumes: `resolve_model(...) -> ModelResolution`
- Chat request `model_name: str | None`; `None` means automatic everyday routing.
- Stored non-empty conversation model is always passed as `conversation_model`.
- `CodingModelConfig.model`, `RecursiveAgentConfig.planner_model`, and all
  `DeepAnalysisModelsConfig` fields are `str | None`; `None` means role default
  and a string means feature override.

- [ ] **Step 1: Write failing role-assignment and chat-precedence tests**

Cover:

```python
def test_new_chat_without_selection_uses_anthropic_everyday() -> None:
    request = CreateConversationRequest()
    assert request.model_name is None
    assert resolve_new_chat_model(request.model_name) == "claude-sonnet-5"


def test_explicit_chat_model_is_not_replaced() -> None:
    assert resolve_new_chat_model("openai/gpt-4.1") == "openai/gpt-4.1"
```

Assert schema/YAML assignments:

- coding executor resolves `None` as `claude-sonnet-5`
- recursive planner resolves `None` as `claude-opus-5`
- deep-analysis scout resolves `None` as `claude-sonnet-5`
- deep-analysis dig resolves `None` as `claude-opus-5`
- deep-analysis synth resolves `None` as `claude-opus-5`
- deep-analysis judge resolves `None` as `claude-sonnet-5`
- any non-empty feature value wins over the corresponding role

Do not change explicit model strings inside tests whose purpose is to exercise
legacy/manual model behavior.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
pytest -q tests/services/test_chat_model_resolution.py tests/test_chat_service.py tests/config/test_coding_model_config.py tests/config/test_config_files.py tests/workflow/routing/test_deep_analysis_routing.py
```

Expected: failures on old defaults and absent chat resolver behavior.

- [ ] **Step 3: Wire backend consumers to routing roles**

Make request-model and automatic feature defaults optional so omission is
distinguishable from an explicit model. Resolve a concrete model before
repository insertion or provider invocation. When generating a response for
an existing conversation, pass its stored model as the conversation override.

At each internal boundary, resolve once:

```python
dig_model = resolve_model(
    config=settings.config.model_routing,
    provider="anthropic",
    role="powerful",
    feature_override=config.models.dig,
).model
```

Use analogous everyday resolution for scout/judge/coding and powerful
resolution for synth/planner. Do not repeatedly resolve inside token-stream
loops.

Remove automatic feature model strings from committed YAML profiles (or encode
them as `null`) so they do not masquerade as explicit overrides. Align Pydantic
defaults to `None`. Update the legacy
`models.yaml`/`model_config.py` compatibility layer to current Sonnet/Opus
values, without converting vision-specific GPT-4o entries to text defaults.

- [ ] **Step 4: Verify GREEN and affected workflow tests**

Run:

```bash
pytest -q tests/services/test_chat_model_resolution.py tests/test_chat_service.py tests/config/test_coding_model_config.py tests/config/test_config_files.py tests/workflow/routing/test_deep_analysis_routing.py tests/workflow/deep_analysis
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add neos/services/chat_llm_service.py neos/api/models/chat_models.py neos/api/services/chat_service.py neos/database/repositories/chat_repository.py neos/config/model_config.py neos/config/models.yaml neos/config/schema.py neos/coding/loop/anthropic.py neos/workflow/deep_analysis/service.py neos/workflow/deep_analysis/worker.py neos/workflow/deep_analysis/orchestrator.py neos/workflow/deep_analysis/synthesizer.py config/neos.default.yaml config/neos.development.yaml config/neos.staging.yaml config/neos.production.yaml config/neos.example.yaml tests/services/test_chat_model_resolution.py tests/test_chat_service.py tests/config/test_coding_model_config.py tests/workflow/routing/test_deep_analysis_routing.py tests/workflow/deep_analysis
git commit -m "feat: route backend workloads by model role"
```

---

### Task 4: Recursive Planner Uses the Powerful Role

**Files:**
- Create or modify: the existing recursive planner test module located by `rg -l 'RecursivePlanner' tests`
- Modify: `neos/workflow/recursive/planner.py`

**Interfaces:**
- Consumes: `resolve_model(...) -> ModelResolution`
- Root planning uses `powerful`; lower-depth atomization keeps its explicit
  cost-saving model until a separate Haiku policy is designed.

- [ ] **Step 1: Write the failing planner routing test**

```python
def test_root_planner_uses_powerful_anthropic_role(monkeypatch) -> None:
    planner = RecursivePlanner()
    assert planner._select_model(0) == "claude-opus-5"


def test_lower_depth_keeps_configured_atomizer(monkeypatch) -> None:
    planner = RecursivePlanner()
    assert planner._select_model(1) == settings.RECURSIVE_ATOMIZER_MODEL
```

Also test that a configured non-`None` `planner_model` override wins over the
central powerful default.

- [ ] **Step 2: Run the focused test and verify RED**

Run the located recursive planner test module with `pytest -q`.

Expected: root model is still Opus 4.6.

- [ ] **Step 3: Implement role-aware root planning**

Resolve the root model with provider `anthropic`, role `powerful`, and nullable
`planner_model` as `feature_override`. Keep lower-depth Haiku behavior
unchanged.

- [ ] **Step 4: Verify GREEN**

Run the focused test and the recursive workflow test directory.

- [ ] **Step 5: Commit**

```bash
git add neos/workflow/recursive/planner.py tests
git commit -m "feat: use powerful model for recursive planning"
```

Before staging, narrow `tests` to the exact recursive planner test paths shown
by `git diff --name-only`; do not stage unrelated tests.

---

### Task 5: Frontend Model Picker and Mapping

**Files:**
- Create: `web/tests/source/ai-models.test.ts`
- Modify: `web/lib/ai/models.ts`

**Interfaces:**
- Produces: `DEFAULT_CHAT_MODEL = "anthropic/claude-sonnet-5"`
- Gateway/backend mappings:
  - `anthropic/claude-sonnet-5` → `claude-sonnet-5`
  - `anthropic/claude-opus-5` → `claude-opus-5`
  - `openai/gpt-5.6-terra` → `gpt-5.6-terra`
  - `openai/gpt-5.6-sol` → `gpt-5.6-sol`

- [ ] **Step 1: Write failing source tests**

```typescript
test("default chat model is Claude Sonnet 5", () => {
  assert.equal(DEFAULT_CHAT_MODEL, "anthropic/claude-sonnet-5");
});

test("current model labels map to exact backend IDs", () => {
  assert.equal(
    mapToBackendModelName("anthropic/claude-opus-5"),
    "claude-opus-5"
  );
  assert.equal(
    mapToBackendModelName("openai/gpt-5.6-sol"),
    "gpt-5.6-sol"
  );
});
```

Also assert the four picker entries have accurate names/providers and that no
Opus 4.5 ID is labeled Opus 4.6.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
pnpm --dir web exec tsx --test tests/source/ai-models.test.ts
```

Expected: default and mappings still reference older models.

- [ ] **Step 3: Update the curated picker**

Make Sonnet 5 the default, add the four requested entries, and map each gateway
ID exactly. Retain a legacy picker entry only when it is deliberately supported
and correctly labeled.

- [ ] **Step 4: Verify GREEN and frontend source suite**

Run:

```bash
pnpm --dir web exec tsx --test tests/source/ai-models.test.ts
pnpm --dir web test:source
```

Expected: all source tests pass.

- [ ] **Step 5: Commit**

```bash
git add web/lib/ai/models.ts web/tests/source/ai-models.test.ts
git commit -m "feat: expose Claude 5 and GPT-5.6 models"
```

---

### Task 6: Integrated Verification and Documentation Alignment

**Files:**
- Modify only if assertions require alignment: `docs/CONFIGURATION.md`
- Modify only if public examples are stale: `examples/test_model_config.py`
- Test only: all files changed in Tasks 1–5

**Interfaces:**
- No new runtime interface.

- [ ] **Step 1: Scan for stale automatic defaults**

Run:

```bash
rg -n 'claude-sonnet-4-5-20250929|claude-opus-4-5-20251101|claude-sonnet-4-6|claude-opus-4-6|gpt-5-2025-08-07|gpt-5-mini-2025-08-07' neos config web/lib docs/CONFIGURATION.md examples
```

Classify every remaining match as one of: intentional legacy/manual support,
historical documentation, vision-specific configuration, or a missed automatic
default. Fix only missed automatic defaults and current public configuration
examples.

- [ ] **Step 2: Run backend verification**

Run:

```bash
pytest -q tests/config tests/providers tests/services/test_chat_model_resolution.py tests/test_chat_service.py tests/test_chat_llm.py tests/test_cost_calculator.py tests/workflow/deep_analysis tests/workflow/routing
```

Expected: all pass with no live credentials.

- [ ] **Step 3: Run frontend verification**

Run:

```bash
pnpm --dir web test:source
pnpm --dir web exec tsc --noEmit
```

Expected: all pass.

- [ ] **Step 4: Inspect final scope**

Run:

```bash
git diff --check
git status --short
git diff --stat
```

Confirm `.env.template` and pre-existing untracked July 11 documents remain
untouched and unstaged.

- [ ] **Step 5: Commit any documentation-only alignment**

If Task 6 changed current docs/examples:

```bash
git add docs/CONFIGURATION.md examples/test_model_config.py
git commit -m "docs: document current model routing"
```

If neither file changed, skip this commit.

- [ ] **Step 6: Request code review**

Invoke `superpowers:requesting-code-review`, address correctness findings, then
rerun the complete Task 6 verification before claiming completion.

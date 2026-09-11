# Phase 8 — deep-analysis live LLM via coding harness

Phase 7 extracted `iter_model_turn` / `collect_model_turn` and forbade
rewriting `deep_analysis/llm.py`. This phase is that rewrite — live calls
only.

## Must keep

- Public API: `call_llm` / `call_json` / `call_text` / `call_messages`
- Cassette payload keys (`prompt` / `messages` / `max_tokens` / `temperature`)
- Injected SDK fakes (`client.messages.create`, `client.chat.completions.create`)
- Token budget + C3 `tokens_spent` + §A5 (no estimated tokens)
- 1-step coding loop stays out of DA workers and ChannelGateway

## Change

1. `client is None` → `create_coding_model(provider)` + `collect_model_turn`.
   Provider comes from the model catalog (same rule as `_is_anthropic_model`).
2. `client` that already looks like a `CodingModel` (`stream`) uses the harness.
3. Injected Anthropic/OpenAI SDK clients keep the existing `_call_provider` path
   so golden tests do not change.
4. `_record_dataset_call` records the catalog provider, not hardcoded
   `"anthropic"`.
5. OpenAI/Gemini live calls may pass tools through the harness (legacy OpenAI
   SDK path still rejects tools).
6. Missing `ModelCompleted.usage` → `LLMResponse` tokens stay 0 (unprovable).

## Tests

- Injected FakeAnthropic / FakeOpenAI still pass (`test_llm.py`, `test_llm_tools.py`)
- A CodingModel-shaped client is consumed via `collect_model_turn`
- Dataset record provider is `openai` for `gpt-6-astra`
- `import neos.workflow.deep_analysis.llm` does not import `DurableCodingLoop`

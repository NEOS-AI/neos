-- Add Claude Opus 5.5 / GPT-6 Sol / GPT-6 Luna pins to llm_model_pricing.
-- They replace claude-opus-5, gpt-5.6-sol and gpt-5.6-terra (2026-09-24).
-- Old rows are kept -- historical usage still prices against them.
-- Skip a pin if it is already seeded.
--
-- Sources: Anthropic claude-api reference (Opus 5.5), OpenAI pricing/models
-- docs (GPT-6), cross-checked with Vercel AI Gateway /v1/models.
-- OpenAI rates are the short-context (<272K input) tier.

INSERT INTO llm_model_pricing (
    provider, model_name, input_price_per_1m, output_price_per_1m,
    cache_creation_price_per_1m, cache_read_price_per_1m,
    context_window, max_output_tokens, supports_function_calling, supports_vision
)
SELECT
    v.provider,
    v.model_name,
    v.input_price_per_1m,
    v.output_price_per_1m,
    v.cache_creation_price_per_1m,
    v.cache_read_price_per_1m,
    v.context_window,
    v.max_output_tokens,
    v.supports_function_calling,
    v.supports_vision
FROM (
    VALUES
        -- Anthropic Claude Opus 5.5
        ('anthropic', 'claude-opus-5-5', 4.00, 20.00, 5.00, 0.20, 1000000, 128000, TRUE, TRUE),
        -- OpenAI GPT-6 Sol
        ('openai', 'gpt-6-sol', 2.00, 10.00, 2.50, 0.20, 1050000, 128000, TRUE, TRUE),
        -- OpenAI GPT-6 Luna
        ('openai', 'gpt-6-luna', 0.10, 0.50, 0.125, 0.01, 1050000, 128000, TRUE, TRUE)
) AS v(
    provider, model_name, input_price_per_1m, output_price_per_1m,
    cache_creation_price_per_1m, cache_read_price_per_1m,
    context_window, max_output_tokens, supports_function_calling, supports_vision
)
WHERE NOT EXISTS (
    SELECT 1
    FROM llm_model_pricing existing
    WHERE existing.provider = v.provider
      AND existing.model_name = v.model_name
);

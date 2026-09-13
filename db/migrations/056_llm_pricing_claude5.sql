-- Add catalog Claude 5.x / 4.8 pins to llm_model_pricing.
-- Does not delete or replace 4.5 rows. Skip a pin if it is already seeded.

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
        -- Anthropic Claude Sonnet 5
        ('anthropic', 'claude-sonnet-5', 3.00, 15.00, 3.75, 0.30, 200000, 8192, TRUE, TRUE),
        -- Anthropic Claude Opus 5
        ('anthropic', 'claude-opus-5', 5.00, 25.00, 6.25, 0.50, 200000, 8192, TRUE, TRUE),
        -- Anthropic Claude Opus 4.8 (deep-analysis judge)
        ('anthropic', 'claude-opus-4-8', 5.00, 25.00, 6.25, 0.50, 200000, 8192, TRUE, TRUE)
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

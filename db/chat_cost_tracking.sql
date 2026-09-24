-- Chat Cost Tracking Schema Extension
-- 실시간 비용 추적 및 분석을 위한 스키마 확장

-- ============================================================================
-- 1. LLM 모델 가격 테이블
-- ============================================================================
CREATE TABLE IF NOT EXISTS llm_model_pricing (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(50) NOT NULL, -- 'openai', 'anthropic', 'google' 등
    model_name VARCHAR(255) NOT NULL,
    model_version VARCHAR(100),

    -- 가격 정보 (USD per 1M tokens)
    input_price_per_1m DECIMAL(10, 6) NOT NULL, -- 입력 토큰 가격
    output_price_per_1m DECIMAL(10, 6) NOT NULL, -- 출력 토큰 가격

    -- 추가 가격 정보
    cache_creation_price_per_1m DECIMAL(10, 6), -- 캐시 생성 가격 (Anthropic)
    cache_read_price_per_1m DECIMAL(10, 6), -- 캐시 읽기 가격

    -- 모델 특성
    context_window INTEGER, -- 최대 컨텍스트 윈도우
    max_output_tokens INTEGER, -- 최대 출력 토큰
    supports_streaming BOOLEAN DEFAULT TRUE,
    supports_function_calling BOOLEAN DEFAULT FALSE,
    supports_vision BOOLEAN DEFAULT FALSE,

    -- 상태
    is_active BOOLEAN DEFAULT TRUE,
    is_deprecated BOOLEAN DEFAULT FALSE,

    -- 유효 기간
    effective_from TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    effective_until TIMESTAMP,

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 메타데이터
    notes TEXT,
    metadata JSONB DEFAULT '{}',

    UNIQUE(provider, model_name, effective_from)
);

-- ============================================================================
-- 2. 메시지별 비용 추적 테이블
-- ============================================================================
CREATE TABLE IF NOT EXISTS message_costs (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(255) NOT NULL,
    conversation_id VARCHAR(255) NOT NULL,

    -- 모델 정보
    provider VARCHAR(50) NOT NULL,
    model_name VARCHAR(255) NOT NULL,
    model_version VARCHAR(100),

    -- 토큰 사용량
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,

    -- 캐시 토큰 (Anthropic)
    cache_creation_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,

    -- 비용 계산 (USD)
    input_cost DECIMAL(12, 8) NOT NULL DEFAULT 0.0,
    output_cost DECIMAL(12, 8) NOT NULL DEFAULT 0.0,
    cache_creation_cost DECIMAL(12, 8) DEFAULT 0.0,
    cache_read_cost DECIMAL(12, 8) DEFAULT 0.0,
    total_cost DECIMAL(12, 8) NOT NULL DEFAULT 0.0,

    -- 가격 정보 (스냅샷)
    input_price_per_1m DECIMAL(10, 6),
    output_price_per_1m DECIMAL(10, 6),

    -- 실행 정보
    latency_ms INTEGER,
    finish_reason VARCHAR(50), -- 'stop', 'length', 'content_filter', 'tool_calls'

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 메타데이터
    metadata JSONB DEFAULT '{}',

    FOREIGN KEY (message_id) REFERENCES messages(message_id) ON DELETE CASCADE,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

-- ============================================================================
-- 3. 사용자별 비용 집계 테이블
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_cost_summary (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,

    -- 집계 기간
    period_type VARCHAR(20) NOT NULL, -- 'daily', 'weekly', 'monthly', 'yearly'
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,

    -- 사용량 통계
    total_messages INTEGER DEFAULT 0,
    total_conversations INTEGER DEFAULT 0,
    total_prompt_tokens BIGINT DEFAULT 0,
    total_completion_tokens BIGINT DEFAULT 0,
    total_tokens BIGINT DEFAULT 0,

    -- 비용 통계 (USD)
    total_cost DECIMAL(12, 6) DEFAULT 0.0,
    input_cost DECIMAL(12, 6) DEFAULT 0.0,
    output_cost DECIMAL(12, 6) DEFAULT 0.0,

    -- Provider별 분석
    cost_by_provider JSONB DEFAULT '{}', -- {"openai": 10.5, "anthropic": 5.2}
    usage_by_model JSONB DEFAULT '{}', -- {"gpt-4": {"tokens": 10000, "cost": 0.5}}

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE(user_id, period_type, period_start)
);

-- ============================================================================
-- 4. 대화별 실시간 비용 추적 뷰
-- ============================================================================
CREATE OR REPLACE VIEW conversation_cost_summary AS
SELECT
    c.conversation_id,
    c.user_id,
    c.title,
    c.model_name,
    COUNT(DISTINCT mc.message_id) as total_billed_messages,
    SUM(mc.prompt_tokens) as total_prompt_tokens,
    SUM(mc.completion_tokens) as total_completion_tokens,
    SUM(mc.total_tokens) as total_tokens,
    SUM(mc.input_cost) as total_input_cost,
    SUM(mc.output_cost) as total_output_cost,
    SUM(mc.total_cost) as total_cost,
    AVG(mc.latency_ms) as avg_latency_ms,
    c.created_at,
    MAX(mc.created_at) as last_billed_at
FROM conversations c
LEFT JOIN message_costs mc ON c.conversation_id = mc.conversation_id
WHERE c.deleted_at IS NULL
GROUP BY c.conversation_id, c.user_id, c.title, c.model_name, c.created_at;

-- ============================================================================
-- 인덱스 생성
-- ============================================================================

-- llm_model_pricing 인덱스
CREATE INDEX IF NOT EXISTS idx_llm_pricing_provider_model ON llm_model_pricing(provider, model_name);
CREATE INDEX IF NOT EXISTS idx_llm_pricing_active ON llm_model_pricing(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_llm_pricing_effective ON llm_model_pricing(effective_from, effective_until);

-- message_costs 인덱스
CREATE INDEX IF NOT EXISTS idx_message_costs_message_id ON message_costs(message_id);
CREATE INDEX IF NOT EXISTS idx_message_costs_conversation_id ON message_costs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_message_costs_created_at ON message_costs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_message_costs_provider_model ON message_costs(provider, model_name);

-- user_cost_summary 인덱스
CREATE INDEX IF NOT EXISTS idx_user_cost_summary_user_id ON user_cost_summary(user_id);
CREATE INDEX IF NOT EXISTS idx_user_cost_summary_period ON user_cost_summary(period_type, period_start);
CREATE INDEX IF NOT EXISTS idx_user_cost_summary_user_period ON user_cost_summary(user_id, period_type, period_start);

-- ============================================================================
-- 트리거 및 함수
-- ============================================================================

-- 메시지 비용 추가 시 대화 비용 업데이트
CREATE OR REPLACE FUNCTION update_conversation_cost_on_message()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE conversations
    SET
        total_tokens_used = total_tokens_used + COALESCE(NEW.total_tokens, 0),
        total_cost = total_cost + COALESCE(NEW.total_cost, 0),
        updated_at = CURRENT_TIMESTAMP
    WHERE conversation_id = NEW.conversation_id;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_conversation_cost_on_message ON message_costs;
CREATE TRIGGER trigger_update_conversation_cost_on_message
    AFTER INSERT ON message_costs
    FOR EACH ROW
    EXECUTE FUNCTION update_conversation_cost_on_message();

-- 메시지 비용 삭제 시 대화 비용 업데이트
CREATE OR REPLACE FUNCTION update_conversation_cost_on_delete()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE conversations
    SET
        total_tokens_used = GREATEST(total_tokens_used - COALESCE(OLD.total_tokens, 0), 0),
        total_cost = GREATEST(total_cost - COALESCE(OLD.total_cost, 0), 0),
        updated_at = CURRENT_TIMESTAMP
    WHERE conversation_id = OLD.conversation_id;

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_conversation_cost_on_delete ON message_costs;
CREATE TRIGGER trigger_update_conversation_cost_on_delete
    AFTER DELETE ON message_costs
    FOR EACH ROW
    EXECUTE FUNCTION update_conversation_cost_on_delete();

-- llm_model_pricing updated_at 자동 업데이트
CREATE OR REPLACE FUNCTION update_llm_pricing_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_llm_pricing_updated_at ON llm_model_pricing;
CREATE TRIGGER trigger_update_llm_pricing_updated_at
    BEFORE UPDATE ON llm_model_pricing
    FOR EACH ROW
    EXECUTE FUNCTION update_llm_pricing_updated_at();

-- ============================================================================
-- 유틸리티 함수
-- ============================================================================

-- 현재 유효한 모델 가격 조회
CREATE OR REPLACE FUNCTION get_current_model_price(
    p_provider VARCHAR(50),
    p_model_name VARCHAR(255)
)
RETURNS TABLE (
    input_price DECIMAL(10, 6),
    output_price DECIMAL(10, 6),
    cache_creation_price DECIMAL(10, 6),
    cache_read_price DECIMAL(10, 6)
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        input_price_per_1m,
        output_price_per_1m,
        cache_creation_price_per_1m,
        cache_read_price_per_1m
    FROM llm_model_pricing
    WHERE provider = p_provider
      AND model_name = p_model_name
      AND is_active = TRUE
      AND effective_from <= CURRENT_TIMESTAMP
      AND (effective_until IS NULL OR effective_until > CURRENT_TIMESTAMP)
    ORDER BY effective_from DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- 비용 계산 함수
CREATE OR REPLACE FUNCTION calculate_message_cost(
    p_provider VARCHAR(50),
    p_model_name VARCHAR(255),
    p_prompt_tokens INTEGER,
    p_completion_tokens INTEGER,
    p_cache_creation_tokens INTEGER DEFAULT 0,
    p_cache_read_tokens INTEGER DEFAULT 0
)
RETURNS DECIMAL(12, 8) AS $$
DECLARE
    v_input_price DECIMAL(10, 6);
    v_output_price DECIMAL(10, 6);
    v_cache_creation_price DECIMAL(10, 6);
    v_cache_read_price DECIMAL(10, 6);
    v_total_cost DECIMAL(12, 8);
BEGIN
    -- 가격 정보 조회
    SELECT * INTO v_input_price, v_output_price, v_cache_creation_price, v_cache_read_price
    FROM get_current_model_price(p_provider, p_model_name);

    -- 가격 정보가 없으면 0 반환
    IF v_input_price IS NULL THEN
        RETURN 0.0;
    END IF;

    -- 비용 계산
    v_total_cost :=
        (p_prompt_tokens * v_input_price / 1000000.0) +
        (p_completion_tokens * v_output_price / 1000000.0) +
        (COALESCE(p_cache_creation_tokens, 0) * COALESCE(v_cache_creation_price, 0) / 1000000.0) +
        (COALESCE(p_cache_read_tokens, 0) * COALESCE(v_cache_read_price, 0) / 1000000.0);

    RETURN v_total_cost;
END;
$$ LANGUAGE plpgsql;

-- 사용자 비용 집계 업데이트 함수
CREATE OR REPLACE FUNCTION update_user_cost_summary(
    p_user_id VARCHAR(255),
    p_period_type VARCHAR(20) DEFAULT 'daily'
)
RETURNS VOID AS $$
DECLARE
    v_period_start DATE;
    v_period_end DATE;
BEGIN
    -- 기간 계산
    IF p_period_type = 'daily' THEN
        v_period_start := CURRENT_DATE;
        v_period_end := CURRENT_DATE;
    ELSIF p_period_type = 'weekly' THEN
        v_period_start := DATE_TRUNC('week', CURRENT_DATE)::DATE;
        v_period_end := v_period_start + INTERVAL '6 days';
    ELSIF p_period_type = 'monthly' THEN
        v_period_start := DATE_TRUNC('month', CURRENT_DATE)::DATE;
        v_period_end := (DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month - 1 day')::DATE;
    ELSE
        RAISE EXCEPTION 'Invalid period_type: %', p_period_type;
    END IF;

    -- Upsert 집계 데이터
    INSERT INTO user_cost_summary (
        user_id,
        period_type,
        period_start,
        period_end,
        total_messages,
        total_conversations,
        total_prompt_tokens,
        total_completion_tokens,
        total_tokens,
        total_cost,
        input_cost,
        output_cost
    )
    SELECT
        p_user_id,
        p_period_type,
        v_period_start,
        v_period_end,
        COUNT(DISTINCT mc.message_id),
        COUNT(DISTINCT mc.conversation_id),
        SUM(mc.prompt_tokens),
        SUM(mc.completion_tokens),
        SUM(mc.total_tokens),
        SUM(mc.total_cost),
        SUM(mc.input_cost),
        SUM(mc.output_cost)
    FROM message_costs mc
    JOIN conversations c ON mc.conversation_id = c.conversation_id
    WHERE c.user_id = p_user_id
      AND mc.created_at::DATE BETWEEN v_period_start AND v_period_end
    ON CONFLICT (user_id, period_type, period_start)
    DO UPDATE SET
        total_messages = EXCLUDED.total_messages,
        total_conversations = EXCLUDED.total_conversations,
        total_prompt_tokens = EXCLUDED.total_prompt_tokens,
        total_completion_tokens = EXCLUDED.total_completion_tokens,
        total_tokens = EXCLUDED.total_tokens,
        total_cost = EXCLUDED.total_cost,
        input_cost = EXCLUDED.input_cost,
        output_cost = EXCLUDED.output_cost,
        updated_at = CURRENT_TIMESTAMP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 초기 가격 데이터 (2025년 1월 기준)
-- ============================================================================
INSERT INTO llm_model_pricing (
    provider, model_name, input_price_per_1m, output_price_per_1m,
    cache_creation_price_per_1m, cache_read_price_per_1m,
    context_window, max_output_tokens, supports_function_calling, supports_vision
) VALUES
    -- OpenAI GPT-4o
    ('openai', 'gpt-4o', 2.50, 10.00, NULL, NULL, 128000, 16384, TRUE, TRUE),
    ('openai', 'gpt-4o-mini', 0.15, 0.60, NULL, NULL, 128000, 16384, TRUE, TRUE),

    -- OpenAI GPT-4 Turbo
    ('openai', 'gpt-4-turbo', 10.00, 30.00, NULL, NULL, 128000, 4096, TRUE, TRUE),

    -- OpenAI GPT-3.5
    ('openai', 'gpt-3.5-turbo', 0.50, 1.50, NULL, NULL, 16385, 4096, TRUE, FALSE),

    -- Anthropic Claude 4.5 Sonnet
    ('anthropic', 'claude-sonnet-4-5-20250929', 3.00, 15.00, 3.75, 0.30, 200000, 8192, TRUE, TRUE),

    -- Anthropic Claude 4.5 Opus
    ('anthropic', 'claude-opus-4-5-20251101', 15.00, 75.00, 18.75, 1.50, 200000, 4096, TRUE, TRUE),

    -- Anthropic Claude 4.5 Haiku
    ('anthropic', 'claude-haiku-4-5-20251001', 0.25, 1.25, 0.30, 0.03, 200000, 4096, TRUE, TRUE),

    -- Anthropic Claude Sonnet 5
    ('anthropic', 'claude-sonnet-5', 3.00, 15.00, 3.75, 0.30, 200000, 8192, TRUE, TRUE),

    -- Anthropic Claude Opus 5
    ('anthropic', 'claude-opus-5', 5.00, 25.00, 6.25, 0.50, 200000, 8192, TRUE, TRUE),

    -- Anthropic Claude Opus 4.8 (deep-analysis judge)
    ('anthropic', 'claude-opus-4-8', 5.00, 25.00, 6.25, 0.50, 200000, 8192, TRUE, TRUE),

    -- Anthropic Claude Opus 5.5 (replaces claude-opus-5)
    ('anthropic', 'claude-opus-5-5', 4.00, 20.00, 5.00, 0.20, 1000000, 128000, TRUE, TRUE),

    -- OpenAI GPT-6 Sol / Luna (replace gpt-5.6-sol / gpt-5.6-terra)
    ('openai', 'gpt-6-sol', 2.00, 10.00, 2.50, 0.20, 1050000, 128000, TRUE, TRUE),
    ('openai', 'gpt-6-luna', 0.10, 0.50, 0.125, 0.01, 1050000, 128000, TRUE, TRUE)
ON CONFLICT (provider, model_name, effective_from) DO NOTHING;

-- ============================================================================
-- 코멘트 추가
-- ============================================================================
COMMENT ON TABLE llm_model_pricing IS 'LLM 모델별 가격 정보 및 특성';
COMMENT ON TABLE message_costs IS '메시지별 실시간 비용 추적';
COMMENT ON TABLE user_cost_summary IS '사용자별 비용 집계 (일별/주별/월별)';
COMMENT ON VIEW conversation_cost_summary IS '대화별 비용 요약 뷰';

// Curated list of top models from Vercel AI Gateway
export const DEFAULT_CHAT_MODEL = "anthropic/claude-sonnet-5";

export type ChatModel = {
  id: string;
  name: string;
  provider: string;
  description: string;
};

export const chatModels: ChatModel[] = [
  // Anthropic
  {
    id: "anthropic/claude-sonnet-5",
    name: "Claude Sonnet 5",
    provider: "anthropic",
    description: "Best balance of speed, intelligence, and cost",
  },
  {
    id: "anthropic/claude-opus-5",
    name: "Claude Opus 5",
    provider: "anthropic",
    description: "Most capable Anthropic model",
  },
  {
    id: "anthropic/claude-haiku-4.5",
    name: "Claude Haiku 4.5",
    provider: "anthropic",
    description: "Fast and affordable, great for everyday tasks",
  },
  {
    id: "anthropic/claude-sonnet-4.5",
    name: "Claude Sonnet 4.5",
    provider: "anthropic",
    description: "Previous-generation balanced model",
  },
  // OpenAI
  {
    id: "openai/gpt-5.6-terra",
    name: "GPT-5.6 Terra",
    provider: "openai",
    description: "Balanced OpenAI model for everyday tasks",
  },
  {
    id: "openai/gpt-5.6-sol",
    name: "GPT-5.6 Sol",
    provider: "openai",
    description: "Most capable OpenAI model",
  },
  {
    id: "openai/gpt-4o-mini",
    name: "GPT-4o Mini",
    provider: "openai",
    description: "Fast and cost-effective for simple tasks",
  },
  {
    id: "openai/gpt-4o",
    name: "GPT-4o",
    provider: "openai",
    description: "Previous-generation OpenAI model",
  },
  // Reasoning models (extended thinking).
  // The id must keep "thinking"/"reasoning" — lib/ai/prompts.ts branches on it.
  {
    id: "anthropic/claude-sonnet-4.5-thinking",
    name: "Claude Sonnet 4.5 (Thinking)",
    provider: "reasoning",
    description: "Extended thinking for complex problems",
  },
];

// Group models by provider for UI
export const modelsByProvider = chatModels.reduce(
  (acc, model) => {
    if (!acc[model.provider]) {
      acc[model.provider] = [];
    }
    acc[model.provider].push(model);
    return acc;
  },
  {} as Record<string, ChatModel[]>
);

// Map Vercel AI Gateway model IDs to backend model names.
//
// The backend infers its provider from the model name and only recognizes
// "gpt" and "claude"; every other name silently routes to Anthropic and fails
// at request time. So every value here must be an OpenAI or Anthropic model.
const MODEL_MAP: Record<string, string> = {
  // Anthropic
  "anthropic/claude-sonnet-5": "claude-sonnet-5",
  "anthropic/claude-opus-5": "claude-opus-5",
  "anthropic/claude-haiku-4.5": "claude-haiku-4-5-20251001",
  "anthropic/claude-sonnet-4.5": "claude-sonnet-4-5-20250929",
  "anthropic/claude-sonnet-4.5-thinking": "claude-sonnet-4-5-20250929",
  // OpenAI - remove provider prefix
  "openai/gpt-5.6-terra": "gpt-5.6-terra",
  "openai/gpt-5.6-sol": "gpt-5.6-sol",
  "openai/gpt-4o": "gpt-4o",
  "openai/gpt-4o-mini": "gpt-4o-mini",
};

// Retired from the picker but still present in stored `chat-model` cookies.
// The cookie is read verbatim and validated only as z.string(), so dropping an
// entry here would leak the raw gateway ID to the backend.
const RETIRED_MODEL_MAP: Record<string, string> = {
  // Renamed picker entries — keep serving what they always served.
  "openai/gpt-4.1": "gpt-4o",
  "openai/gpt-4.1-mini": "gpt-4o-mini",
  "anthropic/claude-3.7-sonnet-thinking": "claude-sonnet-4-5-20250929",
  // claude-opus-4-6 was retired from the backend catalog (no known price, so
  // its cost aggregated as zero). Serve its replacement.
  "anthropic/claude-opus-4.5": "claude-opus-5",
  // Google and xAI were never servable — the backend has no provider for them,
  // so these selections always failed. Retire them onto the default model.
  "google/gemini-2.5-flash-lite": "claude-sonnet-5",
  "google/gemini-3-pro-preview": "claude-sonnet-5",
  "xai/grok-4.1-fast-non-reasoning": "claude-sonnet-5",
  "xai/grok-code-fast-1-thinking": "claude-sonnet-5",
};

export function mapToBackendModelName(vercelModelId: string): string {
  return (
    MODEL_MAP[vercelModelId] ??
    RETIRED_MODEL_MAP[vercelModelId] ??
    vercelModelId
  );
}

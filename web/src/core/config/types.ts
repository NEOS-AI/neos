export interface ModelConfig {
  basic: string[];
  reasoning: string[];
}

export interface RagConfig {
  provider: string;
}

export interface NeosConfig {
  rag: RagConfig;
  models: ModelConfig;
}

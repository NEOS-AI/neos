/**
 * Type definitions for Analytics Backoffice
 */

export interface AnalysisRun {
  run_id: string;
  name: string;
  description: string | null;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  total_conversations: number;
  processed_conversations: number;
  total_clusters: number;
  progress_percentage: number;
  current_stage: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface Cluster {
  id: string;
  name: string;
  description: string | null;
  level: number;
  path: string;
  conversation_count: number;
  unique_user_count: number;
  keywords: string[] | null;
  top_facets: Record<string, Record<string, number>> | null;
  centroid: { x: number; y: number } | null;
  children: Cluster[];
}

export interface UMAPPoint {
  conversation_id: number;
  x: number;
  y: number;
  cluster_id: number | null;
  task_type: string | null;
  language: string | null;
}

export interface TrendingTopic {
  name: string;
  count: number;
  keywords: string[];
  id: string;
}

export interface FacetDistribution {
  facet: string;
  distribution: Record<string, number>;
}

export interface ConversationFacets {
  conversation_id: number;
  umap_x: number;
  umap_y: number;
  facets: {
    topic: string;
    language: string;
    task_type: string;
    intent: string;
    domain: string;
    complexity: number;
    sentiment: string;
    safety_score: number;
    summary: string;
    keywords: string[];
  };
}

export interface AnalysisStatistics {
  run_id: string;
  status: string;
  total_conversations: number;
  processed_conversations: number;
  total_clusters: number;
  clusters_by_level: Record<string, number>;
  progress: number;
  started_at: string | null;
  completed_at: string | null;
}

export interface CreateAnalysisRequest {
  name: string;
  description?: string;
  start_date?: string;
  end_date?: string;
  facet_types?: string[];
  config?: Record<string, unknown>;
}

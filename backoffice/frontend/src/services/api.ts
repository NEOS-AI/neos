/**
 * API client for Analytics Backoffice
 */

import axios from "axios";
import type {
  AnalysisRun,
  AnalysisStatistics,
  Cluster,
  CreateAnalysisRequest,
  FacetDistribution,
  TrendingTopic,
  UMAPPoint,
} from "@/types";

const api = axios.create({
  baseURL: "/api",
  headers: {
    "Content-Type": "application/json",
  },
});

// Analysis endpoints
export const analysisApi = {
  create: async (data: CreateAnalysisRequest): Promise<AnalysisRun> => {
    const response = await api.post<AnalysisRun>("/analysis", data);
    return response.data;
  },

  list: async (params?: {
    limit?: number;
    offset?: number;
    status?: string;
  }): Promise<AnalysisRun[]> => {
    const response = await api.get<AnalysisRun[]>("/analysis", { params });
    return response.data;
  },

  get: async (runId: string): Promise<AnalysisRun> => {
    const response = await api.get<AnalysisRun>(`/analysis/${runId}`);
    return response.data;
  },

  getStatistics: async (runId: string): Promise<AnalysisStatistics> => {
    const response = await api.get<AnalysisStatistics>(
      `/analysis/${runId}/statistics`
    );
    return response.data;
  },

  delete: async (runId: string): Promise<void> => {
    await api.delete(`/analysis/${runId}`);
  },
};

// Cluster endpoints
export const clusterApi = {
  getHierarchy: async (
    analysisRunId: number,
    maxDepth?: number
  ): Promise<{ hierarchy: Cluster[] }> => {
    const response = await api.get<{ hierarchy: Cluster[] }>(
      `/clusters/hierarchy/${analysisRunId}`,
      { params: { max_depth: maxDepth } }
    );
    return response.data;
  },

  get: async (
    clusterId: string,
    includeChildren?: boolean
  ): Promise<Cluster> => {
    const response = await api.get<Cluster>(`/clusters/${clusterId}`, {
      params: { include_children: includeChildren },
    });
    return response.data;
  },

  getConversations: async (
    clusterId: string,
    params?: { limit?: number; offset?: number; include_facets?: boolean }
  ): Promise<{ conversations: unknown[]; count: number }> => {
    const response = await api.get(`/clusters/${clusterId}/conversations`, {
      params,
    });
    return response.data;
  },

  getUMAP: async (
    analysisRunId: number,
    sampleSize?: number
  ): Promise<{ points: UMAPPoint[]; count: number }> => {
    const response = await api.get<{ points: UMAPPoint[]; count: number }>(
      `/clusters/umap/${analysisRunId}`,
      { params: { sample_size: sampleSize } }
    );
    return response.data;
  },

  getFacetDistribution: async (
    analysisRunId: number,
    facetName: string
  ): Promise<FacetDistribution> => {
    const response = await api.get<FacetDistribution>(
      `/clusters/facets/${analysisRunId}/${facetName}`
    );
    return response.data;
  },

  search: async (
    analysisRunId: number,
    query: string,
    limit?: number
  ): Promise<{ results: Cluster[]; count: number }> => {
    const response = await api.get(`/clusters/search/${analysisRunId}`, {
      params: { q: query, limit },
    });
    return response.data;
  },

  getTrending: async (
    analysisRunId: number,
    limit?: number
  ): Promise<{ topics: TrendingTopic[] }> => {
    const response = await api.get<{ topics: TrendingTopic[] }>(
      `/clusters/trending/${analysisRunId}`,
      { params: { limit } }
    );
    return response.data;
  },

  compare: async (
    clusterIds: string[]
  ): Promise<{ clusters: unknown[]; facet_comparison: unknown }> => {
    const response = await api.post("/clusters/compare", {
      cluster_ids: clusterIds,
    });
    return response.data;
  },
};

// Health check
export const healthApi = {
  check: async (): Promise<{ status: string; app_name: string; version: string }> => {
    const response = await api.get("/health");
    return response.data;
  },
};

export default api;

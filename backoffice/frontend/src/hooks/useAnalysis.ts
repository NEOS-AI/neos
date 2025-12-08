/**
 * React hooks for analysis data
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { analysisApi, clusterApi } from "@/services/api";
import type { CreateAnalysisRequest } from "@/types";

export function useAnalysisRuns(status?: string) {
  return useQuery({
    queryKey: ["analysisRuns", status],
    queryFn: () => analysisApi.list({ status }),
    refetchInterval: 5000, // Poll every 5 seconds for running analyses
  });
}

export function useAnalysisRun(runId: string | null) {
  return useQuery({
    queryKey: ["analysisRun", runId],
    queryFn: () => (runId ? analysisApi.get(runId) : null),
    enabled: !!runId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data?.status === "running") {
        return 2000; // Poll every 2 seconds when running
      }
      return false;
    },
  });
}

export function useAnalysisStatistics(runId: string | null) {
  return useQuery({
    queryKey: ["analysisStatistics", runId],
    queryFn: () => (runId ? analysisApi.getStatistics(runId) : null),
    enabled: !!runId,
  });
}

export function useCreateAnalysis() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateAnalysisRequest) => analysisApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["analysisRuns"] });
    },
  });
}

export function useDeleteAnalysis() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (runId: string) => analysisApi.delete(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["analysisRuns"] });
    },
  });
}

export function useClusterHierarchy(analysisRunId: number | null) {
  return useQuery({
    queryKey: ["clusterHierarchy", analysisRunId],
    queryFn: () =>
      analysisRunId ? clusterApi.getHierarchy(analysisRunId) : null,
    enabled: !!analysisRunId,
  });
}

export function useUMAPData(analysisRunId: number | null, sampleSize?: number) {
  return useQuery({
    queryKey: ["umapData", analysisRunId, sampleSize],
    queryFn: () =>
      analysisRunId ? clusterApi.getUMAP(analysisRunId, sampleSize) : null,
    enabled: !!analysisRunId,
  });
}

export function useTrendingTopics(analysisRunId: number | null, limit?: number) {
  return useQuery({
    queryKey: ["trendingTopics", analysisRunId, limit],
    queryFn: () =>
      analysisRunId ? clusterApi.getTrending(analysisRunId, limit) : null,
    enabled: !!analysisRunId,
  });
}

export function useFacetDistribution(
  analysisRunId: number | null,
  facetName: string
) {
  return useQuery({
    queryKey: ["facetDistribution", analysisRunId, facetName],
    queryFn: () =>
      analysisRunId
        ? clusterApi.getFacetDistribution(analysisRunId, facetName)
        : null,
    enabled: !!analysisRunId,
  });
}

export function useClusterSearch(
  analysisRunId: number | null,
  query: string,
  limit?: number
) {
  return useQuery({
    queryKey: ["clusterSearch", analysisRunId, query, limit],
    queryFn: () =>
      analysisRunId && query
        ? clusterApi.search(analysisRunId, query, limit)
        : null,
    enabled: !!analysisRunId && query.length >= 2,
  });
}

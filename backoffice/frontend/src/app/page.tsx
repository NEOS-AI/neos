"use client";

import { useState } from "react";
import {
  BarChart3,
  Plus,
  Search,
  TrendingUp,
  Users,
  MessageSquare,
  Layers,
} from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { AnalysisCard } from "@/components/analysis/AnalysisCard";
import { CreateAnalysisModal } from "@/components/analysis/CreateAnalysisModal";
import { ClusterTree } from "@/components/clusters/ClusterTree";
import { ClusterDetail } from "@/components/clusters/ClusterDetail";
import { UMAPScatter } from "@/components/visualization/UMAPScatter";
import { FacetChart } from "@/components/visualization/FacetChart";
import {
  useAnalysisRuns,
  useCreateAnalysis,
  useDeleteAnalysis,
  useClusterHierarchy,
  useUMAPData,
  useTrendingTopics,
  useFacetDistribution,
} from "@/hooks/useAnalysis";
import type { AnalysisRun, Cluster, CreateAnalysisRequest } from "@/types";

export default function Home() {
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [selectedAnalysis, setSelectedAnalysis] = useState<AnalysisRun | null>(
    null
  );
  const [selectedCluster, setSelectedCluster] = useState<Cluster | null>(null);
  const [colorBy, setColorBy] = useState<"task_type" | "language" | "cluster_id">(
    "task_type"
  );

  const { data: analysisRuns, isLoading: isLoadingRuns } = useAnalysisRuns();
  const createAnalysis = useCreateAnalysis();
  const deleteAnalysis = useDeleteAnalysis();

  // Derive analysis run ID from selected analysis
  // Note: In a real app, you'd need to map run_id to the database id
  const analysisRunId = selectedAnalysis?.status === "completed" ? 1 : null;

  const { data: hierarchyData } = useClusterHierarchy(analysisRunId);
  const { data: umapData } = useUMAPData(analysisRunId);
  const { data: trendingData } = useTrendingTopics(analysisRunId);
  const { data: taskTypeData } = useFacetDistribution(analysisRunId, "task_type");

  const handleCreateAnalysis = async (data: CreateAnalysisRequest) => {
    await createAnalysis.mutateAsync(data);
    setIsCreateModalOpen(false);
  };

  const handleDeleteAnalysis = async (analysis: AnalysisRun) => {
    if (confirm(`Delete "${analysis.name}"?`)) {
      await deleteAnalysis.mutateAsync(analysis.run_id);
      if (selectedAnalysis?.run_id === analysis.run_id) {
        setSelectedAnalysis(null);
      }
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-3">
              <BarChart3 className="w-8 h-8 text-primary-600" />
              <h1 className="text-xl font-bold text-gray-900">
                Analytics Backoffice
              </h1>
            </div>

            <div className="flex items-center gap-4">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search clusters..."
                  className="pl-9 pr-4 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 w-64"
                />
              </div>
              <Button
                icon={<Plus className="w-4 h-4" />}
                onClick={() => setIsCreateModalOpen(true)}
              >
                New Analysis
              </Button>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Stats Overview */}
        {selectedAnalysis?.status === "completed" && (
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
            <Card className="!p-4">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-blue-100 rounded-lg">
                  <MessageSquare className="w-5 h-5 text-blue-600" />
                </div>
                <div>
                  <p className="text-sm text-gray-500">Conversations</p>
                  <p className="text-2xl font-bold">
                    {selectedAnalysis.total_conversations.toLocaleString()}
                  </p>
                </div>
              </div>
            </Card>
            <Card className="!p-4">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-green-100 rounded-lg">
                  <Layers className="w-5 h-5 text-green-600" />
                </div>
                <div>
                  <p className="text-sm text-gray-500">Clusters</p>
                  <p className="text-2xl font-bold">
                    {selectedAnalysis.total_clusters.toLocaleString()}
                  </p>
                </div>
              </div>
            </Card>
            <Card className="!p-4">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-purple-100 rounded-lg">
                  <Users className="w-5 h-5 text-purple-600" />
                </div>
                <div>
                  <p className="text-sm text-gray-500">Unique Users</p>
                  <p className="text-2xl font-bold">-</p>
                </div>
              </div>
            </Card>
            <Card className="!p-4">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-orange-100 rounded-lg">
                  <TrendingUp className="w-5 h-5 text-orange-600" />
                </div>
                <div>
                  <p className="text-sm text-gray-500">Top Topic</p>
                  <p className="text-lg font-bold truncate">
                    {trendingData?.topics?.[0]?.name || "-"}
                  </p>
                </div>
              </div>
            </Card>
          </div>
        )}

        <div className="grid grid-cols-12 gap-6">
          {/* Analysis List Sidebar */}
          <div className="col-span-12 lg:col-span-3">
            <Card title="Analysis Runs" className="h-fit">
              {isLoadingRuns ? (
                <div className="text-center py-8 text-gray-500">Loading...</div>
              ) : !analysisRuns?.length ? (
                <div className="text-center py-8 text-gray-500">
                  <p>No analyses yet</p>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-2"
                    onClick={() => setIsCreateModalOpen(true)}
                  >
                    Create your first
                  </Button>
                </div>
              ) : (
                <div className="space-y-3">
                  {analysisRuns.map((analysis) => (
                    <AnalysisCard
                      key={analysis.run_id}
                      analysis={analysis}
                      selected={selectedAnalysis?.run_id === analysis.run_id}
                      onSelect={setSelectedAnalysis}
                      onDelete={handleDeleteAnalysis}
                    />
                  ))}
                </div>
              )}
            </Card>
          </div>

          {/* Main Content */}
          <div className="col-span-12 lg:col-span-9 space-y-6">
            {!selectedAnalysis ? (
              <Card className="text-center py-16">
                <BarChart3 className="w-16 h-16 text-gray-300 mx-auto mb-4" />
                <h2 className="text-xl font-semibold text-gray-700 mb-2">
                  Select an Analysis
                </h2>
                <p className="text-gray-500 mb-4">
                  Choose an analysis from the sidebar or create a new one
                </p>
                <Button onClick={() => setIsCreateModalOpen(true)}>
                  Create New Analysis
                </Button>
              </Card>
            ) : selectedAnalysis.status !== "completed" ? (
              <Card className="text-center py-16">
                <div className="animate-pulse">
                  <div className="w-16 h-16 bg-primary-100 rounded-full mx-auto mb-4 flex items-center justify-center">
                    <BarChart3 className="w-8 h-8 text-primary-500" />
                  </div>
                </div>
                <h2 className="text-xl font-semibold text-gray-700 mb-2">
                  Analysis in Progress
                </h2>
                <p className="text-gray-500 mb-2">
                  {selectedAnalysis.current_stage || "Processing..."}
                </p>
                <div className="max-w-xs mx-auto">
                  <div className="flex items-center justify-between text-sm mb-1">
                    <span className="text-gray-500">Progress</span>
                    <span className="font-medium">
                      {Math.round(selectedAnalysis.progress_percentage)}%
                    </span>
                  </div>
                  <div className="w-full bg-gray-100 rounded-full h-2">
                    <div
                      className="bg-primary-500 rounded-full h-2 transition-all"
                      style={{
                        width: `${selectedAnalysis.progress_percentage}%`,
                      }}
                    />
                  </div>
                </div>
              </Card>
            ) : (
              <>
                {/* UMAP Visualization */}
                <Card
                  title="Conversation Space"
                  subtitle="UMAP projection of conversation embeddings"
                  actions={
                    <select
                      value={colorBy}
                      onChange={(e) =>
                        setColorBy(
                          e.target.value as "task_type" | "language" | "cluster_id"
                        )
                      }
                      className="text-sm border border-gray-300 rounded-lg px-3 py-1.5"
                    >
                      <option value="task_type">Color by Task Type</option>
                      <option value="language">Color by Language</option>
                      <option value="cluster_id">Color by Cluster</option>
                    </select>
                  }
                >
                  <UMAPScatter
                    points={umapData?.points || []}
                    colorBy={colorBy}
                    height={400}
                  />
                </Card>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {/* Cluster Tree */}
                  <Card
                    title="Cluster Hierarchy"
                    subtitle="Browse clusters by topic"
                  >
                    <div className="max-h-96 overflow-y-auto">
                      <ClusterTree
                        clusters={hierarchyData?.hierarchy || []}
                        selectedClusterId={selectedCluster?.id}
                        onSelectCluster={setSelectedCluster}
                      />
                    </div>
                  </Card>

                  {/* Facet Distribution */}
                  <Card
                    title="Task Type Distribution"
                    subtitle="How users are using the system"
                  >
                    {taskTypeData ? (
                      <FacetChart data={taskTypeData} chartType="donut" />
                    ) : (
                      <div className="flex items-center justify-center h-64 text-gray-500">
                        No data available
                      </div>
                    )}
                  </Card>
                </div>

                {/* Cluster Detail */}
                {selectedCluster && (
                  <ClusterDetail cluster={selectedCluster} />
                )}

                {/* Trending Topics */}
                {trendingData?.topics && trendingData.topics.length > 0 && (
                  <Card
                    title="Trending Topics"
                    subtitle="Most common conversation topics"
                  >
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                      {trendingData.topics.map((topic, index) => (
                        <div
                          key={topic.id}
                          className="p-4 bg-gray-50 rounded-lg"
                        >
                          <div className="flex items-center gap-2 mb-2">
                            <span className="text-lg font-bold text-primary-600">
                              #{index + 1}
                            </span>
                          </div>
                          <p className="font-medium text-gray-900 truncate">
                            {topic.name}
                          </p>
                          <p className="text-sm text-gray-500">
                            {topic.count.toLocaleString()} conversations
                          </p>
                        </div>
                      ))}
                    </div>
                  </Card>
                )}
              </>
            )}
          </div>
        </div>
      </main>

      {/* Create Analysis Modal */}
      <CreateAnalysisModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        onSubmit={handleCreateAnalysis}
        isLoading={createAnalysis.isPending}
      />
    </div>
  );
}

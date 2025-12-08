"use client";

import { Card } from "@/components/ui/Card";
import type { Cluster } from "@/types";

interface ClusterDetailProps {
  cluster: Cluster;
}

export function ClusterDetail({ cluster }: ClusterDetailProps) {
  return (
    <div className="space-y-6">
      <Card>
        <div className="space-y-4">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">
              {cluster.name}
            </h2>
            {cluster.description && (
              <p className="text-gray-600 mt-1">{cluster.description}</p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="bg-gray-50 rounded-lg p-4">
              <p className="text-sm text-gray-500">Conversations</p>
              <p className="text-2xl font-semibold text-gray-900">
                {cluster.conversation_count.toLocaleString()}
              </p>
            </div>
            <div className="bg-gray-50 rounded-lg p-4">
              <p className="text-sm text-gray-500">Unique Users</p>
              <p className="text-2xl font-semibold text-gray-900">
                {cluster.unique_user_count.toLocaleString()}
              </p>
            </div>
          </div>

          {cluster.keywords && cluster.keywords.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-gray-700 mb-2">
                Keywords
              </h4>
              <div className="flex flex-wrap gap-2">
                {cluster.keywords.map((keyword, i) => (
                  <span
                    key={i}
                    className="px-2 py-1 text-sm bg-primary-100 text-primary-700 rounded-full"
                  >
                    {keyword}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </Card>

      {cluster.top_facets && (
        <Card title="Facet Distribution">
          <div className="space-y-4">
            {Object.entries(cluster.top_facets).map(
              ([facetName, distribution]) => (
                <div key={facetName}>
                  <h4 className="text-sm font-medium text-gray-700 mb-2 capitalize">
                    {facetName.replace("_", " ")}
                  </h4>
                  <div className="space-y-1">
                    {Object.entries(distribution)
                      .sort(([, a], [, b]) => b - a)
                      .slice(0, 5)
                      .map(([value, count]) => {
                        const total = Object.values(distribution).reduce(
                          (sum, c) => sum + c,
                          0
                        );
                        const percentage = Math.round((count / total) * 100);
                        return (
                          <div key={value} className="flex items-center gap-2">
                            <span className="text-sm text-gray-600 w-24 truncate">
                              {value}
                            </span>
                            <div className="flex-1 bg-gray-100 rounded-full h-2">
                              <div
                                className="bg-primary-500 rounded-full h-2 transition-all"
                                style={{ width: `${percentage}%` }}
                              />
                            </div>
                            <span className="text-xs text-gray-500 w-12 text-right">
                              {percentage}%
                            </span>
                          </div>
                        );
                      })}
                  </div>
                </div>
              )
            )}
          </div>
        </Card>
      )}

      {cluster.children && cluster.children.length > 0 && (
        <Card title={`Sub-clusters (${cluster.children.length})`}>
          <div className="space-y-2">
            {cluster.children
              .sort((a, b) => b.conversation_count - a.conversation_count)
              .map((child) => (
                <div
                  key={child.id}
                  className="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
                >
                  <div>
                    <p className="font-medium text-gray-900">{child.name}</p>
                    {child.keywords && child.keywords.length > 0 && (
                      <p className="text-sm text-gray-500">
                        {child.keywords.slice(0, 3).join(", ")}
                      </p>
                    )}
                  </div>
                  <span className="text-sm text-gray-500">
                    {child.conversation_count.toLocaleString()}
                  </span>
                </div>
              ))}
          </div>
        </Card>
      )}
    </div>
  );
}

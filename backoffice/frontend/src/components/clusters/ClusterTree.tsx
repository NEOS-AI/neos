"use client";

import { useState, useMemo } from "react";
import { ChevronRight, ChevronDown, Folder, FolderOpen } from "lucide-react";
import { clsx } from "clsx";
import type { Cluster } from "@/types";

interface ClusterTreeProps {
  clusters: Cluster[];
  selectedClusterId?: string | null;
  onSelectCluster?: (cluster: Cluster) => void;
  expandedByDefault?: number;
}

interface TreeNodeProps {
  cluster: Cluster;
  depth: number;
  selectedClusterId?: string | null;
  onSelectCluster?: (cluster: Cluster) => void;
  defaultExpanded: boolean;
}

function TreeNode({
  cluster,
  depth,
  selectedClusterId,
  onSelectCluster,
  defaultExpanded,
}: TreeNodeProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const hasChildren = cluster.children && cluster.children.length > 0;
  const isSelected = selectedClusterId === cluster.id;

  const handleToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    setExpanded(!expanded);
  };

  const handleSelect = () => {
    onSelectCluster?.(cluster);
  };

  return (
    <div>
      <div
        className={clsx(
          "flex items-center py-2 px-2 rounded-lg cursor-pointer transition-colors",
          isSelected
            ? "bg-primary-100 text-primary-900"
            : "hover:bg-gray-100 text-gray-700"
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={handleSelect}
      >
        {hasChildren ? (
          <button
            onClick={handleToggle}
            className="p-0.5 rounded hover:bg-gray-200 mr-1"
          >
            {expanded ? (
              <ChevronDown className="w-4 h-4" />
            ) : (
              <ChevronRight className="w-4 h-4" />
            )}
          </button>
        ) : (
          <span className="w-5 mr-1" />
        )}

        {expanded ? (
          <FolderOpen className="w-4 h-4 mr-2 text-primary-500" />
        ) : (
          <Folder className="w-4 h-4 mr-2 text-gray-400" />
        )}

        <div className="flex-1 min-w-0">
          <span className="font-medium truncate block">{cluster.name}</span>
          <span className="text-xs text-gray-500">
            {cluster.conversation_count.toLocaleString()} conversations
          </span>
        </div>

        {cluster.keywords && cluster.keywords.length > 0 && (
          <div className="hidden lg:flex items-center gap-1 ml-2">
            {cluster.keywords.slice(0, 2).map((keyword, i) => (
              <span
                key={i}
                className="px-1.5 py-0.5 text-xs bg-gray-100 text-gray-600 rounded"
              >
                {keyword}
              </span>
            ))}
          </div>
        )}
      </div>

      {expanded && hasChildren && (
        <div>
          {cluster.children.map((child) => (
            <TreeNode
              key={child.id}
              cluster={child}
              depth={depth + 1}
              selectedClusterId={selectedClusterId}
              onSelectCluster={onSelectCluster}
              defaultExpanded={depth < 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function ClusterTree({
  clusters,
  selectedClusterId,
  onSelectCluster,
  expandedByDefault = 1,
}: ClusterTreeProps) {
  const sortedClusters = useMemo(() => {
    return [...clusters].sort(
      (a, b) => b.conversation_count - a.conversation_count
    );
  }, [clusters]);

  if (!clusters.length) {
    return (
      <div className="text-center py-8 text-gray-500">
        No clusters available
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {sortedClusters.map((cluster) => (
        <TreeNode
          key={cluster.id}
          cluster={cluster}
          depth={0}
          selectedClusterId={selectedClusterId}
          onSelectCluster={onSelectCluster}
          defaultExpanded={cluster.level <= expandedByDefault}
        />
      ))}
    </div>
  );
}

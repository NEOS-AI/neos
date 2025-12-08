"use client";

import { format, formatDistanceToNow } from "date-fns";
import {
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  Trash2,
} from "lucide-react";
import { clsx } from "clsx";
import { Button } from "@/components/ui/Button";
import type { AnalysisRun } from "@/types";

interface AnalysisCardProps {
  analysis: AnalysisRun;
  onSelect?: (analysis: AnalysisRun) => void;
  onDelete?: (analysis: AnalysisRun) => void;
  selected?: boolean;
}

const statusConfig = {
  pending: {
    icon: Clock,
    color: "text-gray-500",
    bg: "bg-gray-100",
    label: "Pending",
  },
  running: {
    icon: Loader2,
    color: "text-blue-500",
    bg: "bg-blue-100",
    label: "Running",
  },
  completed: {
    icon: CheckCircle2,
    color: "text-green-500",
    bg: "bg-green-100",
    label: "Completed",
  },
  failed: {
    icon: XCircle,
    color: "text-red-500",
    bg: "bg-red-100",
    label: "Failed",
  },
  cancelled: {
    icon: XCircle,
    color: "text-gray-500",
    bg: "bg-gray-100",
    label: "Cancelled",
  },
};

export function AnalysisCard({
  analysis,
  onSelect,
  onDelete,
  selected,
}: AnalysisCardProps) {
  const status = statusConfig[analysis.status];
  const StatusIcon = status.icon;

  return (
    <div
      className={clsx(
        "bg-white rounded-lg border shadow-sm p-4 cursor-pointer transition-all",
        selected
          ? "border-primary-500 ring-2 ring-primary-100"
          : "border-gray-200 hover:border-gray-300"
      )}
      onClick={() => onSelect?.(analysis)}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-gray-900 truncate">
            {analysis.name}
          </h3>
          {analysis.description && (
            <p className="text-sm text-gray-500 mt-1 line-clamp-2">
              {analysis.description}
            </p>
          )}
        </div>
        <div
          className={clsx(
            "flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium",
            status.bg,
            status.color
          )}
        >
          <StatusIcon
            className={clsx("w-3 h-3", analysis.status === "running" && "animate-spin")}
          />
          {status.label}
        </div>
      </div>

      {analysis.status === "running" && (
        <div className="mt-3">
          <div className="flex items-center justify-between text-sm mb-1">
            <span className="text-gray-500">{analysis.current_stage}</span>
            <span className="text-gray-700 font-medium">
              {Math.round(analysis.progress_percentage)}%
            </span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-2">
            <div
              className="bg-primary-500 rounded-full h-2 transition-all"
              style={{ width: `${analysis.progress_percentage}%` }}
            />
          </div>
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
        <div>
          <p className="text-gray-500">Conversations</p>
          <p className="font-semibold">
            {analysis.processed_conversations.toLocaleString()} /{" "}
            {analysis.total_conversations.toLocaleString()}
          </p>
        </div>
        <div>
          <p className="text-gray-500">Clusters</p>
          <p className="font-semibold">
            {analysis.total_clusters.toLocaleString()}
          </p>
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between text-xs text-gray-500">
        <span>
          Created{" "}
          {formatDistanceToNow(new Date(analysis.created_at), {
            addSuffix: true,
          })}
        </span>
        {analysis.completed_at && (
          <span>
            Completed {format(new Date(analysis.completed_at), "MMM d, HH:mm")}
          </span>
        )}
      </div>

      {onDelete && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          <Button
            variant="ghost"
            size="sm"
            icon={<Trash2 className="w-4 h-4" />}
            onClick={(e) => {
              e.stopPropagation();
              onDelete(analysis);
            }}
            className="text-red-600 hover:text-red-700 hover:bg-red-50"
          >
            Delete
          </Button>
        </div>
      )}
    </div>
  );
}

"use client";

import { useMemo, useCallback } from "react";
import dynamic from "next/dynamic";
import type { UMAPPoint } from "@/types";

// Dynamically import Plotly to avoid SSR issues
const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

interface UMAPScatterProps {
  points: UMAPPoint[];
  colorBy?: "cluster_id" | "task_type" | "language";
  selectedPointIds?: number[];
  onPointSelect?: (pointIds: number[]) => void;
  height?: number;
}

const TASK_TYPE_COLORS: Record<string, string> = {
  coding: "#3b82f6",
  writing: "#10b981",
  analysis: "#f59e0b",
  creative: "#ec4899",
  learning: "#8b5cf6",
  assistant: "#6b7280",
  other: "#94a3b8",
};

const LANGUAGE_COLORS: Record<string, string> = {
  english: "#3b82f6",
  korean: "#ef4444",
  japanese: "#f59e0b",
  chinese: "#10b981",
  spanish: "#8b5cf6",
  french: "#ec4899",
  other: "#6b7280",
};

export function UMAPScatter({
  points,
  colorBy = "task_type",
  selectedPointIds,
  onPointSelect,
  height = 500,
}: UMAPScatterProps) {
  const plotData = useMemo(() => {
    if (!points.length) return [];

    // Group points by color category
    const groups: Record<string, UMAPPoint[]> = {};

    for (const point of points) {
      let category: string;
      if (colorBy === "cluster_id") {
        category = point.cluster_id?.toString() ?? "unclustered";
      } else if (colorBy === "task_type") {
        category = point.task_type ?? "other";
      } else {
        category = point.language ?? "other";
      }

      if (!groups[category]) {
        groups[category] = [];
      }
      groups[category].push(point);
    }

    // Create traces for each group
    return Object.entries(groups).map(([category, groupPoints]) => {
      let color: string;
      if (colorBy === "task_type") {
        color = TASK_TYPE_COLORS[category] ?? "#6b7280";
      } else if (colorBy === "language") {
        color = LANGUAGE_COLORS[category] ?? "#6b7280";
      } else {
        // Generate color based on cluster ID
        const hue = (parseInt(category) * 137) % 360;
        color = `hsl(${hue}, 70%, 50%)`;
      }

      return {
        type: "scattergl" as const,
        mode: "markers" as const,
        name: category,
        x: groupPoints.map((p) => p.x),
        y: groupPoints.map((p) => p.y),
        customdata: groupPoints.map((p) => p.conversation_id),
        marker: {
          size: 4,
          color,
          opacity: 0.7,
        },
        hovertemplate:
          `<b>${colorBy === "cluster_id" ? "Cluster" : category}</b><br>` +
          "x: %{x:.2f}<br>" +
          "y: %{y:.2f}<br>" +
          "<extra></extra>",
      };
    });
  }, [points, colorBy]);

  const layout = useMemo(
    () => ({
      autosize: true,
      height,
      margin: { l: 40, r: 20, t: 20, b: 40 },
      xaxis: {
        title: "UMAP 1",
        zeroline: false,
        gridcolor: "#f3f4f6",
      },
      yaxis: {
        title: "UMAP 2",
        zeroline: false,
        gridcolor: "#f3f4f6",
      },
      showlegend: true,
      legend: {
        orientation: "h" as const,
        yanchor: "bottom" as const,
        y: 1.02,
        xanchor: "right" as const,
        x: 1,
      },
      hovermode: "closest" as const,
      dragmode: "select" as const,
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
    }),
    [height]
  );

  const handleSelect = useCallback(
    (event: Readonly<Plotly.PlotSelectionEvent>) => {
      if (!onPointSelect || !event.points) return;

      const selectedIds = event.points.map(
        (p) => p.customdata as number
      );
      onPointSelect(selectedIds);
    },
    [onPointSelect]
  );

  if (!points.length) {
    return (
      <div
        className="flex items-center justify-center bg-gray-50 rounded-lg"
        style={{ height }}
      >
        <p className="text-gray-500">No data available</p>
      </div>
    );
  }

  return (
    <Plot
      data={plotData}
      layout={layout}
      config={{
        responsive: true,
        displayModeBar: true,
        modeBarButtonsToRemove: ["lasso2d", "autoScale2d"],
      }}
      onSelected={handleSelect}
      style={{ width: "100%", height }}
    />
  );
}

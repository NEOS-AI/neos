"use client";

import { useMemo } from "react";
import dynamic from "next/dynamic";
import type { FacetDistribution } from "@/types";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

interface FacetChartProps {
  data: FacetDistribution;
  chartType?: "bar" | "pie" | "donut";
  height?: number;
}

export function FacetChart({
  data,
  chartType = "bar",
  height = 300,
}: FacetChartProps) {
  const plotData = useMemo(() => {
    const entries = Object.entries(data.distribution).sort(
      ([, a], [, b]) => b - a
    );

    const labels = entries.map(([label]) => label);
    const values = entries.map(([, value]) => value);

    if (chartType === "pie" || chartType === "donut") {
      return [
        {
          type: "pie" as const,
          labels,
          values,
          hole: chartType === "donut" ? 0.4 : 0,
          textinfo: "label+percent",
          hovertemplate: "%{label}<br>%{value} (%{percent})<extra></extra>",
          marker: {
            colors: [
              "#3b82f6",
              "#10b981",
              "#f59e0b",
              "#ec4899",
              "#8b5cf6",
              "#ef4444",
              "#06b6d4",
              "#84cc16",
            ],
          },
        },
      ];
    }

    return [
      {
        type: "bar" as const,
        x: values,
        y: labels,
        orientation: "h" as const,
        marker: {
          color: "#3b82f6",
        },
        hovertemplate: "%{y}<br>%{x} conversations<extra></extra>",
      },
    ];
  }, [data, chartType]);

  const layout = useMemo(
    () => ({
      autosize: true,
      height,
      margin:
        chartType === "bar"
          ? { l: 100, r: 20, t: 20, b: 40 }
          : { l: 20, r: 20, t: 20, b: 20 },
      xaxis:
        chartType === "bar"
          ? {
              title: "Count",
              gridcolor: "#f3f4f6",
            }
          : undefined,
      yaxis:
        chartType === "bar"
          ? {
              automargin: true,
            }
          : undefined,
      showlegend: chartType !== "bar",
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
    }),
    [chartType, height]
  );

  if (Object.keys(data.distribution).length === 0) {
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
        displayModeBar: false,
      }}
      style={{ width: "100%", height }}
    />
  );
}

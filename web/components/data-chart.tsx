"use client";

import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

const CHART_COLORS = [
  "#6366f1", "#f59e0b", "#10b981", "#ef4444",
  "#3b82f6", "#8b5cf6", "#ec4899", "#14b8a6",
];

interface DataPoint {
  label: string;
  value: number;
}

interface DataChartProps {
  type: "bar" | "line" | "pie";
  data: DataPoint[];
  title?: string;
}

function toRechartsData(data: DataPoint[]) {
  return data.map((d) => ({ name: d.label, value: d.value }));
}

export function DataChart({ type, data, title }: DataChartProps) {
  const chartData = toRechartsData(data);

  return (
    <div className="my-2 rounded-lg border bg-card p-3 shadow-sm">
      {title && (
        <p className="text-sm font-medium text-foreground mb-3">{title}</p>
      )}
      <ResponsiveContainer width="100%" height={240}>
        {type === "bar" ? (
          <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="value" fill={CHART_COLORS[0]} radius={[3, 3, 0, 0]} />
          </BarChart>
        ) : type === "line" ? (
          <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Line
              type="monotone"
              dataKey="value"
              stroke={CHART_COLORS[0]}
              strokeWidth={2}
              dot={{ r: 4 }}
            />
          </LineChart>
        ) : (
          <PieChart>
            <Pie
              data={chartData}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              outerRadius={90}
              label={({ name, percent }) =>
                `${String(name ?? "")} ${((Number(percent) || 0) * 100).toFixed(0)}%`
              }
            >
              {chartData.map((_, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={CHART_COLORS[index % CHART_COLORS.length]}
                />
              ))}
            </Pie>
            <Tooltip />
            <Legend />
          </PieChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

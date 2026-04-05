import { useCallback, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  Brush,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type PageRow = {
  page: number;
  binary: number;
  instruction_count: number;
  max_confidence: number;
};

export type PageCoverageFile = {
  schema_version?: string;
  stage_run_id?: string | null;
  first_page: number;
  last_page: number;
  aggregation?: string;
  pages: PageRow[];
};

type Metric = "max_confidence" | "instruction_count" | "binary";

function metricValue(row: PageRow, m: Metric): number {
  if (m === "binary") return row.binary;
  if (m === "instruction_count") return row.instruction_count;
  return row.max_confidence;
}

export default function App() {
  const [data, setData] = useState<PageCoverageFile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<Metric>("max_confidence");

  const onFile = useCallback((f: File | null) => {
    setError(null);
    setData(null);
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result)) as PageCoverageFile;
        if (!parsed.pages || !Array.isArray(parsed.pages)) {
          throw new Error("Invalid page_coverage.json: missing pages[]");
        }
        setData(parsed);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to parse JSON");
      }
    };
    reader.readAsText(f);
  }, []);

  const chartData = useMemo(() => {
    if (!data?.pages?.length) return [];
    return data.pages.map((row) => ({
      ...row,
      value: metricValue(row, metric),
    }));
  }, [data, metric]);

  const title = data
    ? `Pages ${data.first_page}–${data.last_page} · ${data.pages.length} pages · ${data.aggregation ?? ""}`
    : "Load page_coverage.json";

  return (
    <div style={{ padding: "1.25rem", maxWidth: "min(100%, 1400px)", margin: "0 auto" }}>
      <header style={{ marginBottom: "1rem" }}>
        <h1 style={{ margin: "0 0 0.35rem", fontSize: "1.35rem" }}>Stage 2 · Page coverage</h1>
        <p style={{ margin: 0, color: "#444", fontSize: "0.95rem" }}>
          Open <code>artifacts/stage2_instruction_extraction/page_coverage.json</code> from a Stage 2 run.
          Use the brush below the chart to zoom along the page axis (useful for ~300 pages).
        </p>
      </header>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.75rem",
          alignItems: "center",
          marginBottom: "1rem",
        }}
      >
        <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span>JSON file</span>
          <input
            type="file"
            accept=".json,application/json"
            onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          Metric
          <select
            value={metric}
            onChange={(e) => setMetric(e.target.value as Metric)}
            disabled={!data}
          >
            <option value="max_confidence">Max confidence</option>
            <option value="instruction_count">Instruction count</option>
            <option value="binary">Binary (covered)</option>
          </select>
        </label>
      </div>

      {error && (
        <div
          style={{
            padding: "0.75rem",
            background: "#fde8e8",
            borderRadius: 6,
            marginBottom: "1rem",
            color: "#8b1a1a",
          }}
        >
          {error}
        </div>
      )}

      <section
        style={{
          background: "#fff",
          borderRadius: 8,
          padding: "1rem",
          boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
        }}
      >
        <h2 style={{ margin: "0 0 0.75rem", fontSize: "1rem", fontWeight: 600 }}>{title}</h2>
        {chartData.length === 0 ? (
          <p style={{ margin: 0, color: "#666" }}>No data yet.</p>
        ) : (
          <div style={{ width: "100%", height: 420 }}>
            <ResponsiveContainer>
              <BarChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e8e8e8" />
                <XAxis
                  dataKey="page"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  tick={{ fontSize: 11 }}
                  height={36}
                  label={{ value: "Page", position: "insideBottom", offset: -2 }}
                />
                <YAxis
                  tick={{ fontSize: 11 }}
                  domain={metric === "binary" ? [0, 1] : [0, "auto"]}
                  label={{
                    value:
                      metric === "binary"
                        ? "Covered"
                        : metric === "instruction_count"
                          ? "Count"
                          : "Confidence",
                    angle: -90,
                    position: "insideLeft",
                  }}
                />
                <Tooltip
                  formatter={(v: number) => [v, metric]}
                  labelFormatter={(page) => `Page ${page}`}
                />
                <Bar dataKey="value" fill="#2d6cdf" isAnimationActive={false} maxBarSize={12} />
                <Brush
                  dataKey="page"
                  height={28}
                  stroke="#2d6cdf"
                  travellerWidth={8}
                  tickFormatter={(p) => String(p)}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>
    </div>
  );
}

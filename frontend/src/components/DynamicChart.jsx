// src/components/DynamicChart.jsx
// Generic chart renderer — reads all field names from viz config.
// v3 changes:
//   ① KPI card renders properly for single-value scalar results
//      (data = [{metric: "Total Revenue", value: 94328}])
//   ② Table widget renderer added (chart_type === "table")
//   ③ Scatter plot added
//   ④ Pie only renders when data.length ≤ 8 (prevents unreadable pies)

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, LineChart, Line, PieChart, Pie, Cell,
  Legend, ScatterChart, Scatter, ZAxis,
} from "recharts";

const THEMES = {
  default: [
    "#4f8ef7","#3dd68c","#f5a623","#9b7ff4",
    "#f06060","#38bdf8","#fb923c","#a3e635"
  ],
  blue: [
    "#3b82f6", "#60a5fa", "#2563eb", "#93c5fd",
    "#1d4ed8", "#bfdbfe", "#1e40af", "#1e3a8a"
  ],
  red: [
    "#ef4444", "#f87171", "#dc2626", "#fca5a5",
    "#b91c1c", "#fecaca", "#991b1b", "#7f1d1d"
  ],
  green: [
    "#22c55e", "#4ade80", "#16a34a", "#86efac",
    "#15803d", "#bbf7d0", "#166534", "#14532d"
  ],
  dark: [
    "#475569", "#64748b", "#334155", "#94a3b8",
    "#1e293b", "#cbd5e1", "#0f172a", "#f1f5f9"
  ],
  pastel: [
    "#fecdd3", "#fde68a", "#bbf7d0", "#bfdbfe",
    "#ddd6fe", "#fbcfe8", "#c7d2fe", "#fed7aa"
  ],
  monochrome: [
    "#a1a1aa", "#d4d4d8", "#71717a", "#e4e4e7",
    "#52525b", "#3f3f46", "#27272a", "#18181b"
  ]
};

function getPalette(theme) {
  if (!theme) return THEMES.default;
  const t = theme.toLowerCase();
  for (const key in THEMES) {
    if (t.includes(key)) return THEMES[key];
  }
  return THEMES.default;
}

const TT_STYLE = {
  contentStyle: {
    background: "#171b25",
    border: "1px solid rgba(255,255,255,.07)",
    borderRadius: 6, fontSize: 12, color: "#e8ecf2",
  },
  itemStyle: { color: "#8b92a5" },
  labelStyle: { color: "#e8ecf2", fontWeight: 600 },
};

function fmtVal(v, fmt) {
  try {
    const f = parseFloat(v);
    if (isNaN(f)) return String(v ?? "—");
    if (fmt === "percent") return `${(f * 100).toFixed(1)}%`;
    if (Number.isInteger(f) && f < 1e9) return f.toLocaleString();
    if (Math.abs(f) >= 1_000_000) return `${(f / 1_000_000).toFixed(2)}M`;
    if (Math.abs(f) >= 1_000) return `${(f / 1_000).toFixed(1)}K`;
    return f.toFixed(2);
  } catch (_) { return String(v ?? "—"); }
}

function XTick({ x, y, payload }) {
  const s = String(payload?.value ?? "");
  return (
    <g transform={`translate(${x},${y})`}>
      <text x={0} y={0} dy={12} textAnchor="middle" fill="#545c70" fontSize={10}>
        {s.length > 12 ? s.slice(0, 12) + "…" : s}
      </text>
    </g>
  );
}

function PieLabel({ cx, cy, midAngle, innerRadius, outerRadius, percent }) {
  if (percent < 0.04) return null;
  const R = Math.PI / 180;
  const r = innerRadius + (outerRadius - innerRadius) * 0.55;
  return (
    <text
      x={cx + r * Math.cos(-midAngle * R)}
      y={cy + r * Math.sin(-midAngle * R)}
      fill="#fff" textAnchor="middle" dominantBaseline="central" fontSize={11}
    >
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  );
}

function NoData({ message }) {
  return (
    <div className="chart-no-data">
      {message || "No data available"}
    </div>
  );
}


// ── KPI Card ──────────────────────────────────────────────────────

function KpiCard({ viz }) {
  const { data = [], title, y_format = "number" } = viz;

  // Single-value scalar result: data = [{metric: "...", value: 123}]
  if (data.length === 1 && "metric" in data[0] && "value" in data[0]) {
    const { metric: label, value: raw } = data[0];
    const formatted = fmtVal(raw, y_format);
    return (
      <div className="kpi-single-card">
        <div className="kpi-single-value">{formatted}</div>
        <div className="kpi-single-label">{label || title}</div>
      </div>
    );
  }

  // Multi-value KPI grid (legacy format: [{metric, value}, ...])
  return (
    <div className="kpi-card-grid">
      {data.map((item, i) => (
        <div key={i} className="kpi-item">
          <span className="kpi-label">{item.metric ?? `Stat ${i + 1}`}</span>
          <span className="kpi-value">
            {fmtVal(item.value, y_format)}
          </span>
        </div>
      ))}
    </div>
  );
}


// ── Table widget ──────────────────────────────────────────────────

function TableWidget({ viz }) {
  const { data = [], x_field, y_field, title, y_format = "number" } = viz;
  if (!data.length) return <NoData />;

  const columns = Object.keys(data[0]);

  return (
    <div className="table-widget">
      <div className="table-scroll">
        <table className="result-table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col}>{col.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row, i) => (
              <tr key={i} className={i === 0 ? "top-row" : ""}>
                {columns.map((col) => (
                  <td key={col}>
                    {col === y_field
                      ? fmtVal(row[col], y_format)
                      : String(row[col] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


// ── Main renderer ─────────────────────────────────────────────────

export default function DynamicChart({ viz }) {
  if (!viz) return <NoData />;

  const {
    chart_type,
    data = [],
    x_field,
    y_field,
    label_field,
    value_field,
    y_format = "number",
    color_scheme = "default",
  } = viz;

  const PAL = getPalette(color_scheme);

  if (!data.length) return <NoData />;

  const fmt = (v) => fmtVal(v, y_format);

  // ── KPI card (scalar result) ────────────────────────────────────
  if (chart_type === "kpi_card") {
    return <KpiCard viz={viz} />;
  }

  // ── Table widget ────────────────────────────────────────────────
  if (chart_type === "table") {
    return <TableWidget viz={viz} />;
  }

  // ── Bar chart ───────────────────────────────────────────────────
  if (chart_type === "bar") {
    if (!x_field || !y_field) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={x_field} tick={<XTick />} interval={0} />
          <YAxis tick={{ fill: "#545c70", fontSize: 10 }} width={50} tickFormatter={fmt} />
          <Tooltip {...TT_STYLE} formatter={fmt} />
          <Bar dataKey={y_field} radius={[3, 3, 0, 0]}>
            {data.map((_, i) => <Cell key={i} fill={PAL[i % PAL.length]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  // ── Horizontal bar ──────────────────────────────────────────────
  if (chart_type === "horizontal_bar") {
    if (!x_field || !y_field) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={Math.max(200, data.length * 36)}>
        <BarChart
          layout="vertical" data={data}
          margin={{ top: 4, right: 8, left: 110, bottom: 4 }}
        >
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" tick={{ fill: "#545c70", fontSize: 10 }} tickFormatter={fmt} />
          <YAxis
            type="category" dataKey={x_field}
            tick={{ fill: "#8b92a5", fontSize: 11 }} width={105}
            tickFormatter={(v) => String(v ?? "").slice(0, 18)}
          />
          <Tooltip {...TT_STYLE} formatter={fmt} />
          <Bar dataKey={y_field} radius={[0, 3, 3, 0]}>
            {data.map((_, i) => <Cell key={i} fill={PAL[i % PAL.length]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  // ── Line chart ──────────────────────────────────────────────────
  if (chart_type === "line") {
    if (!x_field || !y_field) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={x_field} tick={<XTick />} interval="preserveStartEnd" />
          <YAxis tick={{ fill: "#545c70", fontSize: 10 }} width={50} tickFormatter={fmt} />
          <Tooltip {...TT_STYLE} formatter={fmt} />
          <Line
            type="monotone" dataKey={y_field}
            stroke={PAL[0]} strokeWidth={2}
            dot={{ fill: PAL[0], r: 3 }} activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // ── Histogram ───────────────────────────────────────────────────
  if (chart_type === "histogram") {
    const xk = x_field || "range";
    const yk = y_field || "count";
    return (
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={xk} tick={<XTick />} interval={0} />
          <YAxis tick={{ fill: "#545c70", fontSize: 10 }} width={44} />
          <Tooltip {...TT_STYLE} />
          <Bar dataKey={yk} fill={PAL[3]} radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  // ── Pie / Donut ─────────────────────────────────────────────────
  if (chart_type === "pie" || chart_type === "donut") {
    const lf = label_field || x_field;
    const vf = value_field || y_field;
    if (!lf || !vf) return <NoData />;
    // Warn if too many slices — degrade to bar
    if (data.length > 8) {
      return (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 20 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey={lf} tick={<XTick />} interval={0} />
            <YAxis tick={{ fill: "#545c70", fontSize: 10 }} width={44} tickFormatter={fmt} />
            <Tooltip {...TT_STYLE} formatter={fmt} />
            <Bar dataKey={vf} radius={[3, 3, 0, 0]}>
              {data.map((_, i) => <Cell key={i} fill={PAL[i % PAL.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      );
    }
    const inner = chart_type === "donut" ? 55 : 0;
    return (
      <ResponsiveContainer width="100%" height={260}>
        <PieChart>
          <Pie
            data={data} dataKey={vf} nameKey={lf}
            cx="50%" cy="50%" outerRadius={95} innerRadius={inner}
            labelLine={false} label={<PieLabel />}
          >
            {data.map((_, i) => <Cell key={i} fill={PAL[i % PAL.length]} />)}
          </Pie>
          <Tooltip {...TT_STYLE} formatter={fmt} />
          <Legend
            iconSize={10} wrapperStyle={{ fontSize: 11, color: "#8b92a5" }}
            formatter={(v) => String(v ?? "").slice(0, 18)}
          />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  // ── Scatter plot ────────────────────────────────────────────────
  if (chart_type === "scatter") {
    if (!x_field || !y_field) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={260}>
        <ScatterChart margin={{ top: 4, right: 8, left: 0, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={x_field} type="number" name={x_field}
                 tick={{ fill: "#545c70", fontSize: 10 }} tickFormatter={fmt} />
          <YAxis dataKey={y_field} type="number" name={y_field}
                 tick={{ fill: "#545c70", fontSize: 10 }} width={50} tickFormatter={fmt} />
          <ZAxis range={[30, 30]} />
          <Tooltip
            {...TT_STYLE}
            cursor={{ strokeDasharray: "3 3" }}
            formatter={fmt}
          />
          <Scatter data={data} fill={PAL[0]} fillOpacity={0.7} />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }

  return <NoData message={`Unknown chart type: ${chart_type}`} />;
}
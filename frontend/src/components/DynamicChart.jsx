// src/components/DynamicChart.jsx
// Renders ANY chart type based purely on the viz config object.
// Reads x_field / y_field / label_field / value_field from the config —
// never uses hardcoded column names like "dx", "age", "sex".
//
// Supported chart_types:
//   bar | horizontal_bar | line | pie | donut | histogram | kpi_card

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line,
  PieChart, Pie, Cell, Legend,
} from "recharts";

// ── colour palette (cycles for multi-series) ─────────────────────
const PALETTE = [
  "#4f8ef7", "#3dd68c", "#f5a623", "#9b7ff4",
  "#f06060", "#38bdf8", "#fb923c", "#a3e635",
];

// ── tooltip style ─────────────────────────────────────────────────
const TOOLTIP_STYLE = {
  contentStyle: {
    background: "#1a1e28",
    border: "1px solid rgba(255,255,255,0.07)",
    borderRadius: 6,
    fontSize: 12,
    color: "#e8ecf2",
  },
  itemStyle: { color: "#8b92a5" },
  labelStyle: { color: "#e8ecf2", fontWeight: 600 },
};

// ── axis tick helper ──────────────────────────────────────────────
function truncate(str, max = 12) {
  if (typeof str !== "string") return str;
  return str.length > max ? str.slice(0, max) + "…" : str;
}

function CustomXTick({ x, y, payload }) {
  return (
    <g transform={`translate(${x},${y})`}>
      <text
        x={0} y={0} dy={12}
        textAnchor="middle"
        fill="#545c70"
        fontSize={10}
      >
        {truncate(String(payload.value ?? ""), 10)}
      </text>
    </g>
  );
}

// ── custom label for pie ──────────────────────────────────────────
function PieLabel({ cx, cy, midAngle, innerRadius, outerRadius, percent }) {
  if (percent < 0.05) return null;
  const RADIAN = Math.PI / 180;
  const radius = innerRadius + (outerRadius - innerRadius) * 0.55;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
  return (
    <text x={x} y={y} fill="#fff" textAnchor="middle" dominantBaseline="central" fontSize={11}>
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  );
}

// ── no data fallback ──────────────────────────────────────────────
function NoData() {
  return <div className="chart-no-data">No data available</div>;
}

// ═════════════════════════════════════════════════════════════════
// Main component
// ═════════════════════════════════════════════════════════════════
export default function DynamicChart({ viz }) {
  if (!viz) return <NoData />;

  const {
    chart_type,
    data = [],
    x_field,
    y_field,
    label_field,
    value_field,
  } = viz;

  if (!data.length) return <NoData />;

  // ── BAR (vertical) ────────────────────────────────────────────
  if (chart_type === "bar") {
    if (!x_field || !y_field) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={x_field} tick={<CustomXTick />} interval={0} />
          <YAxis tick={{ fill: "#545c70", fontSize: 10 }} width={40} />
          <Tooltip {...TOOLTIP_STYLE} />
          <Bar dataKey={y_field} radius={[3, 3, 0, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  // ── HORIZONTAL BAR ────────────────────────────────────────────
  if (chart_type === "horizontal_bar") {
    if (!x_field || !y_field) return <NoData />;
    // for horizontal bar, swap axes: x_field goes on Y axis, y_field on X
    return (
      <ResponsiveContainer width="100%" height={Math.max(200, data.length * 32)}>
        <BarChart
          layout="vertical"
          data={data}
          margin={{ top: 4, right: 8, left: 90, bottom: 4 }}
        >
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis
            type="number"
            tick={{ fill: "#545c70", fontSize: 10 }}
          />
          <YAxis
            type="category"
            dataKey={x_field}
            tick={{ fill: "#8b92a5", fontSize: 11 }}
            width={85}
            tickFormatter={(v) => truncate(String(v ?? ""), 14)}
          />
          <Tooltip {...TOOLTIP_STYLE} />
          <Bar dataKey={y_field} radius={[0, 3, 3, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  // ── LINE ──────────────────────────────────────────────────────
  if (chart_type === "line") {
    if (!x_field || !y_field) return <NoData />;
    return (
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={x_field} tick={<CustomXTick />} interval="preserveStartEnd" />
          <YAxis tick={{ fill: "#545c70", fontSize: 10 }} width={40} />
          <Tooltip {...TOOLTIP_STYLE} />
          <Line
            type="monotone"
            dataKey={y_field}
            stroke={PALETTE[0]}
            strokeWidth={2}
            dot={{ fill: PALETTE[0], r: 3 }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // ── HISTOGRAM ─────────────────────────────────────────────────
  if (chart_type === "histogram") {
    // histogram uses "range" and "count" fields from backend
    const xKey = x_field || "range";
    const yKey = y_field || "count";
    return (
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={xKey} tick={<CustomXTick />} interval={0} />
          <YAxis tick={{ fill: "#545c70", fontSize: 10 }} width={40} />
          <Tooltip {...TOOLTIP_STYLE} />
          <Bar dataKey={yKey} fill={PALETTE[3]} radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  // ── PIE / DONUT ───────────────────────────────────────────────
  if (chart_type === "pie" || chart_type === "donut") {
    const lf = label_field || x_field;
    const vf = value_field || y_field;
    if (!lf || !vf) return <NoData />;

    const innerRadius = chart_type === "donut" ? 55 : 0;

    return (
      <ResponsiveContainer width="100%" height={260}>
        <PieChart>
          <Pie
            data={data}
            dataKey={vf}
            nameKey={lf}
            cx="50%"
            cy="50%"
            outerRadius={95}
            innerRadius={innerRadius}
            labelLine={false}
            label={<PieLabel />}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
            ))}
          </Pie>
          <Tooltip
            {...TOOLTIP_STYLE}
            formatter={(value, name) => [value.toLocaleString(), name]}
          />
          <Legend
            iconSize={10}
            wrapperStyle={{ fontSize: 11, color: "#8b92a5" }}
            formatter={(value) => truncate(String(value ?? ""), 18)}
          />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  // ── KPI CARD ──────────────────────────────────────────────────
  if (chart_type === "kpi_card") {
    return (
      <div className="kpi-card-grid">
        {data.map((item, i) => (
          <div key={i} className="kpi-item">
            <span className="kpi-label">{item.metric ?? `Metric ${i + 1}`}</span>
            <span className="kpi-value">
              {typeof item.value === "number"
                ? item.value.toLocaleString(undefined, { maximumFractionDigits: 2 })
                : item.value ?? "—"}
            </span>
          </div>
        ))}
      </div>
    );
  }

  return <NoData />;
}
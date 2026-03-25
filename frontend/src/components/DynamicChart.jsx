// src/components/DynamicChart.jsx
// ─────────────────────────────────────────────────────────────────────
// Renders ANY visualization object returned by /dashboard.
// Zero hardcoded field names — everything is read from the viz config.
// ─────────────────────────────────────────────────────────────────────
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
  LineChart, Line, CartesianGrid,
  PieChart, Pie, Legend,
} from "recharts";

// ── design tokens (mirrored from App.css CSS vars) ─────────────────
const COLORS  = ["#5b8dee", "#f5a623", "#3ecf8e", "#f16b6b", "#a78bfa", "#38bdf8", "#fb923c", "#34d399"];
const AMBER   = "#f5a623";
const BLUE    = "#5b8dee";
const GREEN   = "#3ecf8e";

// ── shared tooltip ──────────────────────────────────────────────────
function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "var(--bg-3)",
      border: "1px solid var(--border-hover)",
      borderRadius: 6,
      padding: "10px 14px",
      fontFamily: "var(--font-mono)",
      fontSize: 12,
      color: "var(--text-primary)",
      boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
    }}>
      <div style={{ color: "var(--text-secondary)", marginBottom: 4 }}>{label}</div>
      <div style={{ color: "var(--accent)", fontWeight: 500 }}>
        {typeof payload[0].value === "number"
          ? payload[0].value.toLocaleString()
          : payload[0].value}
      </div>
    </div>
  );
}

// ── individual renderers ────────────────────────────────────────────

function BarViz({ viz }) {
  const { data, x_field, y_field, chart_type } = viz;
  const layout = chart_type === "horizontal_bar" ? "vertical" : "horizontal";

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart
        data={data}
        layout={layout}
        margin={{ top: 4, right: 8, left: layout === "vertical" ? 80 : -16, bottom: 0 }}
      >
        {layout === "horizontal" ? (
          <>
            <XAxis dataKey={x_field} tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
          </>
        ) : (
          <>
            <XAxis type="number" tick={{ fontSize: 10 }} />
            <YAxis type="category" dataKey={x_field} tick={{ fontSize: 10 }} width={80} />
          </>
        )}
        <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
        <Bar dataKey={y_field} radius={[3, 3, 0, 0]}>
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} fillOpacity={0.85} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function LineViz({ viz }) {
  const { data, x_field, y_field } = viz;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey={x_field} tick={{ fontSize: 10 }} />
        <YAxis tick={{ fontSize: 10 }} />
        <Tooltip content={<CustomTooltip />} />
        <Line
          type="monotone"
          dataKey={y_field}
          stroke={BLUE}
          strokeWidth={2}
          dot={{ r: 3, fill: BLUE }}
          activeDot={{ r: 5 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

function HistogramViz({ viz }) {
  // histogram uses range/count but is fully driven by viz config
  const { data, x_field, y_field } = viz;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }} barCategoryGap="4%">
        <XAxis dataKey={x_field} tick={{ fontSize: 9 }} />
        <YAxis tick={{ fontSize: 10 }} />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
        <Bar dataKey={y_field} fill={GREEN} fillOpacity={0.8} radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function PieViz({ viz }) {
  const { data, label_field, value_field } = viz;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={50}
          outerRadius={78}
          paddingAngle={3}
          dataKey={value_field}
          nameKey={label_field}
        >
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          formatter={(v, n) => [v.toLocaleString(), n]}
          contentStyle={{
            background: "var(--bg-3)",
            border: "1px solid var(--border-hover)",
            borderRadius: 6,
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--text-primary)",
          }}
        />
        <Legend
          iconType="circle"
          iconSize={8}
          formatter={(v) => (
            <span style={{ color: "var(--text-secondary)", fontSize: 11, fontFamily: "var(--font-mono)" }}>
              {v}
            </span>
          )}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

function KpiCardViz({ viz }) {
  const { data } = viz;
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "repeat(2, 1fr)",
      gap: 12,
      padding: "8px 0",
    }}>
      {data.map(({ metric, value }) => (
        <div key={metric} style={{
          background: "var(--bg-3)",
          border: "1px solid var(--border)",
          borderRadius: 6,
          padding: "12px 14px",
        }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>
            {metric}
          </div>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 20, fontWeight: 700, color: "var(--accent)" }}>
            {typeof value === "number" ? value.toLocaleString() : value}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── main export ─────────────────────────────────────────────────────

/**
 * Drop-in chart renderer.
 * Pass any visualization object from /dashboard and it picks the
 * correct chart type automatically — no switch statement needed in the parent.
 */
export default function DynamicChart({ viz }) {
  if (!viz?.data?.length) return (
    <div style={{ padding: "20px 0", color: "var(--text-muted)", fontSize: 13, fontFamily: "var(--font-mono)" }}>
      No data available for this chart.
    </div>
  );

  switch (viz.chart_type) {
    case "bar":
    case "horizontal_bar":
      return <BarViz viz={viz} />;
    case "line":
      return <LineViz viz={viz} />;
    case "histogram":
      return <HistogramViz viz={viz} />;
    case "pie":
    case "donut":
      return <PieViz viz={viz} />;
    case "kpi_card":
      return <KpiCardViz viz={viz} />;
    default:
      return <BarViz viz={viz} />;  // safe fallback
  }
}
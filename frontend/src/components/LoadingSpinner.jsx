// src/components/ChartPanel.jsx
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
  PieChart, Pie, Legend,
} from "recharts";

// ── Shared palette ─────────────────────────────────────────
const AMBER   = "#f5a623";
const BLUE    = "#5b8dee";
const GREEN   = "#3ecf8e";
const PIE_COLORS = ["#5b8dee", "#f5a623", "#3ecf8e", "#f16b6b", "#a78bfa"];

// ── Custom Tooltip ──────────────────────────────────────────
function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "var(--bg-3)",
      border: "1px solid var(--border-hover)",
      borderRadius: "6px",
      padding: "10px 14px",
      fontFamily: "var(--font-mono)",
      fontSize: "12px",
      color: "var(--text-primary)",
      boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
    }}>
      <div style={{ color: "var(--text-secondary)", marginBottom: 4 }}>{label}</div>
      <div style={{ color: "var(--accent)", fontWeight: 500 }}>
        {payload[0].value.toLocaleString()}
      </div>
    </div>
  );
}

// ── Dx BarChart ─────────────────────────────────────────────
function DxChart({ data }) {
  if (!data?.length) return null;
  return (
    <div className="chart-card">
      <div className="chart-card-title">Diagnoses Distribution</div>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
          <XAxis dataKey="name" tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
          <Bar dataKey="value" radius={[3, 3, 0, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={i === 0 ? AMBER : BLUE} fillOpacity={0.85} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Age Histogram ───────────────────────────────────────────
function AgeChart({ data }) {
  if (!data?.length) return null;
  return (
    <div className="chart-card">
      <div className="chart-card-title">Age Distribution</div>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: -16, bottom: 0 }} barCategoryGap="4%">
          <XAxis dataKey="range" tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
          <Bar dataKey="count" fill={GREEN} fillOpacity={0.8} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Sex PieChart ────────────────────────────────────────────
function SexChart({ data }) {
  if (!data?.length) return null;
  return (
    <div className="chart-card">
      <div className="chart-card-title">Sex Distribution</div>
      <ResponsiveContainer width="100%" height={220}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={54}
            outerRadius={80}
            paddingAngle={3}
            dataKey="value"
          >
            {data.map((_, i) => (
              <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
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
    </div>
  );
}

// ── Panel ───────────────────────────────────────────────────
export default function ChartPanel({ dx, age, sex }) {
  return (
    <div className="chart-panel">
      <DxChart data={dx} />
      <AgeChart data={age} />
      <SexChart data={sex} />
    </div>
  );
}
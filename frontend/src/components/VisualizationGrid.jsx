// src/components/VisualizationGrid.jsx
// ─────────────────────────────────────────────────────────────────────
// Renders all visualizations returned by /dashboard.
// Completely generic — no column name assumptions.
// ─────────────────────────────────────────────────────────────────────
import DynamicChart from "./DynamicChart";

const CONFIDENCE_COLOR = (c) => {
  if (c >= 0.85) return "var(--green)";
  if (c >= 0.7)  return "var(--accent)";
  return "var(--text-muted)";
};

function ConfidencePip({ value }) {
  return (
    <span style={{
      fontFamily: "var(--font-mono)",
      fontSize: 9.5,
      color: CONFIDENCE_COLOR(value),
      letterSpacing: "0.05em",
    }}>
      ● {Math.round(value * 100)}% confidence
    </span>
  );
}

export default function VisualizationGrid({ visualizations }) {
  if (!visualizations?.length) return null;

  return (
    <div className="chart-panel">
      {visualizations.map((viz, i) => (
        <div className="chart-card" key={i}>
          {/* header */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16, gap: 8 }}>
            <div className="chart-card-title">{viz.title}</div>
            {viz.confidence != null && <ConfidencePip value={viz.confidence} />}
          </div>

          {/* chart */}
          <DynamicChart viz={viz} />

          {/* why tooltip */}
          {viz.why_this_chart && (
            <div style={{
              marginTop: 12,
              fontFamily: "var(--font-mono)",
              fontSize: 10.5,
              color: "var(--text-muted)",
              borderTop: "1px solid var(--border)",
              paddingTop: 10,
              lineHeight: 1.5,
            }}>
              {viz.why_this_chart}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}